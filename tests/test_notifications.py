from __future__ import annotations

import json
from typing import Any

from knowledge_core.models import NotificationKind, NotificationStatus
from knowledge_core.notifications import NotificationPublisher


class FakeRepository:
    def __init__(self, *, delivery_status: NotificationStatus) -> None:
        self.delivery_status = delivery_status
        self.calls: list[dict[str, Any]] = []

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
        call = {
            "email": email,
            "kind": kind,
            "title": title,
            "message": message,
            "project_id": project_id,
            "action_url": action_url,
            "send_email": send_email,
            "data": data,
            "notification_id": notification_id,
        }
        self.calls.append(call)
        return (
            {
                **call,
                "kind": kind.value,
                "notification_id": notification_id or "notice_1",
                "delivery_status": self.delivery_status.value,
            },
            True,
        )


class FakeSqs:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def send_message(self, **kwargs: str) -> None:
        self.calls.append(kwargs)


def test_pending_email_notification_is_queued_after_inbox_write() -> None:
    repository = FakeRepository(delivery_status=NotificationStatus.PENDING)
    sqs = FakeSqs()
    publisher = NotificationPublisher(
        repository=repository,  # pyright: ignore[reportArgumentType]
        queue_url="https://sqs.example/notifications",
        sqs_client=sqs,
    )

    notification = publisher.publish(
        email="person@blend360.com",
        kind=NotificationKind.COLLABORATOR_ADDED,
        title="Added to Project One",
        message="You were added.",
        project_id="prj_1",
        action_url="https://knowledge.example.com/",
        send_email=True,
        notification_id="stable-notice",
    )

    assert notification["notification_id"] == "stable-notice"
    assert len(repository.calls) == 1
    assert len(sqs.calls) == 1
    assert json.loads(sqs.calls[0]["MessageBody"]) == {
        "email": "person@blend360.com",
        "notification_id": "stable-notice",
    }


def test_inbox_only_notification_does_not_enqueue_email() -> None:
    repository = FakeRepository(delivery_status=NotificationStatus.DISABLED)
    sqs = FakeSqs()
    publisher = NotificationPublisher(
        repository=repository,  # pyright: ignore[reportArgumentType]
        queue_url="https://sqs.example/notifications",
        sqs_client=sqs,
    )

    publisher.publish(
        email="person@blend360.com",
        kind=NotificationKind.QUESTION_CREATED,
        title="New question",
        message="A question was created.",
        project_id="prj_1",
        action_url=None,
        send_email=False,
    )

    assert sqs.calls == []
