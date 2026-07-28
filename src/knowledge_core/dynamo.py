from __future__ import annotations

import hashlib
import secrets
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

import boto3
from boto3.dynamodb.conditions import Attr, Key
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import (
        DynamoDBServiceResource,
        Table,
    )
    from mypy_boto3_dynamodb.type_defs import TransactWriteItemTypeDef

from knowledge_core.identity import (
    candidate_surname,
    normalize_blend_email,
    normalize_email,
    normalize_name_tokens,
)
from knowledge_core.ids import new_id
from knowledge_core.models import (
    AnswerStatus,
    ContributorCandidate,
    DocumentStatus,
    InvitationStatus,
    KnowledgeGapCreate,
    MembershipRole,
    MembershipSource,
    NameMatchResult,
    NotificationKind,
    NotificationStatus,
    ProjectStatus,
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


def _user_pk(email: str) -> str:
    return f"USER#{normalize_email(email)}"


def _membership_sk(email: str) -> str:
    return f"MEMBER#{normalize_email(email)}"


def _invitation_sk(invitation_id: str) -> str:
    return f"INVITATION#{invitation_id}"


def _notification_sk(notification_id: str) -> str:
    return f"NOTIFICATION#{notification_id}"


def _suppression_sk(email: str) -> str:
    return f"SUPPRESSION#{normalize_email(email)}"


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


def _serialized(value: object) -> dict[str, Any]:
    serialized = TypeSerializer().serialize(_dynamo(value))
    return cast(dict[str, Any], serialized)


def _serialized_item(item: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {key: _serialized(value) for key, value in item.items()}


def _stable_identifier(prefix: str, *values: str) -> str:
    digest = hashlib.sha256("\0".join(values).encode("utf-8")).hexdigest()[:32]
    return f"{prefix}_{digest}"


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
            "status": ProjectStatus.ACTIVE.value,
            "created_at": now,
            "updated_at": now,
        }
        self._table.put_item(
            Item={
                key: value for key, value in item.items() if value is not None
            },
            ConditionExpression="attribute_not_exists(PK)",
        )
        try:
            normalized_creator = normalize_email(created_by)
        except ValueError:
            normalized_creator = None
        if normalized_creator is not None:
            self.ensure_project_membership(
                project_id=project_id,
                email=normalized_creator,
                role=MembershipRole.AUTHOR,
                source=MembershipSource.PROJECT_AUTHOR,
                created_by=normalized_creator,
            )
        return item

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        response = self._table.get_item(
            Key={"PK": _project_pk(project_id), "SK": "META"},
            ConsistentRead=True,
        )
        item = response.get("Item")
        return _plain(item) if item else None

    def transfer_project_authorship(
        self,
        *,
        project_id: str,
        previous_author_email: str,
        new_author_email: str,
        transferred_by: str,
    ) -> tuple[dict[str, Any], bool]:
        """Atomically replace a project's author and author membership."""
        previous_author = normalize_email(previous_author_email)
        new_author = normalize_email(new_author_email)
        actor = normalize_email(transferred_by)
        project = self.require_project(project_id)
        current_author = normalize_email(str(project.get("created_by") or ""))
        if current_author == new_author:
            return project, False
        if current_author != previous_author:
            raise ValueError(
                f"Project {project_id!r} is authored by {current_author!r}, "
                f"not {previous_author!r}"
            )

        profile = self.get_user_profile(new_author)
        if profile is None or not profile.get("email_verified"):
            raise ValueError(
                f"New author {new_author!r} must be a verified Relay user"
            )
        now = utc_now_iso()
        membership = {
            "PK": _project_pk(project_id),
            "SK": _membership_sk(new_author),
            "GSI1PK": f"USER#{new_author}",
            "GSI1SK": f"MEMBERSHIP#{project_id}",
            "entity_type": "PROJECT_MEMBERSHIP",
            "project_id": project_id,
            "email": new_author,
            "user_subject": profile.get("subject"),
            "role": MembershipRole.AUTHOR.value,
            "source": MembershipSource.PROJECT_AUTHOR.value,
            "evidence": {
                "previous_author_email": previous_author,
                "transferred_by": actor,
            },
            "created_by": actor,
            "created_at": now,
            "updated_at": now,
        }
        clean_membership = {
            key: value for key, value in membership.items() if value is not None
        }
        transaction: list[dict[str, Any]] = [
            {
                "Update": {
                    "TableName": self._table.name,
                    "Key": _serialized_item(
                        {"PK": _project_pk(project_id), "SK": "META"}
                    ),
                    "UpdateExpression": (
                        "SET #created_by = :new_author, "
                        "#updated_at = :updated_at, #updated_by = :actor, "
                        "#transferred_from = :previous_author, "
                        "#transferred_at = :transferred_at, "
                        "#transferred_by = :actor"
                    ),
                    "ConditionExpression": ("#created_by = :previous_author"),
                    "ExpressionAttributeNames": {
                        "#created_by": "created_by",
                        "#updated_at": "updated_at",
                        "#updated_by": "updated_by",
                        "#transferred_from": "author_transferred_from",
                        "#transferred_at": "author_transferred_at",
                        "#transferred_by": "author_transferred_by",
                    },
                    "ExpressionAttributeValues": _serialized_item(
                        {
                            ":new_author": new_author,
                            ":previous_author": previous_author,
                            ":updated_at": now,
                            ":transferred_at": now,
                            ":actor": actor,
                        }
                    ),
                }
            },
            {
                "Put": {
                    "TableName": self._table.name,
                    "Item": _serialized_item(clean_membership),
                }
            },
            {
                "Delete": {
                    "TableName": self._table.name,
                    "Key": _serialized_item(
                        {
                            "PK": _project_pk(project_id),
                            "SK": _membership_sk(previous_author),
                        }
                    ),
                }
            },
        ]
        try:
            self._table.meta.client.transact_write_items(
                TransactItems=cast(Any, transaction)
            )
        except ClientError as exc:
            if (
                exc.response.get("Error", {}).get("Code")
                != "TransactionCanceledException"
            ):
                raise
            current = self.require_project(project_id)
            if (
                str(current.get("created_by") or "").strip().casefold()
                == new_author
            ):
                return current, False
            cancellation_reasons = exc.response.get("CancellationReasons")
            reason_detail = (
                f": {cancellation_reasons!r}" if cancellation_reasons else ""
            )
            raise ValueError(
                f"Project {project_id!r} authorship transfer "
                f"failed{reason_detail}"
            ) from exc
        return (
            {
                **project,
                "created_by": new_author,
                "updated_at": now,
                "updated_by": actor,
                "author_transferred_from": previous_author,
                "author_transferred_at": now,
                "author_transferred_by": actor,
            },
            True,
        )

    def require_project(self, project_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        if project is None:
            raise KeyError(f"Project {project_id!r} does not exist")
        return project

    def rename_project(
        self,
        *,
        project_id: str,
        name: str,
        updated_by: str,
    ) -> dict[str, Any]:
        normalized_name = name.strip()
        if len(normalized_name) < 2:
            raise ValueError("Project name must contain at least 2 characters")
        try:
            response = self._table.update_item(
                Key={"PK": _project_pk(project_id), "SK": "META"},
                UpdateExpression=(
                    "SET #name = :name, updated_at = :updated_at, "
                    "updated_by = :updated_by"
                ),
                ConditionExpression=(
                    "attribute_exists(PK) AND attribute_exists(SK)"
                ),
                ExpressionAttributeNames={"#name": "name"},
                ExpressionAttributeValues={
                    ":name": normalized_name,
                    ":updated_at": utc_now_iso(),
                    ":updated_by": updated_by,
                },
                ReturnValues="ALL_NEW",
            )
        except ClientError as exc:
            if (
                exc.response.get("Error", {}).get("Code")
                == "ConditionalCheckFailedException"
            ):
                raise KeyError(
                    f"Project {project_id!r} does not exist"
                ) from exc
            raise
        return _plain(response["Attributes"])

    def list_projects(
        self,
        limit: int = 1000,
        *,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        projects: list[dict[str, Any]] = []
        exclusive_start_key: dict[str, Any] | None = None
        while len(projects) < limit:
            kwargs: dict[str, Any] = {
                "IndexName": "GSI1",
                "KeyConditionExpression": Key("GSI1PK").eq("ENTITY#PROJECT"),
                "ScanIndexForward": False,
                "Limit": min(100, limit - len(projects)),
            }
            if exclusive_start_key is not None:
                kwargs["ExclusiveStartKey"] = exclusive_start_key
            response = self._table.query(**kwargs)
            projects.extend(_plain(item) for item in response.get("Items", []))
            raw_last_key = response.get("LastEvaluatedKey")
            if not isinstance(raw_last_key, dict) or not raw_last_key:
                break
            exclusive_start_key = raw_last_key
        if not include_archived:
            projects = [
                project
                for project in projects
                if project.get("status", ProjectStatus.ACTIVE.value)
                == ProjectStatus.ACTIVE.value
            ]
        return projects[:limit]

    def set_project_archived(
        self,
        *,
        project_id: str,
        archived: bool,
        updated_by: str,
    ) -> dict[str, Any]:
        project_status = (
            ProjectStatus.ARCHIVED if archived else ProjectStatus.ACTIVE
        )
        try:
            response = self._table.update_item(
                Key={"PK": _project_pk(project_id), "SK": "META"},
                UpdateExpression=(
                    "SET #status = :status, updated_at = :updated, "
                    "updated_by = :updated_by"
                ),
                ConditionExpression=(
                    "attribute_exists(PK) AND attribute_exists(SK)"
                ),
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":status": project_status.value,
                    ":updated": utc_now_iso(),
                    ":updated_by": updated_by,
                },
                ReturnValues="ALL_NEW",
            )
        except ClientError as exc:
            if (
                exc.response.get("Error", {}).get("Code")
                == "ConditionalCheckFailedException"
            ):
                raise KeyError(
                    f"Project {project_id!r} does not exist"
                ) from exc
            raise
        return _plain(response["Attributes"])

    def put_user_profile(
        self,
        *,
        subject: str,
        email: str,
        display_name: str,
        identity_source: str,
        email_verified: bool,
    ) -> dict[str, Any]:
        normalized_email = normalize_email(email)
        if not email_verified:
            raise ValueError("A user profile requires a verified email")
        now = utc_now_iso()
        item = {
            "PK": _user_pk(normalized_email),
            "SK": "META",
            "GSI1PK": "ENTITY#USER",
            "GSI1SK": normalized_email,
            "entity_type": "USER_PROFILE",
            "subject": subject,
            "email": normalized_email,
            "display_name": display_name.strip() or normalized_email,
            "identity_source": identity_source,
            "email_verified": True,
            "updated_at": now,
        }
        self._table.put_item(Item=item)
        memberships = self._table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq(f"USER#{normalized_email}"),
        )
        for membership in memberships.get("Items", []):
            if membership.get("entity_type") != "PROJECT_MEMBERSHIP":
                continue
            self._table.update_item(
                Key={"PK": membership["PK"], "SK": membership["SK"]},
                UpdateExpression=(
                    "SET user_subject = :subject, updated_at = :updated"
                ),
                ExpressionAttributeValues={
                    ":subject": subject,
                    ":updated": now,
                },
            )
        return item

    def get_user_profile(self, email: str) -> dict[str, Any] | None:
        response = self._table.get_item(
            Key={"PK": _user_pk(email), "SK": "META"},
            ConsistentRead=True,
        )
        item = response.get("Item")
        return _plain(item) if item else None

    def list_user_profiles(self, limit: int = 1000) -> list[dict[str, Any]]:
        response = self._table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq("ENTITY#USER"),
            Limit=limit,
        )
        return [
            _plain(item)
            for item in response.get("Items", [])
            if item.get("entity_type") == "USER_PROFILE"
        ]

    def ensure_project_membership(
        self,
        *,
        project_id: str,
        email: str,
        role: MembershipRole,
        source: MembershipSource,
        created_by: str,
        user_subject: str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        normalized_email = normalize_email(email)
        if user_subject is None:
            profile = self.get_user_profile(normalized_email)
            if profile is not None and profile.get("subject"):
                user_subject = str(profile["subject"])
        suppression: dict[str, Any] | None = None
        if source in {
            MembershipSource.DOCUMENT_EXACT_EMAIL,
            MembershipSource.DOCUMENT_NAME_MATCH,
        }:
            suppression = self.get_collaborator_suppression(
                project_id=project_id,
                email=normalized_email,
            )
            if suppression is not None and (
                suppression.get("reason") == "MEMBERSHIP_REMOVED"
                or source == MembershipSource.DOCUMENT_NAME_MATCH
            ):
                return suppression, False

        now = utc_now_iso()
        item = {
            "PK": _project_pk(project_id),
            "SK": _membership_sk(normalized_email),
            "GSI1PK": f"USER#{normalized_email}",
            "GSI1SK": f"MEMBERSHIP#{project_id}",
            "entity_type": "PROJECT_MEMBERSHIP",
            "project_id": project_id,
            "email": normalized_email,
            "user_subject": user_subject,
            "role": role.value,
            "source": source.value,
            "evidence": evidence,
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
        }
        clean_item = {
            key: value for key, value in item.items() if value is not None
        }
        automatic_source = source in {
            MembershipSource.DOCUMENT_EXACT_EMAIL,
            MembershipSource.DOCUMENT_NAME_MATCH,
        }
        try:
            if automatic_source:
                suppression_key = _serialized_item(
                    {
                        "PK": _project_pk(project_id),
                        "SK": _suppression_sk(normalized_email),
                    }
                )
                suppression_guard: TransactWriteItemTypeDef
                if (
                    source == MembershipSource.DOCUMENT_EXACT_EMAIL
                    and suppression is not None
                    and suppression.get("reason") == "INVITATION_DECLINED"
                ):
                    suppression_guard = {
                        "Delete": {
                            "TableName": self._table.name,
                            "Key": suppression_key,
                            "ConditionExpression": "#reason = :declined",
                            "ExpressionAttributeNames": {"#reason": "reason"},
                            "ExpressionAttributeValues": _serialized_item(
                                {":declined": "INVITATION_DECLINED"}
                            ),
                        }
                    }
                else:
                    suppression_guard = {
                        "ConditionCheck": {
                            "TableName": self._table.name,
                            "Key": suppression_key,
                            "ConditionExpression": "attribute_not_exists(PK)",
                        }
                    }
                transaction: list[TransactWriteItemTypeDef] = [
                    suppression_guard,
                    {
                        "Put": {
                            "TableName": self._table.name,
                            "Item": _serialized_item(clean_item),
                            "ConditionExpression": "attribute_not_exists(SK)",
                        }
                    },
                ]
                self._table.meta.client.transact_write_items(
                    TransactItems=transaction
                )
            else:
                self._table.put_item(
                    Item=clean_item,
                    ConditionExpression="attribute_not_exists(SK)",
                )
        except ClientError as exc:
            expected_codes = (
                {"TransactionCanceledException"}
                if automatic_source
                else {"ConditionalCheckFailedException"}
            )
            if exc.response.get("Error", {}).get("Code") not in expected_codes:
                raise
            suppression = self.get_collaborator_suppression(
                project_id=project_id,
                email=normalized_email,
            )
            if suppression is not None and (
                suppression.get("reason") == "MEMBERSHIP_REMOVED"
                or source == MembershipSource.DOCUMENT_NAME_MATCH
            ):
                return suppression, False
            existing = self.get_project_membership(
                project_id=project_id,
                email=normalized_email,
            )
            if existing is None:
                raise
            return existing, False
        return clean_item, True

    def get_project_membership(
        self,
        *,
        project_id: str,
        email: str,
    ) -> dict[str, Any] | None:
        try:
            normalized_email = normalize_email(email)
        except ValueError:
            return None
        response = self._table.get_item(
            Key={
                "PK": _project_pk(project_id),
                "SK": _membership_sk(normalized_email),
            },
            ConsistentRead=True,
        )
        item = response.get("Item")
        return _plain(item) if item else None

    def is_project_member(self, *, project_id: str, email: str) -> bool:
        project = self.get_project(project_id)
        if project is None:
            return False
        normalized = email.strip().casefold()
        if str(project.get("created_by", "")).strip().casefold() == normalized:
            return True
        membership = self.get_project_membership(
            project_id=project_id,
            email=normalized,
        )
        return bool(
            membership and membership.get("entity_type") == "PROJECT_MEMBERSHIP"
        )

    def list_project_members(
        self,
        project_id: str,
    ) -> list[dict[str, Any]]:
        response = self._table.query(
            KeyConditionExpression=(
                Key("PK").eq(_project_pk(project_id))
                & Key("SK").begins_with("MEMBER#")
            ),
        )
        members = [
            _plain(item)
            for item in response.get("Items", [])
            if item.get("entity_type") == "PROJECT_MEMBERSHIP"
        ]
        project = self.get_project(project_id)
        created_by = (
            str(project.get("created_by") or "") if project is not None else ""
        )
        try:
            normalized_creator = normalize_email(created_by)
        except ValueError:
            normalized_creator = None
        if normalized_creator is not None and all(
            member.get("email") != normalized_creator for member in members
        ):
            assert project is not None
            members.append(
                {
                    "entity_type": "PROJECT_MEMBERSHIP",
                    "project_id": project_id,
                    "email": normalized_creator,
                    "role": MembershipRole.AUTHOR.value,
                    "source": MembershipSource.PROJECT_AUTHOR.value,
                    "created_by": normalized_creator,
                    "created_at": project.get("created_at"),
                    "updated_at": project.get("updated_at"),
                }
            )
        return sorted(
            members,
            key=lambda item: (str(item.get("role")), str(item.get("email"))),
        )

    def remove_project_member(
        self,
        *,
        project_id: str,
        email: str,
        removed_by: str,
    ) -> dict[str, Any]:
        project = self.require_project(project_id)
        if (
            str(project.get("created_by") or "").strip().casefold()
            == email.strip().casefold()
        ):
            raise ValueError("The project author cannot be removed")
        membership = self.get_project_membership(
            project_id=project_id,
            email=email,
        )
        if membership is None:
            raise KeyError(f"{email!r} is not a project collaborator")
        if membership.get("role") == MembershipRole.AUTHOR.value:
            raise ValueError("The project author cannot be removed")
        if membership.get("source") in {
            MembershipSource.DOCUMENT_EXACT_EMAIL.value,
            MembershipSource.DOCUMENT_NAME_MATCH.value,
        }:
            now = utc_now_iso()
            suppression = {
                "PK": _project_pk(project_id),
                "SK": _suppression_sk(email),
                "entity_type": "COLLABORATOR_SUPPRESSION",
                "project_id": project_id,
                "email": normalize_email(email),
                "source": membership["source"],
                "reason": "MEMBERSHIP_REMOVED",
                "removed_by": removed_by,
                "created_at": now,
                "updated_at": now,
            }
            transaction: list[TransactWriteItemTypeDef] = [
                {
                    "Delete": {
                        "TableName": self._table.name,
                        "Key": _serialized_item(
                            {
                                "PK": _project_pk(project_id),
                                "SK": _membership_sk(email),
                            }
                        ),
                    }
                },
                {
                    "Put": {
                        "TableName": self._table.name,
                        "Item": _serialized_item(suppression),
                    }
                },
            ]
            self._table.meta.client.transact_write_items(
                TransactItems=transaction
            )
        else:
            self._table.delete_item(
                Key={
                    "PK": _project_pk(project_id),
                    "SK": _membership_sk(email),
                }
            )
        return membership

    def get_collaborator_suppression(
        self,
        *,
        project_id: str,
        email: str,
    ) -> dict[str, Any] | None:
        response = self._table.get_item(
            Key={
                "PK": _project_pk(project_id),
                "SK": _suppression_sk(email),
            },
            ConsistentRead=True,
        )
        item = response.get("Item")
        return _plain(item) if item is not None else None

    def clear_collaborator_suppression(
        self,
        *,
        project_id: str,
        email: str,
    ) -> None:
        self._table.delete_item(
            Key={
                "PK": _project_pk(project_id),
                "SK": _suppression_sk(email),
            }
        )

    def create_collaboration_invitation(
        self,
        *,
        project_id: str,
        email: str,
        source: MembershipSource,
        invited_by: str,
        evidence: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        normalized_email = normalize_email(email)
        if source == MembershipSource.DOCUMENT_NAME_MATCH:
            suppression = self.get_collaborator_suppression(
                project_id=project_id,
                email=normalized_email,
            )
            if suppression is not None:
                return suppression, False
        invitation_id = _stable_identifier(
            "invite",
            project_id,
            normalized_email,
            source.value,
        )
        now = utc_now_iso()
        item = {
            "PK": _user_pk(normalized_email),
            "SK": _invitation_sk(invitation_id),
            "GSI1PK": _project_pk(project_id),
            "GSI1SK": f"INVITATION#{now}#{invitation_id}",
            "entity_type": "COLLABORATION_INVITATION",
            "invitation_id": invitation_id,
            "project_id": project_id,
            "email": normalized_email,
            "source": source.value,
            "status": InvitationStatus.PENDING.value,
            "evidence": evidence,
            "invited_by": invited_by,
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
            if (
                exc.response.get("Error", {}).get("Code")
                != "ConditionalCheckFailedException"
            ):
                raise
            existing = self.get_collaboration_invitation(
                email=normalized_email,
                invitation_id=invitation_id,
            )
            if existing is None:
                raise
            return existing, False
        return clean_item, True

    def get_collaboration_invitation(
        self,
        *,
        email: str,
        invitation_id: str,
    ) -> dict[str, Any] | None:
        response = self._table.get_item(
            Key={
                "PK": _user_pk(email),
                "SK": _invitation_sk(invitation_id),
            },
            ConsistentRead=True,
        )
        item = response.get("Item")
        return _plain(item) if item else None

    def list_collaboration_invitations(
        self,
        *,
        email: str,
        include_decided: bool = False,
    ) -> list[dict[str, Any]]:
        response = self._table.query(
            KeyConditionExpression=(
                Key("PK").eq(_user_pk(email))
                & Key("SK").begins_with("INVITATION#")
            ),
        )
        invitations = [
            _plain(item)
            for item in response.get("Items", [])
            if item.get("entity_type") == "COLLABORATION_INVITATION"
        ]
        if not include_decided:
            invitations = [
                item
                for item in invitations
                if item.get("status") == InvitationStatus.PENDING.value
            ]
        return sorted(
            invitations,
            key=lambda item: str(item.get("created_at", "")),
            reverse=True,
        )

    def decide_collaboration_invitation(
        self,
        *,
        email: str,
        invitation_id: str,
        accepted: bool,
        user_subject: str,
    ) -> dict[str, Any]:
        normalized_email = normalize_email(email)
        invitation = self.get_collaboration_invitation(
            email=normalized_email,
            invitation_id=invitation_id,
        )
        if invitation is None:
            raise KeyError(f"Invitation {invitation_id!r} does not exist")
        target_status = (
            InvitationStatus.ACCEPTED if accepted else InvitationStatus.DECLINED
        )
        current_status = str(invitation.get("status"))
        if current_status == target_status.value:
            return invitation
        if current_status != InvitationStatus.PENDING.value:
            raise ValueError("This invitation has already been decided")

        now = utc_now_iso()
        project_id = str(invitation["project_id"])
        already_member = accepted and self.is_project_member(
            project_id=project_id,
            email=normalized_email,
        )
        transaction: list[TransactWriteItemTypeDef] = [
            {
                "Update": {
                    "TableName": self._table.name,
                    "Key": _serialized_item(
                        {
                            "PK": _user_pk(normalized_email),
                            "SK": _invitation_sk(invitation_id),
                        }
                    ),
                    "UpdateExpression": (
                        "SET #status = :status, decided_at = :now, "
                        "updated_at = :now, decided_by = :email"
                    ),
                    "ConditionExpression": "#status = :pending",
                    "ExpressionAttributeNames": {"#status": "status"},
                    "ExpressionAttributeValues": _serialized_item(
                        {
                            ":status": target_status.value,
                            ":pending": InvitationStatus.PENDING.value,
                            ":now": now,
                            ":email": normalized_email,
                        }
                    ),
                }
            }
        ]
        if accepted and not already_member:
            membership = {
                "PK": _project_pk(project_id),
                "SK": _membership_sk(normalized_email),
                "GSI1PK": f"USER#{normalized_email}",
                "GSI1SK": f"MEMBERSHIP#{project_id}",
                "entity_type": "PROJECT_MEMBERSHIP",
                "project_id": project_id,
                "email": normalized_email,
                "user_subject": user_subject,
                "role": MembershipRole.COLLABORATOR.value,
                "source": str(invitation["source"]),
                "evidence": invitation.get("evidence"),
                "created_by": str(invitation["invited_by"]),
                "created_at": now,
                "updated_at": now,
            }
            transaction.extend(
                [
                    {
                        "Put": {
                            "TableName": self._table.name,
                            "Item": _serialized_item(
                                {
                                    key: value
                                    for key, value in membership.items()
                                    if value is not None
                                }
                            ),
                            "ConditionExpression": (
                                "attribute_not_exists(PK) AND "
                                "attribute_not_exists(SK)"
                            ),
                        }
                    },
                    {
                        "Delete": {
                            "TableName": self._table.name,
                            "Key": _serialized_item(
                                {
                                    "PK": _project_pk(project_id),
                                    "SK": _suppression_sk(normalized_email),
                                }
                            ),
                        }
                    },
                ]
            )
        elif accepted:
            transaction.append(
                {
                    "Delete": {
                        "TableName": self._table.name,
                        "Key": _serialized_item(
                            {
                                "PK": _project_pk(project_id),
                                "SK": _suppression_sk(normalized_email),
                            }
                        ),
                    }
                }
            )
        elif (
            invitation.get("source")
            == MembershipSource.DOCUMENT_NAME_MATCH.value
        ):
            transaction.append(
                {
                    "Put": {
                        "TableName": self._table.name,
                        "Item": _serialized_item(
                            {
                                "PK": _project_pk(project_id),
                                "SK": _suppression_sk(normalized_email),
                                "entity_type": "COLLABORATOR_SUPPRESSION",
                                "project_id": project_id,
                                "email": normalized_email,
                                "source": invitation["source"],
                                "reason": "INVITATION_DECLINED",
                                "removed_by": normalized_email,
                                "created_at": now,
                                "updated_at": now,
                            }
                        ),
                    }
                }
            )
        self._table.meta.client.transact_write_items(TransactItems=transaction)
        decided = self.get_collaboration_invitation(
            email=normalized_email,
            invitation_id=invitation_id,
        )
        if decided is None:
            raise RuntimeError("Invitation disappeared after being decided")
        return decided

    def create_notification(
        self,
        *,
        email: str,
        kind: NotificationKind,
        title: str,
        message: str,
        project_id: str | None,
        action_url: str | None,
        send_email: bool,
        data: dict[str, Any] | None = None,
        notification_id: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        normalized_email = normalize_email(email)
        notification_id = notification_id or new_id("notice")
        now = utc_now_iso()
        item = {
            "PK": _user_pk(normalized_email),
            "SK": _notification_sk(notification_id),
            "entity_type": "NOTIFICATION",
            "notification_id": notification_id,
            "email": normalized_email,
            "kind": kind.value,
            "title": title.strip(),
            "message": message.strip(),
            "project_id": project_id,
            "action_url": action_url,
            "data": data,
            "delivery_status": (
                NotificationStatus.PENDING.value
                if send_email
                else NotificationStatus.DISABLED.value
            ),
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
            if (
                exc.response.get("Error", {}).get("Code")
                != "ConditionalCheckFailedException"
            ):
                raise
            existing = self.get_notification(
                email=normalized_email,
                notification_id=notification_id,
            )
            if existing is None:
                raise
            return existing, False
        return clean_item, True

    def get_notification(
        self,
        *,
        email: str,
        notification_id: str,
    ) -> dict[str, Any] | None:
        response = self._table.get_item(
            Key={
                "PK": _user_pk(email),
                "SK": _notification_sk(notification_id),
            },
            ConsistentRead=True,
        )
        item = response.get("Item")
        return _plain(item) if item else None

    def list_notifications(
        self,
        *,
        email: str,
        unread_only: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        response = self._table.query(
            KeyConditionExpression=(
                Key("PK").eq(_user_pk(email))
                & Key("SK").begins_with("NOTIFICATION#")
            ),
            Limit=limit,
        )
        notifications = [
            _plain(item)
            for item in response.get("Items", [])
            if item.get("entity_type") == "NOTIFICATION"
        ]
        if unread_only:
            notifications = [
                item for item in notifications if not item.get("read_at")
            ]
        return sorted(
            notifications,
            key=lambda item: str(item.get("created_at", "")),
            reverse=True,
        )

    def mark_notification_read(
        self,
        *,
        email: str,
        notification_id: str,
    ) -> dict[str, Any]:
        try:
            response = self._table.update_item(
                Key={
                    "PK": _user_pk(email),
                    "SK": _notification_sk(notification_id),
                },
                UpdateExpression=(
                    "SET read_at = if_not_exists(read_at, :now), "
                    "updated_at = :now"
                ),
                ConditionExpression="attribute_exists(PK)",
                ExpressionAttributeValues={":now": utc_now_iso()},
                ReturnValues="ALL_NEW",
            )
        except ClientError as exc:
            if (
                exc.response.get("Error", {}).get("Code")
                == "ConditionalCheckFailedException"
            ):
                raise KeyError(
                    f"Notification {notification_id!r} does not exist"
                ) from exc
            raise
        return _plain(response["Attributes"])

    def update_notification_delivery(
        self,
        *,
        email: str,
        notification_id: str,
        status: NotificationStatus,
        message_id: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        assignments = [
            "delivery_status = :status",
            "updated_at = :updated",
        ]
        values: dict[str, Any] = {
            ":status": status.value,
            ":updated": utc_now_iso(),
        }
        removals: list[str] = []
        if message_id is not None:
            assignments.extend(
                [
                    "delivery_message_id = :message_id",
                    "delivery_sent_at = :sent_at",
                ]
            )
            values[":message_id"] = message_id
            values[":sent_at"] = utc_now_iso()
            removals.append("delivery_error")
        if error is not None:
            assignments.append("delivery_error = :error")
            values[":error"] = error[:4000]
        expression = "SET " + ", ".join(assignments)
        if removals:
            expression += " REMOVE " + ", ".join(removals)
        response = self._table.update_item(
            Key={
                "PK": _user_pk(email),
                "SK": _notification_sk(notification_id),
            },
            UpdateExpression=expression,
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )
        return _plain(response["Attributes"])

    def claim_notification_delivery(
        self,
        *,
        email: str,
        notification_id: str,
        attempt_id: str,
    ) -> bool:
        try:
            self._table.update_item(
                Key={
                    "PK": _user_pk(email),
                    "SK": _notification_sk(notification_id),
                },
                UpdateExpression=(
                    "SET delivery_status = :processing, "
                    "delivery_attempt_id = :attempt, updated_at = :updated"
                ),
                ConditionExpression="delivery_status = :pending",
                ExpressionAttributeValues={
                    ":processing": NotificationStatus.PROCESSING.value,
                    ":pending": NotificationStatus.PENDING.value,
                    ":attempt": attempt_id,
                    ":updated": utc_now_iso(),
                },
            )
        except ClientError as exc:
            if (
                exc.response.get("Error", {}).get("Code")
                == "ConditionalCheckFailedException"
            ):
                return False
            raise
        return True

    def reset_notification_delivery(
        self,
        *,
        email: str,
        notification_id: str,
        attempt_id: str,
        error: str,
    ) -> None:
        self._table.update_item(
            Key={
                "PK": _user_pk(email),
                "SK": _notification_sk(notification_id),
            },
            UpdateExpression=(
                "SET delivery_status = :pending, delivery_error = :error, "
                "updated_at = :updated REMOVE delivery_attempt_id"
            ),
            ConditionExpression="delivery_attempt_id = :attempt",
            ExpressionAttributeValues={
                ":pending": NotificationStatus.PENDING.value,
                ":error": error[:4000],
                ":updated": utc_now_iso(),
                ":attempt": attempt_id,
            },
        )

    def put_author_evidence(
        self,
        *,
        project_id: str,
        document_id: str,
        document_name: str,
        candidate: ContributorCandidate,
        page_number: int | None,
        locator: str | None,
        extraction_version: str,
    ) -> tuple[dict[str, Any], bool]:
        surname = candidate_surname(candidate.display_name)
        if surname is None:
            raise ValueError("Contributor candidates require a full name")
        normalized_name = " ".join(
            normalize_name_tokens(candidate.display_name)
        )
        name_tokens = list(normalize_name_tokens(candidate.display_name))
        page_key = str(page_number or 0)
        evidence_id = _stable_identifier(
            "author",
            project_id,
            document_id,
            page_key,
            normalized_name,
        )
        now = utc_now_iso()
        item = {
            "PK": _project_pk(project_id),
            "SK": f"AUTHOR#{evidence_id}",
            "GSI1PK": f"AUTHOR_SURNAME#{surname}",
            "GSI1SK": f"{project_id}#{document_id}#{page_key}#{evidence_id}",
            "entity_type": "AUTHOR_EVIDENCE",
            "evidence_id": evidence_id,
            "project_id": project_id,
            "document_id": document_id,
            "document_name": document_name,
            "display_name": candidate.display_name,
            "normalized_name": normalized_name,
            "name_tokens": name_tokens,
            "surname": surname,
            "relationship": candidate.relationship,
            "confidence": Decimal(str(candidate.confidence)),
            "evidence": candidate.evidence,
            "page_number": page_number,
            "locator": locator,
            "extraction_version": extraction_version,
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
            if (
                exc.response.get("Error", {}).get("Code")
                != "ConditionalCheckFailedException"
            ):
                raise
            return clean_item, False
        return clean_item, True

    def list_author_evidence(
        self,
        project_id: str,
    ) -> list[dict[str, Any]]:
        response = self._table.query(
            KeyConditionExpression=(
                Key("PK").eq(_project_pk(project_id))
                & Key("SK").begins_with("AUTHOR#")
            ),
        )
        return [
            _plain(item)
            for item in response.get("Items", [])
            if item.get("entity_type") == "AUTHOR_EVIDENCE"
        ]

    def list_author_evidence_by_surname(
        self,
        surname: str,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        normalized_tokens = normalize_name_tokens(surname)
        if len(normalized_tokens) != 1 or limit <= 0:
            return []
        token = normalized_tokens[0]
        evidence: list[dict[str, Any]] = []
        exclusive_start_key: dict[str, Any] | None = None
        while len(evidence) < limit:
            kwargs: dict[str, Any] = {
                "FilterExpression": (
                    Attr("entity_type").eq("AUTHOR_EVIDENCE")
                    & Attr("name_tokens").contains(token)
                ),
                "Limit": min(250, limit),
            }
            if exclusive_start_key is not None:
                kwargs["ExclusiveStartKey"] = exclusive_start_key
            response = self._table.scan(**kwargs)
            evidence.extend(_plain(item) for item in response.get("Items", []))
            raw_last_key = response.get("LastEvaluatedKey")
            if not isinstance(raw_last_key, dict) or not raw_last_key:
                break
            exclusive_start_key = raw_last_key
        return evidence[:limit]

    def put_name_match_evaluation(
        self,
        *,
        evidence: dict[str, Any],
        user_profile: dict[str, Any],
        result: NameMatchResult,
        matching_model: str,
        evaluated_by: str,
    ) -> dict[str, Any]:
        project_id = str(evidence["project_id"])
        evidence_id = str(evidence["evidence_id"])
        email = normalize_email(str(user_profile["email"]))
        evaluation_id = _stable_identifier(
            "match",
            project_id,
            evidence_id,
            email,
            matching_model,
        )
        now = utc_now_iso()
        item = {
            "PK": _project_pk(project_id),
            "SK": f"MATCH#{evaluation_id}",
            "GSI1PK": f"USER#{email}",
            "GSI1SK": (f"MATCH#{project_id}#{evidence_id}#{evaluation_id}"),
            "entity_type": "NAME_MATCH_EVALUATION",
            "evaluation_id": evaluation_id,
            "project_id": project_id,
            "evidence_id": evidence_id,
            "document_id": evidence["document_id"],
            "document_name": evidence["document_name"],
            "candidate_name": evidence["display_name"],
            "user_email": email,
            "user_subject": user_profile.get("subject"),
            "user_display_name": user_profile.get("display_name"),
            "decision": result.decision.value,
            "confidence": Decimal(str(result.confidence)),
            "rationale": result.rationale,
            "matching_model": matching_model,
            "evaluated_by": evaluated_by,
            "extraction_version": evidence["extraction_version"],
            "created_at": now,
            "updated_at": now,
        }
        clean_item = {
            key: value for key, value in item.items() if value is not None
        }
        self._table.put_item(Item=clean_item)
        return clean_item

    def record_document_discovery(
        self,
        *,
        project_id: str,
        document_id: str,
        blend360_emails: list[str],
        extraction_version: str,
    ) -> None:
        normalized = {normalize_blend_email(email) for email in blend360_emails}
        assignments = [
            "contributor_extraction_version = :version",
            "contributor_extracted_at = :now",
            "updated_at = :now",
        ]
        values: dict[str, Any] = {
            ":version": extraction_version,
            ":now": utc_now_iso(),
        }
        expression = "SET " + ", ".join(assignments)
        if normalized:
            expression += " ADD discovered_blend360_emails :emails"
            values[":emails"] = normalized
        self._table.update_item(
            Key={
                "PK": _project_pk(project_id),
                "SK": f"DOCUMENT#{document_id}",
            },
            UpdateExpression=expression,
            ExpressionAttributeValues=values,
        )

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
        source_answer_id: str | None = None,
        source_attachment_id: str | None = None,
        source_question_id: str | None = None,
        return_existing: bool = False,
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
            "source_answer_id": source_answer_id,
            "source_attachment_id": source_attachment_id,
            "source_question_id": source_question_id,
            "uploaded_by": uploaded_by,
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
            if (
                not return_existing
                or exc.response.get("Error", {}).get("Code")
                != "ConditionalCheckFailedException"
            ):
                raise
            existing = self.get_document(
                project_id=project_id,
                document_id=document_id,
            )
            if existing is None:
                raise
            return existing
        return clean_item

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
        email = gap.assigned_expert_email
        reply_token = (
            secrets.token_hex(24)
            if reply_domain and email is not None
            else None
        )
        reply_address = (
            f"kg-{reply_token}@{reply_domain.strip().casefold().rstrip('.')}"
            if reply_token and reply_domain
            else None
        )
        item = {
            "PK": _project_pk(project_id),
            "SK": _question_sk(question_id),
            "GSI1PK": f"EXPERT#{email}" if email is not None else None,
            "GSI1SK": (
                f"{status}#{now}#{project_id}#{question_id}"
                if email is not None
                else None
            ),
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

    def claim_question_email_resend(
        self,
        *,
        project_id: str,
        question_id: str,
        request_id: str,
    ) -> bool:
        """Claim one logical resend while permitting retries after failure."""
        try:
            self._table.update_item(
                Key={
                    "PK": _project_pk(project_id),
                    "SK": _question_sk(question_id),
                },
                UpdateExpression=(
                    "SET last_resend_request_id = :request, "
                    "last_resend_claimed_at = :now, updated_at = :now"
                ),
                ConditionExpression=(
                    "attribute_exists(PK) AND ("
                    "attribute_not_exists(last_resend_request_id) OR "
                    "last_resend_request_id <> :request OR "
                    "notification_status = :failed)"
                ),
                ExpressionAttributeValues={
                    ":request": request_id,
                    ":failed": NotificationStatus.FAILED.value,
                    ":now": utc_now_iso(),
                },
            )
        except ClientError as exc:
            if (
                exc.response.get("Error", {}).get("Code")
                == "ConditionalCheckFailedException"
            ):
                return False
            raise
        return True

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

    def get_question_answer(
        self,
        *,
        project_id: str,
        question_id: str,
        answer_id: str,
    ) -> dict[str, Any] | None:
        response = self._table.get_item(
            Key={
                "PK": _project_pk(project_id),
                "SK": _answer_sk(question_id, answer_id),
            },
            ConsistentRead=True,
        )
        item = response.get("Item")
        if item is None or item.get("entity_type") != "ANSWER":
            return None
        return _plain(item)

    def submit_answer(
        self,
        *,
        project_id: str,
        question_id: str,
        answer: str,
        answered_by: str,
        requires_human_review: bool | None = None,
        source: str = "AUTHENTICATED_API",
        answer_id: str | None = None,
        supporting_document_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        question = self.get_question(
            project_id=project_id,
            question_id=question_id,
        )
        if question is None:
            raise KeyError(f"Question {question_id!r} does not exist")
        if requires_human_review is None:
            requires_human_review = not self.is_project_member(
                project_id=project_id,
                email=answered_by,
            )
        return self._put_answer(
            question=question,
            answer_id=answer_id or new_id("ans"),
            answer=answer,
            answered_by=answered_by,
            source=source,
            supporting_document_ids=supporting_document_ids,
            return_existing=answer_id is not None,
            requires_human_review=requires_human_review,
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
        attachments: list[dict[str, Any]] | None = None,
        attachment_errors: list[str] | None = None,
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
            attachments=attachments,
            attachment_errors=attachment_errors,
            return_existing=True,
            requires_human_review=not self.is_project_member(
                project_id=str(question["project_id"]),
                email=answered_by,
            ),
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
        attachments: list[dict[str, Any]] | None = None,
        attachment_errors: list[str] | None = None,
        supporting_document_ids: list[str] | None = None,
        return_existing: bool = False,
        requires_human_review: bool = False,
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
        normalized_answer = answer.strip()
        normalized_support = list(dict.fromkeys(supporting_document_ids or []))
        normalized_attachments = attachments or []
        if (
            len(normalized_answer) < 3
            and not normalized_support
            and not normalized_attachments
        ):
            raise ValueError(
                "An answer must include text or at least one supporting document"
            )

        now = utc_now_iso()
        waits_for_documents = bool(normalized_attachments) and not (
            requires_human_review
        )
        item = {
            "PK": _project_pk(project_id),
            "SK": _answer_sk(question_id, answer_id),
            "entity_type": "ANSWER",
            "project_id": project_id,
            "project_name": question["project_name"],
            "question_id": question_id,
            "question": question["question"],
            "context": question.get("context"),
            "assigned_expert_email": question.get("assigned_expert_email"),
            "reply_address": question.get("reply_address"),
            "answer_id": answer_id,
            "answer": normalized_answer,
            "answered_by": answered_by.strip().casefold(),
            "answer_source": source,
            "source_message_id": source_message_id,
            "raw_email_bucket": raw_email_bucket,
            "raw_email_key": raw_email_key,
            "email_subject": (email_subject or "").strip() or None,
            "attachments": normalized_attachments or None,
            "attachment_errors": attachment_errors or None,
            "supporting_document_ids": normalized_support or None,
            "review_status": (
                AnswerStatus.PENDING_HUMAN.value
                if requires_human_review
                else (
                    AnswerStatus.WAITING_DOCUMENTS.value
                    if waits_for_documents
                    else AnswerStatus.PENDING.value
                )
            ),
            "requires_human_review": requires_human_review,
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

    def decide_answer_human_review(
        self,
        *,
        project_id: str,
        question_id: str,
        answer_id: str,
        approved: bool,
        reviewed_by: str,
        note: str | None,
    ) -> dict[str, Any]:
        existing_response = self._table.get_item(
            Key={
                "PK": _project_pk(project_id),
                "SK": _answer_sk(question_id, answer_id),
            },
            ConsistentRead=True,
        )
        existing_item = existing_response.get("Item")
        if existing_item is None:
            raise KeyError(f"Answer {answer_id!r} does not exist")
        waits_for_documents = bool(existing_item.get("attachments"))
        target_status = (
            (
                AnswerStatus.WAITING_DOCUMENTS
                if waits_for_documents
                else AnswerStatus.PENDING
            )
            if approved
            else AnswerStatus.REJECTED
        )
        now = utc_now_iso()
        values: dict[str, Any] = {
            ":pending_human": AnswerStatus.PENDING_HUMAN.value,
            ":target": target_status.value,
            ":reviewed_by": reviewed_by.strip().casefold(),
            ":reviewed_at": now,
            ":updated": now,
        }
        assignments = [
            "review_status = :target",
            "human_reviewed_by = :reviewed_by",
            "human_reviewed_at = :reviewed_at",
            "updated_at = :updated",
        ]
        if note:
            assignments.append("human_review_note = :note")
            values[":note"] = note.strip()
        try:
            response = self._table.update_item(
                Key={
                    "PK": _project_pk(project_id),
                    "SK": _answer_sk(question_id, answer_id),
                },
                UpdateExpression="SET " + ", ".join(assignments),
                ConditionExpression="review_status = :pending_human",
                ExpressionAttributeValues=values,
                ReturnValues="ALL_NEW",
            )
        except ClientError as exc:
            if (
                exc.response.get("Error", {}).get("Code")
                == "ConditionalCheckFailedException"
            ):
                existing_response = self._table.get_item(
                    Key={
                        "PK": _project_pk(project_id),
                        "SK": _answer_sk(question_id, answer_id),
                    },
                    ConsistentRead=True,
                )
                existing = existing_response.get("Item")
                if (
                    existing is not None
                    and existing.get("review_status") == target_status.value
                ):
                    return _plain(existing)
                raise ValueError(
                    "This answer is no longer awaiting human review"
                ) from exc
            raise
        return _plain(response["Attributes"])

    def update_answer_attachments(
        self,
        *,
        project_id: str,
        question_id: str,
        answer_id: str,
        attachments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        response = self._table.update_item(
            Key={
                "PK": _project_pk(project_id),
                "SK": _answer_sk(question_id, answer_id),
            },
            UpdateExpression=(
                "SET attachments = :attachments, updated_at = :updated"
            ),
            ExpressionAttributeValues={
                ":attachments": attachments,
                ":updated": utc_now_iso(),
            },
            ReturnValues="ALL_NEW",
        )
        return _plain(response["Attributes"])

    def release_answer_after_documents(
        self,
        *,
        project_id: str,
        question_id: str,
        answer_id: str,
        attachment_warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        values: dict[str, Any] = {
            ":waiting": AnswerStatus.WAITING_DOCUMENTS.value,
            ":pending": AnswerStatus.PENDING.value,
            ":updated": utc_now_iso(),
        }
        assignments = [
            "review_status = :pending",
            "updated_at = :updated",
        ]
        if attachment_warnings:
            assignments.append("attachment_warnings = :warnings")
            values[":warnings"] = attachment_warnings
        try:
            response = self._table.update_item(
                Key={
                    "PK": _project_pk(project_id),
                    "SK": _answer_sk(question_id, answer_id),
                },
                UpdateExpression="SET " + ", ".join(assignments),
                ConditionExpression="review_status = :waiting",
                ExpressionAttributeValues=values,
                ReturnValues="ALL_NEW",
            )
        except ClientError as exc:
            if (
                exc.response.get("Error", {}).get("Code")
                != "ConditionalCheckFailedException"
            ):
                raise
            current = self._table.get_item(
                Key={
                    "PK": _project_pk(project_id),
                    "SK": _answer_sk(question_id, answer_id),
                },
                ConsistentRead=True,
            ).get("Item")
            if current is None:
                raise KeyError(f"Answer {answer_id!r} does not exist") from exc
            return _plain(current)
        return _plain(response["Attributes"])

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
