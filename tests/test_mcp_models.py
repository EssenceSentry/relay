from __future__ import annotations

from app.mcp_models import (
    McpDocumentSummary,
    McpDocumentText,
    McpSearchResponse,
)

from knowledge_core.models import SearchHit, SearchResponse


def test_search_response_uses_bounded_previews_and_safe_warnings() -> None:
    response = SearchResponse(
        project_id="prj_1",
        query="launch owner",
        hits=[
            SearchHit(
                index_id="idx_1",
                project_id="prj_1",
                document_id="doc_1",
                document_name="dossier.md",
                text="x" * 2_000,
                s3_key="uploads/prj_1/doc_1/dossier.md",
                page_number=3,
                page_count=8,
                locator="page 3 of 8",
                rrf_score=0.02,
            )
        ],
        warnings=["Vector channel failed: RuntimeError: internal detail"],
    )

    result = McpSearchResponse.from_search(response)

    assert result.hits[0].text_preview == "x" * 1_600 + "…"
    assert result.hits[0].text_truncated is True
    assert "s3_key" not in result.hits[0].model_dump()
    assert result.hits[0].page_number == 3
    assert result.hits[0].locator == "page 3 of 8"
    assert result.warnings == ["Vector retrieval is temporarily unavailable."]
    assert "do not stop after reporting the gap" in (
        result.insufficient_evidence_action
    )
    assert "call get_project and list_project_collaborators" in (
        result.insufficient_evidence_action
    )
    assert "explicit user confirmation" in result.insufficient_evidence_action


def test_document_text_concatenates_pages_and_references_original() -> None:
    result = McpDocumentText.from_records(
        document={
            "project_id": "prj_1",
            "document_id": "doc_1",
            "document_name": "dossier.pptx",
            "document_version": "1",
            "status": "READY",
            "source_type": "UPLOADED",
            "s3_bucket": "documents",
            "s3_key": "uploads/prj_1/doc_1/dossier.pptx",
            "enhanced_s3_key": "extracted/prj_1/doc_1/document.md",
            "page_count": 2,
        },
        indexed_documents=[
            {"page_number": 2, "text": "page two"},
            {"page_number": 1, "text": "page one"},
        ],
    )

    assert result.text == "page one\n\npage two"
    assert result.page_count == 2
    assert "s3_key" not in result.model_dump()
    assert "enhanced_s3_key" not in result.model_dump()
    assert result.content_hash is not None


def test_document_summary_reports_markdown_availability() -> None:
    result = McpDocumentSummary.from_record(
        {
            "project_id": "prj_1",
            "document_id": "doc_1",
            "document_name": "dossier.pptx",
            "document_version": "1",
            "status": "READY",
            "source_type": "UPLOADED",
            "enhanced_s3_key": "extracted/prj_1/doc_1/document.md",
        }
    )

    assert result.markdown_available is True
