from __future__ import annotations

import hashlib
import secrets
from decimal import Decimal
from typing import Any, cast

import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeDeserializer
from botocore.exceptions import ClientError
from mypy_boto3_dynamodb.service_resource import (
    DynamoDBServiceResource,
    Table,
)

from knowledge_core.ids import new_id
from knowledge_core.models import (
    AnswerStatus,
    DocumentStatus,
    KnowledgeGapCreate,
    NotificationStatus,
    QuestionStatus,
    VerifiedFactCreate,
)
from knowledge_core.time_utils import utc_now_iso


def _project_pk(project_id: str) -> str:
    return f"PROJECT#{project_id}"


def _question_sk(question_id: str) -> str:
    return f"QUESTION#{question_id}"


def _answer_sk(question_id: str, answer_id: str) -> str:
    return f"QUESTION#{question_id}#ANSWER#{answer_id}"


def _reply_pk(reply_token: str) -> str:
    digest = hashlib.sha256(reply_token.encode("utf-8")).hexdigest()
    return f"REPLY#{digest}"


def _email_answer_id(message_id: str) -> str:
    digest = hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:32]
    return f"ans_email_{digest}"


def _plain(value: object) -> Any:
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return float(value)
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        return {str(key): _plain(item) for key, item in mapping.items()}
    if isinstance(value, list):
        return [_plain(item) for item in cast(list[object], value)]
    return value


def _dynamo(value: object) -> Any:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        return {str(key): _dynamo(item) for key, item in mapping.items()}
    if isinstance(value, list):
        return [_dynamo(item) for item in cast(list[object], value)]
    return value


def deserialize_stream_image(image: dict[str, Any]) -> dict[str, Any]:
    deserializer = TypeDeserializer()
    return {
        key: _plain(deserializer.deserialize(value))
        for key, value in image.items()
    }


