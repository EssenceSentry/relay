from __future__ import annotations

import json
from typing import Any

from knowledge_core.dynamo import KnowledgeRepository
from knowledge_core.models import NotificationKind, NotificationStatus


class NotificationPublisher:
    def __init__(
        self,
        *,
        repository: KnowledgeRepository,
        queue_url: str,
        sqs_client: Any,
    ) -> None:
        self._repository = repository
        self._queue_url = queue_url
        self._sqs = sqs_client

    def publish(
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
    ) -> dict[str, Any]:
        notification, _created = self._repository.create_notification(
            email=email,
            kind=kind,
            title=title,
            message=message,
            project_id=project_id,
            action_url=action_url,
            send_email=send_email,
            data=data,
            notification_id=notification_id,
        )
        if (
            send_email
            and notification.get("delivery_status")
            == NotificationStatus.PENDING.value
        ):
            self._sqs.send_message(
                QueueUrl=self._queue_url,
                MessageBody=json.dumps(
                    {
                        "email": notification["email"],
                        "notification_id": notification["notification_id"],
                    },
                    separators=(",", ":"),
                ),
            )
        return notification


class MatchingPublisher:
    def __init__(self, *, queue_url: str, sqs_client: Any) -> None:
        self._queue_url = queue_url
        self._sqs = sqs_client

    def candidate_created(self, evidence: dict[str, Any]) -> None:
        self._send({"kind": "candidate_created", "evidence": evidence})

    def user_verified(self, email: str) -> None:
        self._send({"kind": "user_verified", "email": email})

    def _send(self, message: dict[str, Any]) -> None:
        self._sqs.send_message(
            QueueUrl=self._queue_url,
            MessageBody=json.dumps(message, separators=(",", ":")),
        )
