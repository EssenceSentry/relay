from __future__ import annotations

import logging
from typing import Any

from knowledge_core.dynamo import KnowledgeRepository
from knowledge_core.email_service import QuestionEmailSender
from knowledge_core.models import (
    KnowledgeGapCreate,
    NotificationKind,
    NotificationStatus,
)
from knowledge_core.notifications import NotificationPublisher

LOGGER = logging.getLogger(__name__)


class QuestionWorkflow:
    def __init__(
        self,
        *,
        repository: KnowledgeRepository,
        email_sender: QuestionEmailSender | None,
        reply_domain: str | None,
        notifications: NotificationPublisher | None = None,
        application_base_url: str | None = None,
    ) -> None:
        self._repository = repository
        self._email_sender = email_sender
        self._reply_domain = reply_domain
        self._notifications = notifications
        self._application_base_url = application_base_url

    def create_question(
        self,
        *,
        project_id: str,
        gap: KnowledgeGapCreate,
        created_by: str,
        question_id: str | None = None,
    ) -> dict[str, Any]:
        sends_direct_email = (
            self._email_sender is not None
            and gap.assigned_expert_email is not None
        )
        question = self._repository.create_question(
            project_id=project_id,
            gap=gap,
            created_by=created_by,
            question_id=question_id,
            reply_domain=(self._reply_domain if sends_direct_email else None),
            notification_status=(
                NotificationStatus.PENDING
                if sends_direct_email
                else NotificationStatus.DISABLED
            ),
        )
        self._publish_notifications(question)
        if not sends_direct_email:
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

    def _publish_notifications(self, question: dict[str, Any]) -> None:
        publisher = self._notifications
        if publisher is None:
            return
        project_id = str(question["project_id"])
        project_name = str(question["project_name"])
        assigned_value = question.get("assigned_expert_email")
        assigned_email = str(assigned_value) if assigned_value else None
        recipients = {
            str(member["email"])
            for member in self._repository.list_project_members(project_id)
        }
        if assigned_email is not None:
            recipients.add(assigned_email)
        for email in sorted(recipients):
            assigned = email == assigned_email
            publisher.publish(
                email=email,
                kind=(
                    NotificationKind.QUESTION_ASSIGNED
                    if assigned
                    else NotificationKind.QUESTION_CREATED
                ),
                title=(
                    f"Your expertise is needed for {project_name}"
                    if assigned
                    else f"New question for {project_name}"
                ),
                message=(
                    str(question["question"])
                    if assigned
                    else (
                        (
                            f"A project question was assigned to "
                            f"{assigned_email}: {question['question']}"
                        )
                        if assigned_email is not None
                        else str(question["question"])
                    )
                ),
                project_id=project_id,
                action_url=self._application_base_url,
                send_email=not assigned,
                data={
                    "project_name": project_name,
                    "question_id": question["question_id"],
                    "assigned_expert_email": assigned_email,
                },
                notification_id=(
                    f"question-{question['question_id']}-"
                    f"{email.replace('@', '-')}"
                ),
            )
