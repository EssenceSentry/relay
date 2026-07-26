from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import Any

import pytest

from knowledge_core.models import (
    ContributorCandidate,
    DocumentEnhancementResult,
    NameMatchDecision,
    NameMatchResult,
)
from knowledge_core.openai_api import (
    DOCUMENT_ENHANCEMENT_INSTRUCTIONS,
    OpenAIService,
)


class FakeResponses:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(
            output_parsed=DocumentEnhancementResult(markdown=self.output_text)
        )


class FakeMatchingResponses:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(
            output_parsed=NameMatchResult(
                decision=NameMatchDecision.MATCH,
                confidence=0.97,
                rationale="The identity uniquely aligns.",
            )
        )


def _service(responses: FakeResponses) -> OpenAIService:
    service = object.__new__(OpenAIService)
    service.__dict__["_client"] = SimpleNamespace(responses=responses)
    service.__dict__["_document_model"] = "gpt-5.4-mini"
    return service


def test_document_enhancement_sends_high_detail_pdf_and_extracted_text() -> (
    None
):
    responses = FakeResponses("# Clean document")
    service = _service(responses)

    markdown = service.enhance_document_markdown(
        filename="source.pptx",
        rendered_pdf=b"%PDF-1.7\nrendered",
        extracted_text="Deterministic source text",
    )

    assert markdown == "# Clean document"
    call = responses.calls[0]
    assert call["model"] == "gpt-5.4-mini"
    assert call["reasoning"] == {"effort": "low"}
    assert call["store"] is False
    assert call["instructions"] == DOCUMENT_ENHANCEMENT_INSTRUCTIONS
    content = call["input"][0]["content"]
    input_file = content[0]
    assert input_file["type"] == "input_file"
    assert input_file["filename"] == "source.pdf"
    assert input_file["detail"] == "high"
    encoded_pdf = input_file["file_data"].split(",", maxsplit=1)[1]
    assert base64.b64decode(encoded_pdf) == b"%PDF-1.7\nrendered"
    assert "Deterministic source text" in content[1]["text"]


def test_document_enhancement_prompt_excludes_decorative_page_furniture() -> (
    None
):
    instructions = DOCUMENT_ENHANCEMENT_INSTRUCTIONS.casefold()

    for excluded_visual in (
        "logos",
        "banners",
        "stock photos",
        "workspace or lifestyle photography",
        "confidentiality notices",
        "page numbers",
    ):
        assert excluded_visual in instructions
    for qualifying_visual in (
        "plots",
        "charts",
        "infographics",
        "process or system diagrams",
        "substantive tables",
    ):
        assert qualifying_visual in instructions


def test_document_enhancement_strips_markdown_code_fence() -> None:
    service = _service(FakeResponses("```markdown\n# Clean\n```"))

    markdown = service.enhance_document_markdown(
        filename="source.pdf",
        rendered_pdf=b"%PDF-1.7\nrendered",
        extracted_text="",
    )

    assert markdown == "# Clean"


def test_document_enhancement_rejects_empty_model_output() -> None:
    service = _service(FakeResponses(" "))

    with pytest.raises(RuntimeError, match="empty enhanced Markdown"):
        service.enhance_document_markdown(
            filename="source.pdf",
            rendered_pdf=b"%PDF-1.7\nrendered",
            extracted_text="source",
        )


def test_name_match_includes_nearby_contributors_for_disambiguation() -> None:
    responses = FakeMatchingResponses()
    service = object.__new__(OpenAIService)
    service.__dict__["_client"] = SimpleNamespace(responses=responses)
    service.__dict__["_matching_model"] = "gpt-5.6-luna"

    result = service.match_contributor_name(
        user_email="maria.perez@blend360.com",
        user_display_name="Maria Perez",
        candidate=ContributorCandidate(
            display_name="María Pérez",
            relationship="Delivery lead",
            confidence=0.96,
            evidence="María Pérez led delivery.",
        ),
        nearby_candidate_names=["María Pereira", "Mario Pérez"],
    )

    assert result.decision == NameMatchDecision.MATCH
    call = responses.calls[0]
    assert call["model"] == "gpt-5.6-luna"
    assert call["reasoning"] == {"effort": "low"}
    prompt = call["input"][0]["content"]
    assert "María Pereira, Mario Pérez" in prompt
