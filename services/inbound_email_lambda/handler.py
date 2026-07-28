from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Any

import boto3

from knowledge_core.answer_attachments import AnswerAttachmentPromoter
from knowledge_core.dynamo import KnowledgeRepository
from knowledge_core.email_parsing import (
    ParsedInboundAttachment,
    extract_reply_token,
    parse_inbound_email,
)
from knowledge_core.ids import safe_filename
from knowledge_core.models import NotificationKind
from knowledge_core.notifications import NotificationPublisher
from knowledge_core.settings import InboundEmailSettings

if TYPE_CHECKING:
    from aws_lambda_typing.context import Context
    from aws_lambda_typing.events import SESEvent
    from aws_lambda_typing.events.ses import (
        SESEventRecord,
        SESReceiptStatus,
    )

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

_SETTINGS = InboundEmailSettings.from_env()
_S3 = boto3.client("s3", region_name=_SETTINGS.aws_region)
_REPOSITORY = KnowledgeRepository(
    _SETTINGS.table_name,
    region_name=_SETTINGS.aws_region,
)
_NOTIFICATIONS = NotificationPublisher(
    repository=_REPOSITORY,
    queue_url=_SETTINGS.notification_queue_url,
    sqs_client=boto3.client("sqs", region_name=_SETTINGS.aws_region),
)


class PermanentInboundEmailError(ValueError):
    """An invalid or unauthorized message that should not be retried."""


def lambda_handler(
    event: SESEvent,
    context: Context,
) -> dict[str, int]:
    del context
    processed = 0
    ignored = 0
    for record in event.get("Records", []):
        try:
            _process_record(record)
        except PermanentInboundEmailError as exc:
            ignored += 1
            LOGGER.warning("Ignoring inbound email: %s", exc)
        else:
            processed += 1
    return {"processed": processed, "ignored": ignored}


