from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from app.application import UploadSession
from knowledge_core.models import (
    GlobalSearchResponse,
    SearchHit,
    SearchResponse,
)

_PREVIEW_CHARACTERS = 1_600
_INSUFFICIENT_EVIDENCE_ACTION = (
    "If opened sources do not answer the project-specific question, do not "
    "stop after reporting the gap. Before responding, call get_project and "
    "list_project_collaborators for the relevant project, suggest the verified "
    "author first and then other verified collaborators, and offer to draft a "
    "question. Do not send anything without explicit user confirmation."
)


class McpModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class McpCurrentUser(McpModel):
    subject: str
    email: str
    groups: list[str]
    is_admin: bool
    profile: dict[str, Any] | None = None


class McpDirectoryUser(McpModel):
    display_name: str
    email: str
    identity_source: str
    match_type: Literal[
        "EXACT_EMAIL",
        "EXACT_NAME",
        "NAME_TOKENS",
        "NAME_OR_EMAIL_TOKENS",
    ]


class McpProject(McpModel):
    project_id: str
    name: str
    description: str | None = None
    status: str = "ACTIVE"
    author_display_name: str | None = Field(
        default=None,
        description=(
            "Verified display name of the project author and preferred first "
            "expert to suggest when project evidence is insufficient."
        ),
    )
    author_email: str | None = Field(
        default=None,
        description=(
            "Verified project-author email. Sending a question still requires "
            "explicit user confirmation."
        ),
    )
    my_role: str
    can_edit: bool = Field(
        description=(
            "Whether the current user may modify project content. This does "
            "not control permission to ask or answer questions."
        )
    )
    can_ask_questions: bool = Field(
        description=(
            "Whether the current user may create project questions. This is "
            "true for every authenticated reader of an active project."
        )
    )
    can_answer_questions: bool = Field(
        description=(
            "Whether the current user may submit answers. Non-collaborator "
            "answers are routed through member review."
        )
    )
    can_archive: bool
    upload_page_url: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class McpCollaborator(McpModel):
    project_id: str
    email: str
    display_name: str | None = None
    email_verified: bool = Field(
        default=False,
        description=(
            "Whether this project member is a registered verified user who "
            "may be suggested as a question answerer."
        ),
    )
    role: str
    source: str
    created_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class McpCollaborationInvitation(McpModel):
    invitation_id: str
    project_id: str
    email: str
    source: str
    status: str
    invited_by: str | None = None
    decided_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class McpNotification(McpModel):
    notification_id: str
    email: str
    kind: str
    title: str
    message: str
    project_id: str | None = None
    action_url: str | None = None
    read_at: str | None = None
    email_status: str | None = None
    data: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None


class McpDocumentSummary(McpModel):
    project_id: str
    document_id: str
    document_name: str
    document_version: str
    status: str
    source_type: str
    content_type: str | None = None
    size_bytes: int | None = None
    markdown_available: bool
    page_count: int | None = None
    error: str | None = None
    next_action: str
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_record(
        cls,
        document: Mapping[str, Any],
    ) -> McpDocumentSummary:
        status = str(document["status"])
        if status == "READY":
            next_action = "Search or read this document."
        elif status == "FAILED":
            next_action = "Report the ingestion failure to a project member."
        else:
            next_action = "Poll get_document until status is READY or FAILED."
        return cls.model_validate(
            {
                **document,
                "markdown_available": bool(document.get("enhanced_s3_key")),
                "next_action": next_action,
            }
        )


class McpDocumentUpload(McpModel):
    document: McpDocumentSummary
    upload_method: Literal["POST"] = "POST"
    upload_url: str
    fields: dict[str, str]
    expires_in_seconds: int
    fallback_url: str
    max_upload_bytes: int
    supported_extensions: list[str]
    upload_required: bool
    next_action: str

    @classmethod
    def from_session(cls, session: UploadSession) -> McpDocumentUpload:
        return cls(
            document=McpDocumentSummary.from_record(session.document),
            upload_url=session.upload_url,
            fields=session.fields,
            expires_in_seconds=session.expires_in_seconds,
            fallback_url=session.fallback_url,
            max_upload_bytes=session.max_upload_bytes,
            supported_extensions=list(session.supported_extensions),
            upload_required=session.upload_required,
            next_action=(
                (
                    "If the client can upload a local file, POST it directly "
                    "to upload_url with every returned field. Otherwise open "
                    "fallback_url for the authenticated browser uploader. "
                )
                if session.upload_required
                else (
                    "Do not upload the file again: this idempotent request "
                    "already reached ingestion. "
                )
            )
            + ("Poll get_document until status is READY or FAILED."),
        )


