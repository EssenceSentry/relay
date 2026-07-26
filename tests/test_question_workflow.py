from __future__ import annotations

from typing import Any

from knowledge_core.email_service import EmailSendResult
from knowledge_core.models import KnowledgeGapCreate, NotificationStatus
from knowledge_core.question_workflow import QuestionWorkflow


class FakeRepository:
    def __init__(self) -> None:
        self.create_kwargs: dict[str, Any] | None = None
        self.updates: list[dict[str, Any]] = []
        self.question = {
            "project_id": "prj_1",
            "project_name": "Project one",
            "question_id": "gap_1",
            "question": "Who owned the rollout?",
            "assigned_expert_email": "expert@blend360.com",
            "reply_address": "kg-validtokenvalue12345@example.com",
        }

    def create_question(self, **kwargs: Any) -> dict[str, Any]:
        self.create_kwargs = kwargs
        return dict(self.question)

    def get_question(self, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        return dict(self.question)

    def update_question_notification(self, **kwargs: Any) -> dict[str, Any]:
        self.updates.append(kwargs)
        return {**self.question, "notification_status": kwargs["status"].value}


class SuccessfulSender:
    def send_question(self, question: dict[str, Any]) -> EmailSendResult:
        del question
        return EmailSendResult(message_id="ses-message-1")


class FailingSender:
    def send_question(self, question: dict[str, Any]) -> EmailSendResult:
        del question
        raise RuntimeError("recipient is not verified")


class ExplodingSender:
    def send_question(self, question: dict[str, Any]) -> EmailSendResult:
        del question
        raise AssertionError(
            "An untargeted question must not send direct email"
        )


def _gap() -> KnowledgeGapCreate:
    return KnowledgeGapCreate(
        question="Who owned the rollout?",
        assigned_expert_email="expert@blend360.com",
    )


def test_create_question_sends_notification_and_records_message_id() -> None:
    repository = FakeRepository()
    workflow = QuestionWorkflow(
        repository=repository,  # type: ignore[arg-type]
        email_sender=SuccessfulSender(),  # type: ignore[arg-type]
        reply_domain="example.com",
    )

    result = workflow.create_question(
        project_id="prj_1",
        gap=_gap(),
        created_by="mcp-agent",
    )

    assert repository.create_kwargs is not None
    assert repository.create_kwargs["reply_domain"] == "example.com"
    assert (
        repository.create_kwargs["notification_status"]
        == NotificationStatus.PENDING
    )
    assert repository.updates[0]["status"] == NotificationStatus.SENT
    assert repository.updates[0]["message_id"] == "ses-message-1"
    assert result["notification_status"] == "SENT"


def test_email_failure_keeps_gap_and_records_delivery_error() -> None:
    repository = FakeRepository()
    workflow = QuestionWorkflow(
        repository=repository,  # type: ignore[arg-type]
        email_sender=FailingSender(),  # type: ignore[arg-type]
        reply_domain="example.com",
    )

    result = workflow.create_question(
        project_id="prj_1",
        gap=_gap(),
        created_by="mcp-agent",
    )

    assert repository.updates[0]["status"] == NotificationStatus.FAILED
    assert "recipient is not verified" in repository.updates[0]["error"]
    assert result["question_id"] == "gap_1"
    assert result["notification_status"] == "FAILED"


def test_create_question_passes_stable_question_id() -> None:
    repository = FakeRepository()
    workflow = QuestionWorkflow(
        repository=repository,  # type: ignore[arg-type]
        email_sender=None,
        reply_domain=None,
    )

    workflow.create_question(
        project_id="prj_1",
        gap=_gap(),
        created_by="mcp-agent",
        question_id="gap_stable",
    )

    assert repository.create_kwargs is not None
    assert repository.create_kwargs["question_id"] == "gap_stable"


def test_untargeted_question_disables_direct_email_delivery() -> None:
    repository = FakeRepository()
    workflow = QuestionWorkflow(
        repository=repository,  # type: ignore[arg-type]
        email_sender=ExplodingSender(),  # type: ignore[arg-type]
        reply_domain="example.com",
    )

    workflow.create_question(
        project_id="prj_1",
        gap=KnowledgeGapCreate(question="Who owned the rollout?"),
        created_by="asker@blend360.com",
    )

    assert repository.create_kwargs is not None
    assert repository.create_kwargs["reply_domain"] is None
    assert (
        repository.create_kwargs["notification_status"]
        == NotificationStatus.DISABLED
    )
