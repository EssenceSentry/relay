from __future__ import annotations

import json
import logging
from typing import Any

from knowledge_core.dynamo import KnowledgeRepository
from knowledge_core.email_service import SesEmailService
from knowledge_core.models import NotificationStatus
from knowledge_core.settings import NotificationSettings

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

_SETTINGS = NotificationSettings.from_env()
_REPOSITORY = KnowledgeRepository(
    _SETTINGS.table_name,
    region_name=_SETTINGS.aws_region,
)


def _sender() -> SesEmailService | None:
    if not _SETTINGS.email_enabled:
        return None
    assert _SETTINGS.ses_from_address is not None
    assert _SETTINGS.application_base_url is not None
    return SesEmailService(
        region_name=_SETTINGS.aws_region,
        from_address=_SETTINGS.ses_from_address,
        application_base_url=_SETTINGS.application_base_url,
    )


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    del context
    failures: list[dict[str, str]] = []
    for record in event.get("Records", []):
        message_id = str(record.get("messageId") or "unknown")
        try:
            _process(record, attempt_id=message_id)
        except Exception:
            LOGGER.exception("Notification delivery failed for %s", message_id)
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}


def _process(record: dict[str, Any], *, attempt_id: str) -> None:
    body = json.loads(record["body"])
    email = str(body["email"])
    notification_id = str(body["notification_id"])
    notification = _REPOSITORY.get_notification(
        email=email,
        notification_id=notification_id,
    )
    if notification is None:
        LOGGER.warning("Notification %s no longer exists", notification_id)
        return
    if notification.get("delivery_status") == NotificationStatus.SENT.value:
        return
    if not _REPOSITORY.claim_notification_delivery(
        email=email,
        notification_id=notification_id,
        attempt_id=attempt_id,
    ):
        return
    try:
        sender = _sender()
        if sender is None:
            _REPOSITORY.update_notification_delivery(
                email=email,
                notification_id=notification_id,
                status=NotificationStatus.DISABLED,
            )
            return
        result = sender.send_notification(notification)
        _REPOSITORY.update_notification_delivery(
            email=email,
            notification_id=notification_id,
            status=NotificationStatus.SENT,
            message_id=result.message_id,
        )
    except Exception as exc:
        _REPOSITORY.reset_notification_delivery(
            email=email,
            notification_id=notification_id,
            attempt_id=attempt_id,
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
