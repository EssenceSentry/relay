from __future__ import annotations

import hashlib
import logging
from typing import Any

import boto3

from knowledge_core.answer_history import format_answer_history
from knowledge_core.answer_review_material import build_answer_review_material
from knowledge_core.dynamo import (
    KnowledgeRepository,
    deserialize_stream_image,
)
from knowledge_core.email_service import SesEmailService
from knowledge_core.indexed_documents import build_indexed_document
from knowledge_core.indexing import DocumentIndexer
from knowledge_core.models import (
    AnswerReview,
    AnswerStatus,
    NotificationStatus,
    VerifiedFactCreate,
)
from knowledge_core.openai_api import OpenAIService
from knowledge_core.opensearch import OpenSearchServerlessClient
from knowledge_core.secrets import SecretProvider
from knowledge_core.settings import ReviewSettings

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

_SETTINGS = ReviewSettings.from_env()
_S3 = boto3.client("s3")
_REPOSITORY = KnowledgeRepository(
    _SETTINGS.table_name,
    region_name=_SETTINGS.aws_region,
)
_SECRETS = SecretProvider(region_name=_SETTINGS.aws_region)
_SEARCH = OpenSearchServerlessClient(
    endpoint=_SETTINGS.opensearch_endpoint,
    region=_SETTINGS.aws_region,
    index_name=_SETTINGS.opensearch_index,
    dimensions=_SETTINGS.embedding_dimensions,
)


def _email_sender() -> SesEmailService | None:
    if not _SETTINGS.email_enabled:
        return None
    assert _SETTINGS.ses_from_address is not None
    assert _SETTINGS.application_base_url is not None
    return SesEmailService(
        region_name=_SETTINGS.aws_region,
        from_address=_SETTINGS.ses_from_address,
        application_base_url=_SETTINGS.application_base_url,
    )


def _openai() -> OpenAIService:
    return OpenAIService(
        api_key=_SECRETS.get(
            _SETTINGS.openai_secret_arn,
            "api_key",
            use_cache=False,
        ),
        embedding_model=_SETTINGS.embedding_model,
        embedding_dimensions=_SETTINGS.embedding_dimensions,
        review_model=_SETTINGS.review_model,
    )


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    for record in event.get("Records", []):
        event_id = record.get("eventID", "unknown")
        sequence_number = (
            record.get("dynamodb", {}).get("SequenceNumber") or event_id
        )
        try:
            _process_record(record, attempt_id=event_id)
        except Exception:
            LOGGER.exception("Failed to review answer from event %s", event_id)
            failures.append({"itemIdentifier": sequence_number})
    return {"batchItemFailures": failures}


def _process_record(record: dict[str, Any], *, attempt_id: str) -> None:
    new_image = record.get("dynamodb", {}).get("NewImage")
    if not new_image:
        return
    item = deserialize_stream_image(new_image)
    if item.get("entity_type") != "ANSWER":
        return
    if item.get("review_status") != AnswerStatus.PENDING.value:
        return

    project_id = item["project_id"]
    question_id = item["question_id"]
    answer_id = item["answer_id"]
    claimed = _REPOSITORY.claim_answer_for_review(
        project_id=project_id,
        question_id=question_id,
        answer_id=answer_id,
        attempt_id=attempt_id,
    )
    if not claimed:
        return

    try:
        service = _openai()
        answers = _REPOSITORY.list_question_answers(
            project_id=project_id,
            question_id=question_id,
        )
        answer_history = format_answer_history(
            answers,
            current_answer_id=answer_id,
        )
        review_material, has_usable_material = build_answer_review_material(
            answer_history=answer_history,
            answers=answers,
            repository=_REPOSITORY,
            search=_SEARCH,
        )
        if has_usable_material:
            review = service.review_expert_answer(
                project_name=item["project_name"],
                question=item["question"],
                answer=review_material,
                context=item.get("context"),
            )
        else:
            review = AnswerReview(
                sufficient=False,
                confidence=1.0,
                rationale=(
                    "The reply contained no usable text and none of its "
                    "supporting documents could be extracted."
                ),
                missing_details=[
                    "Reply with the missing detail or attach a supported, "
                    "readable project document."
                ],
            )

        generated_document_id: str | None = None
        if review.sufficient:
            generated_document_id = _publish_knowledge_note(
                item=item,
                title=review.title or "Verified expert answer",
                markdown=review.document_markdown or "",
                normalized_answer=review.normalized_answer or item["answer"],
                openai=service,
            )

        _REPOSITORY.update_question_after_review(
            project_id=project_id,
            question_id=question_id,
            accepted=review.sufficient,
            answer_id=answer_id,
            generated_document_id=generated_document_id,
            review_rationale=review.rationale,
        )
        _REPOSITORY.complete_answer_review(
            project_id=project_id,
            question_id=question_id,
            answer_id=answer_id,
            attempt_id=attempt_id,
            accepted=review.sufficient,
            confidence=review.confidence,
            rationale=review.rationale,
            missing_details=review.missing_details,
            generated_document_id=generated_document_id,
        )
        if not review.sufficient:
            _send_follow_up_best_effort(
                item=item,
                missing_details=review.missing_details,
                review_rationale=review.rationale,
            )
    except Exception as exc:
        try:
            _REPOSITORY.reset_answer_for_retry(
                project_id=project_id,
                question_id=question_id,
                answer_id=answer_id,
                attempt_id=attempt_id,
                error=f"{type(exc).__name__}: {exc}",
            )
        except Exception:
            LOGGER.exception("Could not reset answer %s for retry", answer_id)
        raise


