from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class DocumentStatus(StrEnum):
    UPLOADING = "UPLOADING"
    QUEUED = "QUEUED"
    PARSING = "PARSING"
    EMBEDDING = "EMBEDDING"
    INDEXING = "INDEXING"
    READY = "READY"
    FAILED = "FAILED"


class QuestionStatus(StrEnum):
    OPEN = "OPEN"
    NEEDS_MORE_INFO = "NEEDS_MORE_INFO"
    RESOLVED = "RESOLVED"


class AnswerStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    ACCEPTED = "ACCEPTED"
    NEEDS_MORE_INFO = "NEEDS_MORE_INFO"
    FAILED = "FAILED"


class NotificationStatus(StrEnum):
    DISABLED = "DISABLED"
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class TextSection(BaseModel):
    text: str
    locator: str | None = None
    title: str | None = None
    page_number: int | None = None

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return "\n".join(line.rstrip() for line in value.strip().splitlines())


class IndexedDocument(BaseModel):
    index_id: str
    project_id: str
    document_id: str
    document_version: str
    document_name: str
    source_type: str = "UPLOADED"
    text: str
    content_hash: str
    s3_bucket: str
    s3_key: str
    page_number: int | None = None
    page_count: int | None = None
    locator: str | None = None
    embedding: list[float] | None = None

    def search_document(self) -> dict[str, Any]:
        data = self.model_dump(exclude_none=True)
        if self.embedding is None:
            data.pop("embedding", None)
        return data


class SearchHit(BaseModel):
    index_id: str
    project_id: str
    document_id: str
    document_name: str
    text: str
    source_type: str | None = None
    s3_bucket: str | None = None
    s3_key: str | None = None
    page_number: int | None = None
    page_count: int | None = None
    locator: str | None = None
    rrf_score: float
    bm25_score: float | None = None
    vector_score: float | None = None
    bm25_rank: int | None = None
    vector_rank: int | None = None


class SearchResponse(BaseModel):
    project_id: str
    query: str
    hits: list[SearchHit]
    warnings: list[str] = Field(default_factory=list)
    score_note: str = (
        "Raw BM25 and vector scores are engine-specific relevance scores, "
        "not calibrated probabilities. rrf_score is rank-fusion evidence."
    )


class GlobalSearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]
    warnings: list[str] = Field(default_factory=list)
    score_note: str = (
        "Raw BM25 and vector scores are engine-specific relevance scores, "
        "not calibrated probabilities. rrf_score is rank-fusion evidence."
    )


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class UploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=240)
    content_type: str = Field(min_length=1, max_length=120)
    size_bytes: int = Field(gt=0, le=100 * 1024 * 1024)


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=4000)
    top_k: int = Field(default=8, ge=1, le=25)


class KnowledgeGapCreate(BaseModel):
    question: str = Field(min_length=5, max_length=4000)
    assigned_expert_email: str = Field(min_length=3, max_length=320)
    context: str | None = Field(default=None, max_length=8000)
    priority: Literal["low", "normal", "high"] = "normal"

    @field_validator("assigned_expert_email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().casefold()


class AnswerSubmit(BaseModel):
    answer: str = Field(min_length=3, max_length=20_000)


class VerifiedFactCreate(BaseModel):
    name: str = Field(min_length=2, max_length=300)
    value: str = Field(min_length=1, max_length=8000)
    provenance: str = Field(min_length=2, max_length=2000)


class AnswerReview(BaseModel):
    sufficient: bool
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=3000)
    missing_details: list[str] = Field(default_factory=list, max_length=12)
    title: str | None = Field(default=None, max_length=200)
    normalized_answer: str | None = Field(default=None, max_length=12_000)
    document_markdown: str | None = Field(default=None, max_length=20_000)

    @field_validator("title", "normalized_answer", "document_markdown")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None
