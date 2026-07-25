from __future__ import annotations

import logging

import boto3
from aws_lambda_typing.context import Context
from aws_lambda_typing.events import SESEvent
from aws_lambda_typing.events.ses import (
    SESEventRecord,
    SESReceiptStatus,
)

from knowledge_core.dynamo import KnowledgeRepository
from knowledge_core.email_parsing import (
    extract_reply_token,
    parse_inbound_email,
)
from knowledge_core.settings import InboundEmailSettings

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

_SETTINGS = InboundEmailSettings.from_env()
_S3 = boto3.client("s3", region_name=_SETTINGS.aws_region)
_REPOSITORY = KnowledgeRepository(
    _SETTINGS.table_name,
    region_name=_SETTINGS.aws_region,
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
    parsed = parse_inbound_email(
        raw_message,
        max_answer_chars=_SETTINGS.max_answer_chars,
    )
    expected_sender = str(question["assigned_expert_email"]).casefold()
    if parsed.sender.casefold() != expected_sender:
        raise PermanentInboundEmailError(
            f"Sender {parsed.sender!r} is not the assigned expert"
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
        )
    except (KeyError, ValueError) as exc:
        raise PermanentInboundEmailError(str(exc)) from exc

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