def _process_record(record: SESEventRecord) -> None:
    if record.get("eventSource") != "aws:ses":
        raise PermanentInboundEmailError(
            "Event did not originate from Amazon SES"
        )
    ses = record["ses"]
    mail = ses["mail"]
    receipt = ses["receipt"]
    message_id = str(mail.get("messageId") or "").strip()
    if not message_id:
        raise PermanentInboundEmailError("SES event has no message ID")

    _require_safe_verdict(receipt.get("spamVerdict"), "spamVerdict")
    _require_safe_verdict(receipt.get("virusVerdict"), "virusVerdict")

    recipients = [
        *[str(value) for value in receipt.get("recipients", [])],
        *[str(value) for value in mail.get("destination", [])],
    ]
    reply_token = extract_reply_token(recipients, _SETTINGS.reply_domain)
    if reply_token is None:
        raise PermanentInboundEmailError(
            "No knowledge-gap reply token was present in the recipients"
        )

    question = _REPOSITORY.get_question_by_reply_token(reply_token)
    if question is None:
        raise PermanentInboundEmailError("The reply token is unknown")

    raw_key = f"{_SETTINGS.inbound_prefix}{message_id}"
    response = _S3.get_object(
        Bucket=_SETTINGS.inbound_bucket,
        Key=raw_key,
    )
    raw_message = response["Body"].read()
    try:
        parsed = parse_inbound_email(
            raw_message,
            max_answer_chars=_SETTINGS.max_answer_chars,
            max_attachment_count=_SETTINGS.max_attachment_count,
            max_total_attachment_bytes=_SETTINGS.max_attachment_bytes,
        )
    except ValueError as exc:
        raise PermanentInboundEmailError(str(exc)) from exc
    expected_sender = str(question["assigned_expert_email"]).casefold()
    if parsed.sender.casefold() != expected_sender:
        raise PermanentInboundEmailError(
            f"Sender {parsed.sender!r} is not the assigned expert"
        )

    attachments = _quarantine_attachments(
        message_id=message_id,
        attachments=parsed.attachments,
    )
    try:
        answer = _REPOSITORY.submit_email_answer(
            reply_token=reply_token,
            answer=parsed.reply_text,
            answered_by=parsed.sender,
            ses_message_id=message_id,
            raw_email_bucket=_SETTINGS.inbound_bucket,
            raw_email_key=raw_key,
            email_subject=parsed.subject,
            attachments=attachments,
            attachment_errors=list(parsed.attachment_errors),
        )
    except (KeyError, ValueError) as exc:
        raise PermanentInboundEmailError(str(exc)) from exc
    if answer.get("requires_human_review"):
        project = _REPOSITORY.require_project(str(answer["project_id"]))
        for member in _REPOSITORY.list_project_members(
            str(answer["project_id"])
        ):
            member_email = str(member["email"])
            _NOTIFICATIONS.publish(
                email=member_email,
                kind=NotificationKind.ANSWER_REVIEW_REQUIRED,
                title=f"Answer review needed for {project['name']}",
                message=(
                    f"{parsed.sender} replied by email with an answer that "
                    "needs project-member approval before LLM review."
                ),
                project_id=str(answer["project_id"]),
                action_url=_SETTINGS.application_base_url,
                send_email=True,
                data={
                    "project_name": project["name"],
                    "question_id": answer["question_id"],
                    "answer_id": answer["answer_id"],
                },
                notification_id=(
                    f"answer-review-{answer['answer_id']}-"
                    f"{member_email.replace('@', '-')}"
                ),
            )
    elif attachments:
        answer = AnswerAttachmentPromoter(
            repository=_REPOSITORY,
            s3=_S3,
            document_bucket=_SETTINGS.document_bucket,
        ).promote(answer)

    if parsed.attachment_errors:
        _NOTIFICATIONS.publish(
            email=parsed.sender,
            kind=NotificationKind.ANSWER_ATTACHMENT_REJECTED,
            title="Some answer attachments were not accepted",
            message=" ".join(parsed.attachment_errors),
            project_id=str(answer["project_id"]),
            action_url=_SETTINGS.application_base_url,
            send_email=True,
            data={
                "question_id": answer["question_id"],
                "answer_id": answer["answer_id"],
                "attachment_errors": list(parsed.attachment_errors),
            },
            notification_id=f"attachment-errors-{answer['answer_id']}",
        )

    LOGGER.info(
        "Accepted email answer %s for project=%s question=%s",
        answer["answer_id"],
        answer["project_id"],
        answer["question_id"],
    )


def _require_safe_verdict(
    verdict_record: SESReceiptStatus | None,
    field: str,
) -> None:
    verdict = str((verdict_record or {}).get("status") or "").upper()
    if verdict == "FAIL":
        raise PermanentInboundEmailError(f"SES {field} was FAIL")


def _quarantine_attachments(
    *,
    message_id: str,
    attachments: tuple[ParsedInboundAttachment, ...],
) -> list[dict[str, Any]]:
    stored: list[dict[str, Any]] = []
    for index, attachment in enumerate(attachments, start=1):
        digest = hashlib.sha256(
            (f"{message_id}\0{index}\0{attachment.sha256}").encode()
        ).hexdigest()
        attachment_id = f"att_{digest[:32]}"
        document_id = f"doc_email_{digest[:32]}"
        filename = safe_filename(attachment.filename)
        key = f"answer-attachments/{message_id}/{attachment_id}/{filename}"
        _S3.put_object(
            Bucket=_SETTINGS.inbound_bucket,
            Key=key,
            Body=attachment.body,
            ContentType=attachment.content_type,
            ServerSideEncryption="AES256",
            Metadata={
                "message-id": message_id,
                "attachment-id": attachment_id,
                "sha256": attachment.sha256,
            },
        )
        stored.append(
            {
                "attachment_id": attachment_id,
                "document_id": document_id,
                "filename": attachment.filename,
                "content_type": attachment.content_type,
                "size_bytes": attachment.size_bytes,
                "sha256": attachment.sha256,
                "status": "QUARANTINED",
                "quarantine_bucket": _SETTINGS.inbound_bucket,
                "quarantine_key": key,
            }
        )
    return stored
