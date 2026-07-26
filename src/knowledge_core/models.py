from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from knowledge_core.identity import normalize_blend_email, normalize_email


class DocumentStatus(StrEnum):
    UPLOADING = "UPLOADING"
    QUEUED = "QUEUED"
    PARSING = "PARSING"
    EMBEDDING = "EMBEDDING"
    INDEXING = "INDEXING"
    READY = "READY"
    FAILED = "FAILED"


class ProjectStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class MembershipRole(StrEnum):
    AUTHOR = "AUTHOR"
    COLLABORATOR = "COLLABORATOR"


class MembershipSource(StrEnum):
    PROJECT_AUTHOR = "PROJECT_AUTHOR"
    MANUAL_INVITATION = "MANUAL_INVITATION"
    DOCUMENT_EXACT_EMAIL = "DOCUMENT_EXACT_EMAIL"
    DOCUMENT_NAME_MATCH = "DOCUMENT_NAME_MATCH"
    ADMIN_OVERRIDE = "ADMIN_OVERRIDE"


class InvitationStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


class QuestionStatus(StrEnum):
    OPEN = "OPEN"
    NEEDS_MORE_INFO = "NEEDS_MORE_INFO"
    RESOLVED = "RESOLVED"


class AnswerStatus(StrEnum):
    PENDING_HUMAN = "PENDING_HUMAN"
    WAITING_DOCUMENTS = "WAITING_DOCUMENTS"
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    NEEDS_MORE_INFO = "NEEDS_MORE_INFO"
    FAILED = "FAILED"


class NotificationStatus(StrEnum):
    DISABLED = "DISABLED"
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SENT = "SENT"
    FAILED = "FAILED"


class NotificationKind(StrEnum):
    COLLABORATOR_ADDED = "COLLABORATOR_ADDED"
    COLLABORATION_INVITATION = "COLLABORATION_INVITATION"
    QUESTION_ASSIGNED = "QUESTION_ASSIGNED"
    QUESTION_CREATED = "QUESTION_CREATED"
    ANSWER_REVIEW_REQUIRED = "ANSWER_REVIEW_REQUIRED"
    ANSWER_REVIEWED = "ANSWER_REVIEWED"
    ANSWER_ATTACHMENT_REJECTED = "ANSWER_ATTACHMENT_REJECTED"


class ContributorCandidate(BaseModel):
    display_name: str = Field(min_length=2, max_length=240)
    relationship: str = Field(min_length=2, max_length=500)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str = Field(min_length=2, max_length=1000)

    @field_validator("display_name", "relationship", "evidence")
    @classmethod
    def strip_candidate_text(cls, value: str) -> str:
        return value.strip()


class DocumentEnhancementResult(BaseModel):
    markdown: str = Field(min_length=1, max_length=500_000)
    contributors: list[ContributorCandidate] = Field(
        default_factory=list[ContributorCandidate],
        max_length=100,
    )
    blend360_emails: list[str] = Field(
        default_factory=list[str],
        max_length=100,
    )

    @field_validator("markdown")
    @classmethod
    def strip_markdown(cls, value: str) -> str:
        return value.strip()


class ContributorExtractionResult(BaseModel):
    contributors: list[ContributorCandidate] = Field(
        default_factory=list[ContributorCandidate],
        max_length=100,
    )
    blend360_emails: list[str] = Field(
        default_factory=list[str],
        max_length=100,
    )


class NameMatchDecision(StrEnum):
    MATCH = "MATCH"
    NO_MATCH = "NO_MATCH"
    UNCERTAIN = "UNCERTAIN"


class NameMatchResult(BaseModel):
    decision: NameMatchDecision
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=1000)


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


class ProjectRename(BaseModel):
    name: str = Field(min_length=2, max_length=200)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("Project name must contain at least 2 characters")
        return normalized


class CollaboratorInviteCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return normalize_blend_email(value)


class InvitationDecisionRequest(BaseModel):
    decision: Literal["accept", "decline"]


class HumanAnswerReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("note")
    @classmethod
    def strip_review_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class UploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=240)
    content_type: str = Field(min_length=1, max_length=120)
    size_bytes: int = Field(gt=0, le=100 * 1024 * 1024)
    request_id: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )


class DossierRenderRequest(BaseModel):
    markdown: str = Field(min_length=1, max_length=200_000)
    filename_stem: str | None = Field(default=None, max_length=96)
    request_id: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )

    @field_validator("markdown")
    @classmethod
    def normalize_markdown(cls, value: str) -> str:
        normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            raise ValueError("Dossier Markdown cannot be empty")
        return normalized

    @field_validator("filename_stem")
    @classmethod
    def normalize_filename_stem(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=4000)
    top_k: int = Field(default=8, ge=1, le=25)


class KnowledgeGapCreate(BaseModel):
    question: str = Field(min_length=5, max_length=4000)
    assigned_expert_email: str | None = Field(
        default=None,
        min_length=3,
        max_length=320,
    )
    context: str | None = Field(default=None, max_length=8000)
    priority: Literal["low", "normal", "high"] = "normal"

    @field_validator("assigned_expert_email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_email(value)


class AnswerSubmit(BaseModel):
    answer: str = Field(default="", max_length=20_000)
    supporting_document_ids: list[str] = Field(
        default_factory=list[str],
        max_length=10,
    )
    request_id: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )

    @field_validator("answer")
    @classmethod
    def strip_answer(cls, value: str) -> str:
        return value.strip()

    @field_validator("supporting_document_ids")
    @classmethod
    def normalize_supporting_document_ids(
        cls,
        value: list[str],
    ) -> list[str]:
        normalized = [document_id.strip() for document_id in value]
        if any(not document_id for document_id in normalized):
            raise ValueError("Supporting document IDs cannot be blank")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Supporting document IDs must be unique")
        return normalized

    @model_validator(mode="after")
    def require_answer_or_document(self) -> AnswerSubmit:
        if len(self.answer) < 3 and not self.supporting_document_ids:
            raise ValueError(
                "Provide an answer of at least 3 characters or a supporting document"
            )
        return self


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
