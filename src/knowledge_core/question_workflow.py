from __future__ import annotations

import logging
from typing import Any

from knowledge_core.dynamo import KnowledgeRepository
from knowledge_core.email_service import QuestionEmailSender
from knowledge_core.models import KnowledgeGapCreate, NotificationStatus

LOGGER = logging.getLogger(__name__)


class QuestionWorkflow:
    def __init__(
        self,
        *,
        repository: KnowledgeRepository,
        email_sender: QuestionEmailSender | None,
        reply_domain: str | None,
    ) -> None:
        self._repository = repository
        self._email_sender = email_sender
        self._reply_domain = reply_domain

    def create_question(
        self,
        *,
        project_id: str,
        gap: KnowledgeGapCreate,
        created_by: str,
        question_id: str | None = None,
    ) -> dict[str, Any]:
        question = self._repository.create_question(
            project_id=project_id,
            gap=gap,
            created_by=created_by,
            question_id=question_id,
            reply_domain=(self._reply_domain if self._email_sender else None),
            notification_status=(
                NotificationStatus.PENDING
                if self._email_sender
                else NotificationStatus.DISABLED
            ),
        )
        if self._email_sender is None:
            return question
        return self._send(question)

    def resend_question(
        self,
        *,
        project_id: str,
        question_id: str,
    ) -> dict[str, Any]:
        if self._email_sender is None:
            raise RuntimeError("Email notifications are not configured")
        question = self._repository.get_question(
            project_id=project_id,
            question_id=question_id,
        )
        if question is None:
            raise KeyError(f"Question {question_id!r} does not exist")
        return self._send(question)

    def _send(self, question: dict[str, Any]) -> dict[str, Any]:
        email_sender = self._email_sender
        if email_sender is None:
            raise RuntimeError("Email notifications are not configured")
        try:
            result = email_sender.send_question(question)
        except Exception as exc:
            LOGGER.exception(
                "Could not send knowledge request %s",
                question["question_id"],
            )
            return self._repository.update_question_notification(
                project_id=question["project_id"],
                question_id=question["question_id"],
                status=NotificationStatus.FAILED,
                error=f"{type(exc).__name__}: {exc}",
            )
        return self._repository.update_question_notification(
            project_id=question["project_id"],
            question_id=question["question_id"],
            status=NotificationStatus.SENT,
            message_id=result.message_id,
        )
