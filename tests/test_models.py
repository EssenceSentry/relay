from __future__ import annotations

import pytest
from pydantic import ValidationError

from knowledge_core.models import (
    KnowledgeGapCreate,
    SearchResponse,
    UploadRequest,
)


def test_knowledge_gap_normalizes_email() -> None:
    gap = KnowledgeGapCreate(
        question="Who was the delivery lead?",
        assigned_expert_email="  Expert@Blend360.COM ",
    )

    assert gap.assigned_expert_email == "expert@blend360.com"


def test_knowledge_gap_accepts_a_verified_demo_account_address() -> None:
    gap = KnowledgeGapCreate(
        question="Who was the delivery lead?",
        assigned_expert_email=" Essence.Sentry@Gmail.COM ",
    )

    assert gap.assigned_expert_email == "essence.sentry@gmail.com"


def test_knowledge_gap_rejects_unknown_priority() -> None:
    with pytest.raises(ValidationError):
        KnowledgeGapCreate(
            question="Who was the delivery lead?",
            assigned_expert_email="expert@blend360.com",
            priority="urgent",  # type: ignore[arg-type]
        )


def test_knowledge_gap_can_be_created_without_a_requested_answerer() -> None:
    gap = KnowledgeGapCreate(question="Who owned the delivery rollout?")

    assert gap.assigned_expert_email is None


def test_search_response_explains_scores() -> None:
    response = SearchResponse(project_id="prj_1", query="test", hits=[])

    assert "not calibrated probabilities" in response.score_note


def test_upload_request_allows_authenticated_limit() -> None:
    request = UploadRequest(
        filename="large-deck.pptx",
        content_type="application/octet-stream",
        size_bytes=100 * 1024 * 1024,
    )

    assert request.size_bytes == 100 * 1024 * 1024


def test_upload_request_rejects_files_above_authenticated_limit() -> None:
    with pytest.raises(ValidationError):
        UploadRequest(
            filename="too-large-deck.pptx",
            content_type="application/octet-stream",
            size_bytes=100 * 1024 * 1024 + 1,
        )
