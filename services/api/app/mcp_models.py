from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any, cast

from pydantic import BaseModel

from knowledge_core.models import SearchHit, SearchResponse

_PREVIEW_CHARACTERS = 1_600


class McpProject(BaseModel):
    project_id: str
    name: str
    description: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class McpDocumentSummary(BaseModel):
    project_id: str
    document_id: str
    document_name: str
    document_version: str
    status: str
    source_type: str
    markdown_available: bool
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_record(
        cls,
        document: Mapping[str, Any],
    ) -> McpDocumentSummary:
        return cls.model_validate(
            {
                **document,
                "markdown_available": bool(document.get("enhanced_s3_key")),
            }
        )


class McpSearchHit(BaseModel):
    document_id: str
    document_name: str
    source_type: str | None = None
    source_s3_key: str | None = None
    page_number: int | None = None
    page_count: int | None = None
    locator: str | None = None
    text_preview: str
    text_truncated: bool
    rrf_score: float
    bm25_score: float | None = None
    vector_score: float | None = None
    bm25_rank: int | None = None
    vector_rank: int | None = None

    @classmethod
    def from_hit(cls, hit: SearchHit) -> McpSearchHit:
        preview, truncated = _text_preview(hit.text)
        return cls(
            document_id=hit.document_id,
            document_name=hit.document_name,
            source_type=hit.source_type,
            source_s3_key=hit.s3_key,
            page_number=hit.page_number,
            page_count=hit.page_count,
            locator=hit.locator,
            text_preview=preview,
            text_truncated=truncated,
            rrf_score=hit.rrf_score,
            bm25_score=hit.bm25_score,
            vector_score=hit.vector_score,
            bm25_rank=hit.bm25_rank,
            vector_rank=hit.vector_rank,
        )


class McpSearchResponse(BaseModel):
    project_id: str
    query: str
    hits: list[McpSearchHit]
    warnings: list[str]
    score_note: str

    @classmethod
    def from_search(cls, response: SearchResponse) -> McpSearchResponse:
        return cls(
            project_id=response.project_id,
            query=response.query,
            hits=[McpSearchHit.from_hit(hit) for hit in response.hits],
            warnings=[_safe_warning(warning) for warning in response.warnings],
            score_note=response.score_note,
        )


class McpDocumentText(BaseModel):
    project_id: str
    document_id: str
    document_name: str
    document_version: str
    status: str
    source_type: str
    source_s3_bucket: str
    source_s3_key: str
    enhanced_s3_key: str | None
    page_count: int | None
    text: str | None
    content_hash: str | None

    @classmethod
    def from_records(
        cls,
        *,
        document: Mapping[str, Any],
        indexed_documents: Sequence[Mapping[str, Any]],
    ) -> McpDocumentText:
        ordered = sorted(
            indexed_documents,
            key=lambda item: (
                int(item.get("page_number") or 0),
                str(item.get("index_id") or item.get("_id") or ""),
            ),
        )
        texts = [
            str(item.get("text") or "").strip()
            for item in ordered
            if str(item.get("text") or "").strip()
        ]
        text = "\n\n".join(texts) or None
        content_hash = (
            hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None
        )
        return cls(
            project_id=str(document["project_id"]),
            document_id=str(document["document_id"]),
            document_name=str(document["document_name"]),
            document_version=str(document.get("document_version", "1")),
            status=str(document["status"]),
            source_type=str(document.get("source_type", "UPLOADED")),
            source_s3_bucket=str(document["s3_bucket"]),
            source_s3_key=str(document["s3_key"]),
            enhanced_s3_key=cast(str | None, document.get("enhanced_s3_key")),
            page_count=(
                int(document["page_count"])
                if document.get("page_count") is not None
                else None
            ),
            text=text,
            content_hash=content_hash,
        )


class McpDocumentDownload(BaseModel):
    project_id: str
    document_id: str
    document_name: str
    download_format: str
    filename: str
    content_type: str
    url: str
    expires_in_seconds: int


class McpVerifiedFact(BaseModel):
    project_id: str
    fact_id: str
    name: str
    value: str
    provenance: str
    source_document_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class McpKnowledgeGap(BaseModel):
    project_id: str
    project_name: str
    question_id: str
    question: str
    context: str | None = None
    assigned_expert_email: str
    priority: str
    status: str
    notification_status: str
    notification_error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


def _text_preview(text: str) -> tuple[str, bool]:
    if len(text) <= _PREVIEW_CHARACTERS:
        return text, False
    return text[:_PREVIEW_CHARACTERS].rstrip() + "…", True


def _safe_warning(warning: str) -> str:
    if warning.startswith("BM25 channel failed"):
        return "BM25 retrieval is temporarily unavailable."
    if warning.startswith("Vector channel failed"):
        return "Vector retrieval is temporarily unavailable."
    return "One retrieval channel returned an unexpected warning."
