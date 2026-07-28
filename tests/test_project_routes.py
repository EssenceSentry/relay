from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.auth import Principal
from app.routes import build_api_router
from fastapi import FastAPI

from test_support.http_client import make_test_client


class FakeRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def rename_project(
        self,
        *,
        project_id: str,
        name: str,
        updated_by: str,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "project_id": project_id,
                "name": name,
                "updated_by": updated_by,
            }
        )
        if project_id == "prj_missing":
            raise KeyError(project_id)
        return {
            "project_id": project_id,
            "name": name,
            "updated_by": updated_by,
            "created_by": "owner@blend360.com",
        }

    def get_project(self, project_id: str) -> dict[str, str] | None:
        if project_id == "prj_missing":
            return None
        return {
            "project_id": project_id,
            "name": "Project one",
            "status": "ACTIVE",
            "created_by": "owner@blend360.com",
        }

    def get_user_profile(self, email: str) -> dict[str, Any] | None:
        if email == "owner@blend360.com":
            return {
                "email": email,
                "display_name": "Project Owner",
                "email_verified": True,
            }
        if email == "collaborator@blend360.com":
            return {
                "email": email,
                "display_name": "Project Collaborator",
                "email_verified": True,
            }
        if email == "unverified@blend360.com":
            return {
                "email": email,
                "display_name": "Unverified Person",
            }
        return None

    def list_project_members(self, project_id: str) -> list[dict[str, str]]:
        assert project_id == "prj_1"
        return [
            {
                "project_id": project_id,
                "email": "owner@blend360.com",
                "role": "AUTHOR",
                "source": "PROJECT_AUTHOR",
            },
            {
                "project_id": project_id,
                "email": "collaborator@blend360.com",
                "role": "COLLABORATOR",
                "source": "MANUAL_INVITATION",
            },
            {
                "project_id": project_id,
                "email": "unverified@blend360.com",
                "role": "COLLABORATOR",
                "source": "DOCUMENT_EXACT_EMAIL",
            },
        ]

    def is_project_member(self, *, project_id: str, email: str) -> bool:
        return project_id == "prj_1" and email == "owner@blend360.com"

    def get_project_membership(
        self,
        *,
        project_id: str,
        email: str,
    ) -> dict[str, str] | None:
        if self.is_project_member(project_id=project_id, email=email):
            return {
                "project_id": project_id,
                "email": email,
                "role": "AUTHOR",
            }
        return None


def _client(repository: FakeRepository):
    principal = Principal(
        subject="user-1",
        email="owner@blend360.com",
        groups=frozenset(),
        claims={},
    )
    container = SimpleNamespace(
        repository=repository,
        settings=SimpleNamespace(
            application_base_url="https://knowledge.example.com",
        ),
    )
    app = FastAPI()
    app.include_router(
        build_api_router(
            container,  # pyright: ignore[reportArgumentType]
            lambda: principal,
        )
    )
    return make_test_client(app)


def test_rename_project_endpoint_returns_updated_project() -> None:
    repository = FakeRepository()
    client = _client(repository)

    response = client.patch(
        "/api/projects/prj_1",
        json={"name": "  New project name  "},
    )

    assert response.status_code == 200
    assert response.json() == {
        "project_id": "prj_1",
        "name": "New project name",
        "updated_by": "owner@blend360.com",
        "created_by": "owner@blend360.com",
        "author_display_name": "Project Owner",
        "author_email": "owner@blend360.com",
        "my_role": "AUTHOR",
        "can_edit": True,
        "can_ask_questions": True,
        "can_answer_questions": True,
        "can_archive": False,
        "upload_page_url": (
            "https://knowledge.example.com/upload.html?upload_project_id=prj_1"
        ),
    }
    assert repository.calls == [
        {
            "project_id": "prj_1",
            "name": "New project name",
            "updated_by": "owner@blend360.com",
        }
    ]


def test_collaborator_endpoint_identifies_verified_suggested_experts() -> None:
    response = _client(FakeRepository()).get(
        "/api/projects/prj_1/collaborators"
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "project_id": "prj_1",
            "email": "owner@blend360.com",
            "role": "AUTHOR",
            "source": "PROJECT_AUTHOR",
            "display_name": "Project Owner",
            "email_verified": True,
        },
        {
            "project_id": "prj_1",
            "email": "collaborator@blend360.com",
            "role": "COLLABORATOR",
            "source": "MANUAL_INVITATION",
            "display_name": "Project Collaborator",
            "email_verified": True,
        },
        {
            "project_id": "prj_1",
            "email": "unverified@blend360.com",
            "role": "COLLABORATOR",
            "source": "DOCUMENT_EXACT_EMAIL",
            "display_name": "Unverified Person",
            "email_verified": False,
        },
    ]


def test_rename_project_endpoint_returns_not_found() -> None:
    response = _client(FakeRepository()).patch(
        "/api/projects/prj_missing",
        json={"name": "New project name"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Project not found"}


def test_rename_project_endpoint_rejects_blank_name() -> None:
    response = _client(FakeRepository()).patch(
        "/api/projects/prj_1",
        json={"name": "  "},
    )

    assert response.status_code == 422