class McpSearchHit(McpModel):
    project_id: str
    document_id: str
    document_name: str
    source_type: str | None = None
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
            project_id=hit.project_id,
            document_id=hit.document_id,
            document_name=hit.document_name,
            source_type=hit.source_type,
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


class McpSearchResponse(McpModel):
    project_id: str | None = None
    query: str
    hits: list[McpSearchHit]
    warnings: list[str]
    score_note: str
    insufficient_evidence_action: str = Field(
        default=_INSUFFICIENT_EVIDENCE_ACTION,
        description=(
            "Mandatory handoff when opened project sources cannot answer the "
            "question."
        ),
    )

    @classmethod
    def from_search(
        cls,
        response: SearchResponse | GlobalSearchResponse,
    ) -> McpSearchResponse:
        return cls(
            project_id=getattr(response, "project_id", None),
            query=response.query,
            hits=[McpSearchHit.from_hit(hit) for hit in response.hits],
            warnings=[_safe_warning(warning) for warning in response.warnings],
            score_note=response.score_note,
        )


class McpDocumentText(McpModel):
    project_id: str
    document_id: str
    document_name: str
    document_version: str
    status: str
    source_type: str
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
            page_count=(
                int(document["page_count"])
                if document.get("page_count") is not None
                else None
            ),
            text=text,
            content_hash=content_hash,
        )


class McpDocumentDownload(McpModel):
    project_id: str
    document_id: str
    document_name: str
    download_format: Literal["original", "markdown"]
    filename: str
    content_type: str
    url: str
    expires_in_seconds: int


class McpDossierRender(McpModel):
    project_id: str
    render_id: str
    title: str
    source_sha256: str
    docx_url: str
    pdf_url: str
    docx_filename: str
    pdf_filename: str
    expires_in_seconds: int
    reused_existing_render: bool
    next_action: str = (
        "Give the user both Relay download links. Explain that the links expire "
        "and rerun this tool with the same request_id to refresh them without "
        "creating another render."
    )


class McpWorkflowGuide(McpModel):
    workflow: Literal[
        "manage-project-knowledge",
        "create-project-dossier",
    ]
    purpose: str
    workflow_instructions: str
    bundled_reference: str | None = None
    content_sha256: str
    next_action: str


class McpDownloadArtifactManifest(McpModel):
    name: str
    description: str
    filename: str
    sha256: str


class McpSkillDownloadManifest(McpModel):
    version: str
    plugin_bundle: McpDownloadArtifactManifest
    skills: list[McpDownloadArtifactManifest]


class McpSkillDownload(McpDownloadArtifactManifest):
    url: str


class McpSkillDownloads(McpModel):
    version: str
    plugin_bundle: McpSkillDownload
    skills: list[McpSkillDownload]
    default_usage: str = (
        "Use Relay's MCP workflow tools by default. Install these archives "
        "only for portability, offline reference, or client compatibility."
    )
    next_action: str = (
        "Give the user only the download option relevant to their client. "
        "Do not claim an archive is installed unless the client confirms it."
    )


class McpVerifiedFact(McpModel):
    project_id: str
    fact_id: str
    name: str
    value: str
    provenance: str
    source_document_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class McpQuestion(McpModel):
    project_id: str
    project_name: str
    question_id: str
    question: str
    context: str | None = None
    assigned_expert_email: str | None = None
    priority: str
    status: str
    notification_status: str
    notification_error: str | None = None
    review_rationale: str | None = None
    latest_answer_id: str | None = None
    created_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class McpAnswerAttachment(McpModel):
    attachment_id: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    status: str
    document_id: str
    error: str | None = None


class McpAnswer(McpModel):
    project_id: str
    question_id: str
    answer_id: str
    answer: str
    answered_by: str
    answer_source: str
    review_status: str
    requires_human_review: bool
    supporting_document_ids: list[str] = Field(default_factory=list[str])
    attachments: list[McpAnswerAttachment] = Field(
        default_factory=list[McpAnswerAttachment]
    )
    human_reviewed_by: str | None = None
    human_review_note: str | None = None
    review_rationale: str | None = None
    missing_details: list[str] = Field(default_factory=list[str])
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


def optional_string(
    record: Mapping[str, Any],
    key: str,
) -> str | None:
    return cast(str | None, record.get(key))