def _send_follow_up_best_effort(
    *,
    item: dict[str, Any],
    missing_details: list[str],
    review_rationale: str,
) -> None:
    project_id = item["project_id"]
    question_id = item["question_id"]
    answer_id = item["answer_id"]
    try:
        sender = _email_sender()
        if sender is None or not item.get("reply_address"):
            return
        result = sender.send_follow_up(
            item,
            missing_details=missing_details,
            review_rationale=review_rationale,
        )
        _REPOSITORY.update_answer_follow_up_notification(
            project_id=project_id,
            question_id=question_id,
            answer_id=answer_id,
            status=NotificationStatus.SENT,
            message_id=result.message_id,
        )
    except Exception as exc:
        LOGGER.exception("Could not send follow-up for answer %s", answer_id)
        try:
            _REPOSITORY.update_answer_follow_up_notification(
                project_id=project_id,
                question_id=question_id,
                answer_id=answer_id,
                status=NotificationStatus.FAILED,
                error=f"{type(exc).__name__}: {exc}",
            )
        except Exception:
            LOGGER.exception(
                "Could not record follow-up delivery failure for %s",
                answer_id,
            )


def _publish_knowledge_note(
    *,
    item: dict[str, Any],
    title: str,
    markdown: str,
    normalized_answer: str,
    openai: OpenAIService,
) -> str:
    project_id = item["project_id"]
    question_id = item["question_id"]
    answer_id = item["answer_id"]
    suffix = hashlib.sha256(answer_id.encode("utf-8")).hexdigest()[:20]
    document_id = f"doc_qa_{suffix}"
    key = f"generated/{project_id}/{question_id}/{answer_id}.md"
    body = markdown.strip().encode("utf-8")

    _S3.put_object(
        Bucket=_SETTINGS.document_bucket,
        Key=key,
        Body=body,
        ContentType="text/markdown; charset=utf-8",
        ServerSideEncryption="AES256",
        Metadata={
            "project-id": project_id,
            "question-id": question_id,
            "answer-id": answer_id,
        },
    )

    indexed_document = build_indexed_document(
        text=markdown,
        project_id=project_id,
        document_id=document_id,
        document_version="1",
        document_name=f"{title}.md",
        s3_bucket=_SETTINGS.document_bucket,
        s3_key=key,
        source_type="EXPERT_QA",
    )
    _SEARCH.ensure_index()
    _SEARCH.delete_document(
        project_id=project_id,
        document_id=document_id,
    )
    DocumentIndexer(openai=openai, search=_SEARCH).index_document(
        indexed_document
    )

    _REPOSITORY.put_generated_document(
        project_id=project_id,
        document_id=document_id,
        document_name=f"{title}.md",
        s3_bucket=_SETTINGS.document_bucket,
        s3_key=key,
        created_by=item["answered_by"],
        size_bytes=len(body),
    )
    _REPOSITORY.put_verified_fact(
        project_id=project_id,
        fact=VerifiedFactCreate(
            name=item["question"],
            value=normalized_answer,
            provenance=(
                "Answer supplied by assigned expert "
                f"{item['answered_by']} and reviewed by the server-side LLM."
            ),
        ),
        created_by="answer-review-lambda",
        source_document_id=document_id,
        fact_id=f"qa_{question_id}",
    )
    return document_id