class KnowledgeRepository:
    def __init__(self, table_name: str, region_name: str | None = None) -> None:
        resource: DynamoDBServiceResource = boto3.resource(
            "dynamodb",
            region_name=region_name,
        )
        self._table: Table = resource.Table(table_name)

    def create_project(
        self,
        *,
        name: str,
        description: str | None,
        created_by: str,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        project_id = project_id or new_id("prj")
        now = utc_now_iso()
        item = {
            "PK": _project_pk(project_id),
            "SK": "META",
            "GSI1PK": "ENTITY#PROJECT",
            "GSI1SK": f"{now}#{project_id}",
            "entity_type": "PROJECT",
            "project_id": project_id,
            "name": name.strip(),
            "description": (description or "").strip() or None,
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
        }
        self._table.put_item(
            Item={
                key: value for key, value in item.items() if value is not None
            },
            ConditionExpression="attribute_not_exists(PK)",
        )
        return item

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        response = self._table.get_item(
            Key={"PK": _project_pk(project_id), "SK": "META"},
            ConsistentRead=True,
        )
        item = response.get("Item")
        return _plain(item) if item else None

    def require_project(self, project_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        if project is None:
            raise KeyError(f"Project {project_id!r} does not exist")
        return project

    def list_projects(self, limit: int = 100) -> list[dict[str, Any]]:
        response = self._table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq("ENTITY#PROJECT"),
            ScanIndexForward=False,
            Limit=limit,
        )
        return [_plain(item) for item in response.get("Items", [])]

    def create_document(
        self,
        *,
        project_id: str,
        document_id: str,
        document_name: str,
        s3_bucket: str,
        s3_key: str,
        content_type: str,
        size_bytes: int,
        status: DocumentStatus,
        uploaded_by: str,
        source_type: str = "UPLOADED",
        document_version: str = "1",
    ) -> dict[str, Any]:
        now = utc_now_iso()
        item = {
            "PK": _project_pk(project_id),
            "SK": f"DOCUMENT#{document_id}",
            "entity_type": "DOCUMENT",
            "project_id": project_id,
            "document_id": document_id,
            "document_version": document_version,
            "document_name": document_name,
            "s3_bucket": s3_bucket,
            "s3_key": s3_key,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "status": status.value,
            "source_type": source_type,
            "uploaded_by": uploaded_by,
            "created_at": now,
            "updated_at": now,
        }
        self._table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(SK)",
        )
        return item

    def put_generated_document(
        self,
        *,
        project_id: str,
        document_id: str,
        document_name: str,
        s3_bucket: str,
        s3_key: str,
        created_by: str,
        size_bytes: int,
    ) -> dict[str, Any]:
        now = utc_now_iso()
        item = {
            "PK": _project_pk(project_id),
            "SK": f"DOCUMENT#{document_id}",
            "entity_type": "DOCUMENT",
            "project_id": project_id,
            "document_id": document_id,
            "document_version": "1",
            "document_name": document_name,
            "s3_bucket": s3_bucket,
            "s3_key": s3_key,
            "content_type": "text/markdown",
            "size_bytes": size_bytes,
            "status": DocumentStatus.READY.value,
            "source_type": "EXPERT_QA",
            "uploaded_by": created_by,
            "created_at": now,
            "updated_at": now,
        }
        self._table.put_item(Item=item)
        return item

    def get_document(
        self,
        *,
        project_id: str,
        document_id: str,
    ) -> dict[str, Any] | None:
        response = self._table.get_item(
            Key={
                "PK": _project_pk(project_id),
                "SK": f"DOCUMENT#{document_id}",
            },
            ConsistentRead=True,
        )
        item = response.get("Item")
        return _plain(item) if item else None

    def list_documents(self, project_id: str) -> list[dict[str, Any]]:
        response = self._table.query(
            KeyConditionExpression=(
                Key("PK").eq(_project_pk(project_id))
                & Key("SK").begins_with("DOCUMENT#")
            ),
            ScanIndexForward=False,
        )
        items = [_plain(item) for item in response.get("Items", [])]
        return sorted(items, key=lambda item: item["created_at"], reverse=True)

    def update_document_status(
        self,
        *,
        project_id: str,
        document_id: str,
        status: DocumentStatus,
        error: str | None = None,
        enhanced_s3_key: str | None = None,
    ) -> dict[str, Any]:
        names = {"#status": "status"}
        values: dict[str, Any] = {
            ":status": status.value,
            ":updated": utc_now_iso(),
        }
        assignments = ["#status = :status", "updated_at = :updated"]
        if error is not None:
            names["#error"] = "error"
            assignments.append("#error = :error")
            values[":error"] = error[:4000]
        if enhanced_s3_key is not None:
            assignments.append("enhanced_s3_key = :enhanced_s3_key")
            values[":enhanced_s3_key"] = enhanced_s3_key

        update_expression = (
            "SET "
            + ", ".join(assignments)
            + " REMOVE chunk_count, extracted_s3_key"
        )
        response = self._table.update_item(
            Key={
                "PK": _project_pk(project_id),
                "SK": f"DOCUMENT#{document_id}",
            },
            UpdateExpression=update_expression,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )
        return _plain(response["Attributes"])

    def begin_page_ingestion(
        self,
        *,
        project_id: str,
        document_id: str,
        page_count: int,
        enhanced_s3_key: str,
    ) -> dict[str, Any]:
        if page_count <= 0:
            raise ValueError("page_count must be positive")
        response = self._table.update_item(
            Key={
                "PK": _project_pk(project_id),
                "SK": f"DOCUMENT#{document_id}",
            },
            UpdateExpression=(
                "SET #status = :status, updated_at = :updated, "
                "page_count = :page_count, "
                "enhanced_s3_key = :enhanced_s3_key, "
                "processing_mode = :processing_mode "
                "REMOVE completed_pages, page_jobs_scheduled, #error"
            ),
            ExpressionAttributeNames={
                "#status": "status",
                "#error": "error",
            },
            ExpressionAttributeValues={
                ":status": DocumentStatus.EMBEDDING.value,
                ":updated": utc_now_iso(),
                ":page_count": page_count,
                ":enhanced_s3_key": enhanced_s3_key,
                ":processing_mode": "PAGE",
            },
            ReturnValues="ALL_NEW",
        )
        return _plain(response["Attributes"])

    def record_completed_page(
        self,
        *,
        project_id: str,
        document_id: str,
        page_number: int,
    ) -> dict[str, Any]:
        if page_number <= 0:
            raise ValueError("page_number must be positive")
        response = self._table.update_item(
            Key={
                "PK": _project_pk(project_id),
                "SK": f"DOCUMENT#{document_id}",
            },
            UpdateExpression=(
                "SET updated_at = :updated ADD completed_pages :page"
            ),
            ExpressionAttributeValues={
                ":updated": utc_now_iso(),
                ":page": {str(page_number)},
            },
            ReturnValues="ALL_NEW",
        )
        return _plain(response["Attributes"])

    def mark_page_jobs_scheduled(
        self,
        *,
        project_id: str,
        document_id: str,
    ) -> dict[str, Any]:
        response = self._table.update_item(
            Key={
                "PK": _project_pk(project_id),
                "SK": f"DOCUMENT#{document_id}",
            },
            UpdateExpression=(
                "SET page_jobs_scheduled = :scheduled, updated_at = :updated"
            ),
            ExpressionAttributeValues={
                ":scheduled": True,
                ":updated": utc_now_iso(),
            },
            ReturnValues="ALL_NEW",
        )
        return _plain(response["Attributes"])

    def create_question(
        self,
        *,
        project_id: str,
        gap: KnowledgeGapCreate,
        created_by: str,
        question_id: str | None = None,
        reply_domain: str | None = None,
        notification_status: NotificationStatus = NotificationStatus.DISABLED,
    ) -> dict[str, Any]:
        project = self.require_project(project_id)
        question_id = question_id or new_id("gap")
        now = utc_now_iso()
        status = QuestionStatus.OPEN.value
        email = gap.assigned_expert_email.strip().casefold()
        reply_token = secrets.token_hex(24) if reply_domain else None
        reply_address = (
            f"kg-{reply_token}@{reply_domain.strip().casefold().rstrip('.')}"
            if reply_token and reply_domain
            else None
        )
        item = {
            "PK": _project_pk(project_id),
            "SK": _question_sk(question_id),
            "GSI1PK": f"EXPERT#{email}",
            "GSI1SK": f"{status}#{now}#{project_id}#{question_id}",
            "entity_type": "QUESTION",
            "project_id": project_id,
            "project_name": project["name"],
            "question_id": question_id,
            "question": gap.question.strip(),
            "context": (gap.context or "").strip() or None,
            "assigned_expert_email": email,
            "priority": gap.priority,
            "status": status,
            "reply_address": reply_address,
            "notification_status": notification_status.value,
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
        }
        question_item = {
            key: value for key, value in item.items() if value is not None
        }
        self._table.put_item(
            Item=question_item,
            ConditionExpression="attribute_not_exists(SK)",
        )
        if reply_token is not None:
            reply_item = {
                "PK": _reply_pk(reply_token),
                "SK": "META",
                "entity_type": "REPLY_ROUTE",
                "project_id": project_id,
                "question_id": question_id,
                "assigned_expert_email": email,
                "created_at": now,
            }
            try:
                self._table.put_item(
                    Item=reply_item,
                    ConditionExpression="attribute_not_exists(PK)",
                )
            except Exception:
                self._table.delete_item(
                    Key={
                        "PK": _project_pk(project_id),
                        "SK": _question_sk(question_id),
                    }
                )
                raise
        return item

    def get_question_by_reply_token(
        self,
        reply_token: str,
    ) -> dict[str, Any] | None:
        response = self._table.get_item(
            Key={"PK": _reply_pk(reply_token), "SK": "META"},
            ConsistentRead=True,
        )
        route = response.get("Item")
        if route is None:
            return None
        route = _plain(route)
        return self.get_question(
            project_id=route["project_id"],
            question_id=route["question_id"],
        )

    def update_question_notification(
        self,
        *,
        project_id: str,
        question_id: str,
        status: NotificationStatus,
        message_id: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        values: dict[str, Any] = {
            ":status": status.value,
            ":updated": utc_now_iso(),
        }
        assignments = [
            "notification_status = :status",
            "updated_at = :updated",
        ]
        removals: list[str] = []
        if message_id is not None:
            assignments.extend(
                [
                    "notification_message_id = :message_id",
                    "notification_sent_at = :sent_at",
                ]
            )
            values[":message_id"] = message_id
            values[":sent_at"] = utc_now_iso()
            removals.append("notification_error")
        if error is not None:
            assignments.append("notification_error = :error")
            values[":error"] = error[:4000]

        expression = "SET " + ", ".join(assignments)
        if removals:
            expression += " REMOVE " + ", ".join(removals)
        response = self._table.update_item(
            Key={
                "PK": _project_pk(project_id),
                "SK": _question_sk(question_id),
            },
            UpdateExpression=expression,
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )
        return _plain(response["Attributes"])

    def get_question(
        self,
        *,
        project_id: str,
        question_id: str,
    ) -> dict[str, Any] | None:
        response = self._table.get_item(
            Key={
                "PK": _project_pk(project_id),
                "SK": _question_sk(question_id),
            },
            ConsistentRead=True,
        )
        item = response.get("Item")
        return _plain(item) if item else None

    def list_project_questions(
        self,
        project_id: str,
    ) -> list[dict[str, Any]]:
        response = self._table.query(
            KeyConditionExpression=(
                Key("PK").eq(_project_pk(project_id))
                & Key("SK").begins_with("QUESTION#")
            ),
        )
        items = [
            _plain(item)
            for item in response.get("Items", [])
            if item.get("entity_type") == "QUESTION"
        ]
        return sorted(items, key=lambda item: item["created_at"], reverse=True)

    def list_assigned_questions(
        self,
        expert_email: str,
        *,
        include_resolved: bool = False,
    ) -> list[dict[str, Any]]:
        email = expert_email.strip().casefold()
        response = self._table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq(f"EXPERT#{email}"),
            ScanIndexForward=False,
        )
        items = [
            _plain(item)
            for item in response.get("Items", [])
            if item.get("entity_type") == "QUESTION"
        ]
        if not include_resolved:
            items = [
                item
                for item in items
                if item.get("status") != QuestionStatus.RESOLVED.value
            ]
        return items

    def list_question_answers(
        self,
        *,
        project_id: str,
        question_id: str,
    ) -> list[dict[str, Any]]:
        response = self._table.query(
            KeyConditionExpression=(
                Key("PK").eq(_project_pk(project_id))
                & Key("SK").begins_with(f"QUESTION#{question_id}#ANSWER#")
            ),
            ConsistentRead=True,
        )
        answers = [
            _plain(item)
            for item in response.get("Items", [])
            if item.get("entity_type") == "ANSWER"
        ]
        return sorted(
            answers,
            key=lambda item: (item.get("created_at", ""), item["answer_id"]),
        )

    def submit_answer(
        self,
        *,
        project_id: str,
        question_id: str,
        answer: str,
        answered_by: str,
    ) -> dict[str, Any]:
        question = self.get_question(
            project_id=project_id,
            question_id=question_id,
        )
        if question is None:
            raise KeyError(f"Question {question_id!r} does not exist")
        return self._put_answer(
            question=question,
            answer_id=new_id("ans"),
            answer=answer,
            answered_by=answered_by,
            source="WEB",
        )

    def submit_email_answer(
        self,
        *,
        reply_token: str,
        answer: str,
        answered_by: str,
        ses_message_id: str,
        raw_email_bucket: str,
        raw_email_key: str,
        email_subject: str | None = None,
    ) -> dict[str, Any]:
        question = self.get_question_by_reply_token(reply_token)
        if question is None:
            raise KeyError("The reply address does not map to an open question")
        return self._put_answer(
            question=question,
            answer_id=_email_answer_id(ses_message_id),
            answer=answer,
            answered_by=answered_by,
            source="EMAIL",
            source_message_id=ses_message_id,
            raw_email_bucket=raw_email_bucket,
            raw_email_key=raw_email_key,
            email_subject=email_subject,
            return_existing=True,
        )

    def _put_answer(
        self,
        *,
        question: dict[str, Any],
        answer_id: str,
        answer: str,
        answered_by: str,
        source: str,
        source_message_id: str | None = None,
        raw_email_bucket: str | None = None,
        raw_email_key: str | None = None,
        email_subject: str | None = None,
        return_existing: bool = False,
    ) -> dict[str, Any]:
        project_id = question["project_id"]
        question_id = question["question_id"]
        if return_existing:
            response = self._table.get_item(
                Key={
                    "PK": _project_pk(project_id),
                    "SK": _answer_sk(question_id, answer_id),
                },
                ConsistentRead=True,
            )
            existing = response.get("Item")
            if existing is not None:
                return _plain(existing)
        if question["status"] == QuestionStatus.RESOLVED.value:
            raise ValueError("This question is already resolved")

        now = utc_now_iso()
        item = {
            "PK": _project_pk(project_id),
            "SK": _answer_sk(question_id, answer_id),
            "entity_type": "ANSWER",
            "project_id": project_id,
            "project_name": question["project_name"],
            "question_id": question_id,
            "question": question["question"],
            "context": question.get("context"),
            "assigned_expert_email": question["assigned_expert_email"],
            "reply_address": question.get("reply_address"),
            "answer_id": answer_id,
            "answer": answer.strip(),
            "answered_by": answered_by.strip().casefold(),
            "answer_source": source,
            "source_message_id": source_message_id,
            "raw_email_bucket": raw_email_bucket,
            "raw_email_key": raw_email_key,
            "email_subject": (email_subject or "").strip() or None,
            "review_status": AnswerStatus.PENDING.value,
            "created_at": now,
            "updated_at": now,
        }
        clean_item = {
            key: value for key, value in item.items() if value is not None
        }
        try:
            self._table.put_item(
                Item=clean_item,
                ConditionExpression="attribute_not_exists(SK)",
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code != "ConditionalCheckFailedException" or not return_existing:
                raise
            response = self._table.get_item(
                Key={
                    "PK": _project_pk(project_id),
                    "SK": _answer_sk(question_id, answer_id),
                },
                ConsistentRead=True,
            )
            existing = response.get("Item")
            if existing is None:
                raise
            return _plain(existing)
        return item

    def update_answer_follow_up_notification(
        self,
        *,
        project_id: str,
        question_id: str,
        answer_id: str,
        status: NotificationStatus,
        message_id: str | None = None,
        error: str | None = None,
    ) -> None:
        values: dict[str, Any] = {
            ":status": status.value,
            ":updated": utc_now_iso(),
        }
        assignments = [
            "follow_up_notification_status = :status",
            "updated_at = :updated",
        ]
        if message_id is not None:
            assignments.extend(
                [
                    "follow_up_message_id = :message_id",
                    "follow_up_sent_at = :sent_at",
                ]
            )
            values[":message_id"] = message_id
            values[":sent_at"] = utc_now_iso()
        if error is not None:
            assignments.append("follow_up_error = :error")
            values[":error"] = error[:4000]
        self._table.update_item(
            Key={
                "PK": _project_pk(project_id),
                "SK": _answer_sk(question_id, answer_id),
            },
            UpdateExpression="SET " + ", ".join(assignments),
            ExpressionAttributeValues=values,
        )

    def claim_answer_for_review(
        self,
        *,
        project_id: str,
        question_id: str,
        answer_id: str,
        attempt_id: str,
    ) -> bool:
        try:
            self._table.update_item(
                Key={
                    "PK": _project_pk(project_id),
                    "SK": _answer_sk(question_id, answer_id),
                },
                UpdateExpression=(
                    "SET review_status = :processing, review_attempt_id = :attempt, "
                    "updated_at = :updated"
                ),
                ConditionExpression="review_status = :pending",
                ExpressionAttributeValues={
                    ":processing": AnswerStatus.PROCESSING.value,
                    ":pending": AnswerStatus.PENDING.value,
                    ":attempt": attempt_id,
                    ":updated": utc_now_iso(),
                },
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def reset_answer_for_retry(
        self,
        *,
        project_id: str,
        question_id: str,
        answer_id: str,
        attempt_id: str,
        error: str,
    ) -> None:
        self._table.update_item(
            Key={
                "PK": _project_pk(project_id),
                "SK": _answer_sk(question_id, answer_id),
            },
            UpdateExpression=(
                "SET review_status = :pending, review_error = :error, "
                "updated_at = :updated REMOVE review_attempt_id"
            ),
            ConditionExpression="review_attempt_id = :attempt",
            ExpressionAttributeValues={
                ":pending": AnswerStatus.PENDING.value,
                ":error": error[:4000],
                ":updated": utc_now_iso(),
                ":attempt": attempt_id,
            },
        )

    def complete_answer_review(
        self,
        *,
        project_id: str,
        question_id: str,
        answer_id: str,
        attempt_id: str,
        accepted: bool,
        confidence: float,
        rationale: str,
        missing_details: list[str],
        generated_document_id: str | None = None,
    ) -> None:
        answer_status = (
            AnswerStatus.ACCEPTED.value
            if accepted
            else AnswerStatus.NEEDS_MORE_INFO.value
        )
        values = {
            ":status": answer_status,
            ":confidence": Decimal(str(confidence)),
            ":rationale": rationale,
            ":missing": missing_details,
            ":updated": utc_now_iso(),
            ":attempt": attempt_id,
        }
        assignments = [
            "review_status = :status",
            "review_confidence = :confidence",
            "review_rationale = :rationale",
            "missing_details = :missing",
            "updated_at = :updated",
        ]
        if generated_document_id:
            assignments.append("generated_document_id = :document")
            values[":document"] = generated_document_id

        self._table.update_item(
            Key={
                "PK": _project_pk(project_id),
                "SK": _answer_sk(question_id, answer_id),
            },
            UpdateExpression=(
                "SET " + ", ".join(assignments) + " REMOVE review_attempt_id"
            ),
            ConditionExpression="review_attempt_id = :attempt",
            ExpressionAttributeValues=values,
        )

    def update_question_after_review(
        self,
        *,
        project_id: str,
        question_id: str,
        accepted: bool,
        answer_id: str,
        generated_document_id: str | None,
        review_rationale: str,
    ) -> None:
        question = self.get_question(
            project_id=project_id,
            question_id=question_id,
        )
        if question is None:
            raise KeyError(f"Question {question_id!r} no longer exists")
        status = (
            QuestionStatus.RESOLVED.value
            if accepted
            else QuestionStatus.NEEDS_MORE_INFO.value
        )
        updated = utc_now_iso()
        values: dict[str, Any] = {
            ":status": status,
            ":gsi": (
                f"{status}#{question['created_at']}#{project_id}#{question_id}"
            ),
            ":answer": answer_id,
            ":rationale": review_rationale,
            ":updated": updated,
        }
        assignments = [
            "#status = :status",
            "GSI1SK = :gsi",
            "latest_answer_id = :answer",
            "review_rationale = :rationale",
            "updated_at = :updated",
        ]
        if generated_document_id:
            assignments.append("generated_document_id = :document")
            values[":document"] = generated_document_id

        self._table.update_item(
            Key={
                "PK": _project_pk(project_id),
                "SK": _question_sk(question_id),
            },
            UpdateExpression="SET " + ", ".join(assignments),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues=values,
        )

    def put_verified_fact(
        self,
        *,
        project_id: str,
        fact: VerifiedFactCreate,
        created_by: str,
        source_document_id: str | None = None,
        fact_id: str | None = None,
    ) -> dict[str, Any]:
        self.require_project(project_id)
        fact_id = fact_id or new_id("fact")
        now = utc_now_iso()
        item = {
            "PK": _project_pk(project_id),
            "SK": f"FACT#{fact_id}",
            "entity_type": "FACT",
            "project_id": project_id,
            "fact_id": fact_id,
            "name": fact.name.strip(),
            "value": fact.value.strip(),
            "provenance": fact.provenance.strip(),
            "source_document_id": source_document_id,
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
        }
        self._table.put_item(
            Item={
                key: value for key, value in item.items() if value is not None
            },
            ConditionExpression="attribute_not_exists(SK)",
        )
        return item

    def get_verified_fact(
        self,
        *,
        project_id: str,
        fact_id: str,
    ) -> dict[str, Any] | None:
        response = self._table.get_item(
            Key={
                "PK": _project_pk(project_id),
                "SK": f"FACT#{fact_id}",
            },
            ConsistentRead=True,
        )
        item = response.get("Item")
        return _plain(item) if item else None

    def list_verified_facts(self, project_id: str) -> list[dict[str, Any]]:
        response = self._table.query(
            KeyConditionExpression=(
                Key("PK").eq(_project_pk(project_id))
                & Key("SK").begins_with("FACT#")
            ),
        )
        items = [_plain(item) for item in response.get("Items", [])]
        return sorted(items, key=lambda item: item["created_at"], reverse=True)
