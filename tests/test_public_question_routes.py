from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.routes import build_api_router
from fastapi import FastAPI

from test_support.http_client import HttpTestClient, make_test_client

_TOKEN = "a" * 48


class FakeRepository:
    def __init__(self, *, status: str = "OPEN") -> None:
        self.status = status
        self.submissions: list[dict[str, str]] = []

    def get_question_by_reply_token(
        self,
        reply_token: str,
    ) -> dict[str, Any] | None:
        if reply_token != _TOKEN:
            return None
        return {
            "project_id": "prj_private",
            "project_name": "Snowflake modernization",
            "question_id": "gap_private",
            "question": "Who owned the production cutover?",
            "context": "The source material names a team, but not an owner.",
            "priority": "high",
            "status": self.status,
            "review_rationale": (
                "Please name the accountable individual."
                if self.status == "NEEDS_MORE_INFO"
                else None
            ),
            "assigned_expert_email": "expert@example.com",
            "reply_address": f"kg-{_TOKEN}@example.com",
        }

    def submit_answer(
        self,
        *,
        project_id: str,
        question_id: str,
        answer: str,
        answered_by: str,
    ) -> dict[str, str]:
        if self.status == "RESOLVED":
            raise ValueError("Question is already resolved")
        self.submissions.append(
            {
                "project_id": project_id,
                "question_id": question_id,
                "answer": answer,
                "answered_by": answered_by,
            }
        )
        return {"answer_id": "ans_123"}


def _client(repository: FakeRepository) -> HttpTestClient:
    container = SimpleNamespace(repository=repository)

    def authenticated_route_only() -> None:
        raise AssertionError("The public answer route requested authentication")

    app = FastAPI()
    app.include_router(
        build_api_router(
            container,  # pyright: ignore[reportArgumentType]
            authenticated_route_only,
        )
    )
    return make_test_client(app)


def test_private_link_returns_only_safe_question_fields() -> None:
    response = _client(FakeRepository(status="NEEDS_MORE_INFO")).get(
        "/api/public/question",
        headers={"X-Answer-Token": _TOKEN},
    )

    assert response.status_code == 200
    assert response.json() == {
        "project_name": "Snowflake modernization",
        "question": "Who owned the production cutover?",
        "context": "The source material names a team, but not an owner.",
        "priority": "high",
        "status": "NEEDS_MORE_INFO",
        "review_rationale": "Please name the accountable individual.",
        "can_answer": True,
    }
    assert "assigned_expert_email" not in response.text
    assert "reply_address" not in response.text
    assert "prj_private" not in response.text
    assert "gap_private" not in response.text


def test_private_link_submits_as_the_assigned_expert() -> None:
    repository = FakeRepository()

    response = _client(repository).post(
        "/api/public/question/answers",
        headers={"X-Answer-Token": _TOKEN},
        json={"answer": "Priya Shah owned the production cutover."},
    )

    assert response.status_code == 202
    assert response.json() == {
        "status": "SUBMITTED",
        "answer_id": "ans_123",
    }
    assert repository.submissions == [
        {
            "project_id": "prj_private",
            "question_id": "gap_private",
            "answer": "Priya Shah owned the production cutover.",
            "answered_by": "expert@example.com",
        }
    ]


def test_invalid_or_unknown_private_link_is_rejected() -> None:
    client = _client(FakeRepository())

    malformed = client.get(
        "/api/public/question",
        headers={"X-Answer-Token": "not-a-valid-token"},
    )
    unknown = client.get(
        "/api/public/question",
        headers={"X-Answer-Token": "b" * 48},
    )

    assert malformed.status_code == 422
    assert unknown.status_code == 404
    assert unknown.json()["detail"] == (
        "This answer link is invalid or no longer available"
    )


def test_resolved_question_can_be_viewed_but_not_answered_again() -> None:
    client = _client(FakeRepository(status="RESOLVED"))

    question = client.get(
        "/api/public/question",
        headers={"X-Answer-Token": _TOKEN},
    )
    answer = client.post(
        "/api/public/question/answers",
        headers={"X-Answer-Token": _TOKEN},
        json={"answer": "A duplicate answer."},
    )

    assert question.status_code == 200
    assert question.json()["can_answer"] is False
    assert answer.status_code == 409
    assert answer.json()["detail"] == "Question is already resolved"
