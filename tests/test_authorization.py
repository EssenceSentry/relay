from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from app.application import (
    AuthenticationRequired,
    KnowledgeApplication,
    NotFound,
    PermissionDenied,
)
from app.auth import Principal

from knowledge_core.models import AnswerSubmit, KnowledgeGapCreate


class FakeRepository:
    def __init__(self, *, archived: bool = False, member: bool = False) -> None:
        self.archived = archived
        self.member = member

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        if project_id == "missing":
            return None
        return {
            "project_id": project_id,
            "name": "Project one",
            "status": "ARCHIVED" if self.archived else "ACTIVE",
        }

    def is_project_member(self, *, project_id: str, email: str) -> bool:
        assert project_id == "prj_1"
        assert email.endswith("@blend360.com")
        return self.member


class FakeQuestions:
    def create_question(
        self,
        *,
        project_id: str,
        gap: KnowledgeGapCreate,
        created_by: str,
        question_id: str | None,
    ) -> dict[str, Any]:
        return {
            "project_id": project_id,
            "gap": gap,
            "created_by": created_by,
            "question_id": question_id,
        }


class AnswerRepository(FakeRepository):
    def __init__(self) -> None:
        super().__init__(member=False)
        self.requires_human_review: bool | None = None

    def get_question(
        self,
        *,
        project_id: str,
        question_id: str,
    ) -> dict[str, Any] | None:
        return {
            "project_id": project_id,
            "question_id": question_id,
            "question": "What was the outcome?",
        }

    def submit_answer(
        self,
        *,
        project_id: str,
        question_id: str,
        answer: str,
        answered_by: str,
        requires_human_review: bool,
        source: str,
        answer_id: str | None,
        supporting_document_ids: list[str],
    ) -> dict[str, Any]:
        del source, answer_id, supporting_document_ids
        self.requires_human_review = requires_human_review
        return {
            "project_id": project_id,
            "question_id": question_id,
            "answer": answer,
            "answered_by": answered_by,
            "requires_human_review": requires_human_review,
        }


def _principal(
    *,
    admin: bool = False,
    public: bool = False,
) -> Principal:
    return Principal(
        subject="user-1",
        email=("public@hackathon.local" if public else "employee@blend360.com"),
        groups=frozenset({"admins"} if admin else set()),
        claims={"authentication_mode": "public"} if public else {},
    )


def _authorization(repository: FakeRepository) -> KnowledgeApplication:
    container = SimpleNamespace(repository=repository)
    return KnowledgeApplication(
        container,  # pyright: ignore[reportArgumentType]
    )


def test_verified_employee_can_read_an_active_project() -> None:
    project = _authorization(FakeRepository()).require_project(
        "prj_1",
        principal=_principal(),
    )

    assert project["project_id"] == "prj_1"


def test_project_writes_require_member_or_admin() -> None:
    authorization = _authorization(FakeRepository())

    with pytest.raises(PermissionDenied):
        authorization.require_member("prj_1", principal=_principal())

    assert (
        _authorization(FakeRepository(member=True)).require_member(
            "prj_1", principal=_principal()
        )["project_id"]
        == "prj_1"
    )
    assert (
        authorization.require_member(
            "prj_1",
            principal=_principal(admin=True),
        )["project_id"]
        == "prj_1"
    )


def test_verified_reader_can_create_a_project_question() -> None:
    application = KnowledgeApplication(
        SimpleNamespace(
            repository=FakeRepository(),
            questions=FakeQuestions(),
        ),  # pyright: ignore[reportArgumentType]
    )

    created = application.create_project_question(
        "prj_1",
        KnowledgeGapCreate(question="Who owned the rollout?"),
        principal=_principal(),
    )

    assert created["project_id"] == "prj_1"
    assert created["created_by"] == "employee@blend360.com"


def test_public_mode_cannot_use_authenticated_write_operations() -> None:
    with pytest.raises(AuthenticationRequired):
        _authorization(FakeRepository(member=True)).require_member(
            "prj_1",
            principal=_principal(public=True),
        )


def test_only_admin_can_read_archived_projects() -> None:
    authorization = _authorization(FakeRepository(archived=True))

    with pytest.raises(NotFound):
        authorization.require_project("prj_1", principal=_principal())

    assert (
        authorization.require_project(
            "prj_1",
            principal=_principal(admin=True),
        )["status"]
        == "ARCHIVED"
    )


def test_admin_answer_skips_human_approval() -> None:
    repository = AnswerRepository()
    application = KnowledgeApplication(
        SimpleNamespace(repository=repository),  # pyright: ignore[reportArgumentType]
    )

    answer = application.submit_question_answer(
        "prj_1",
        "gap_1",
        AnswerSubmit(answer="The rollout increased conversion."),
        principal=_principal(admin=True),
    )

    assert repository.requires_human_review is False
    assert answer["requires_human_review"] is False
