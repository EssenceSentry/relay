# FastMCP registers these nested callables through decorators.
# pyright: reportUnusedFunction=false

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from fastapi import HTTPException
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse

from app.document_downloads import (
    DocumentDownloadUnavailable,
    presign_document_download,
)
from app.mcp_models import (
    McpDocumentDownload,
    McpDocumentSummary,
    McpDocumentText,
    McpKnowledgeGap,
    McpProject,
    McpSearchResponse,
    McpVerifiedFact,
)
from app.mcp_oauth import MCP_SCOPE, CognitoMcpOAuthProvider
from app.services import ServiceContainer
from knowledge_core.ids import stable_action_id
from knowledge_core.models import KnowledgeGapCreate, VerifiedFactCreate

MCP_PUBLIC_PATH = "/mcp/"

ProjectId = Annotated[
    str,
    Field(min_length=1, max_length=128, description="Project identifier"),
]
DocumentId = Annotated[
    str,
    Field(min_length=1, max_length=128, description="Document identifier"),
]
DocumentDownloadFormat = Annotated[
    Literal["original", "markdown"],
    Field(
        description=(
            "Representation to download: original for the uploaded source file "
            "or markdown for the consolidated enhanced Markdown."
        )
    ),
]
QuestionId = Annotated[
    str,
    Field(min_length=1, max_length=128, description="Knowledge-gap identifier"),
]
RequestId = Annotated[
    str,
    Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
        description=(
            "Stable unique ID for this intended write. Reuse it when retrying "
            "the same action."
        ),
    ),
]
QueryText = Annotated[
    str,
    Field(min_length=2, max_length=4_000, description="Natural-language query"),
]
TopK = Annotated[
    int,
    Field(
        ge=1,
        le=25,
        description=(
            "Number of ranked results to return. Use 5 for focused lookup "
            "or 10-20 for broader dossier research."
        ),
    ),
]
QuestionText = Annotated[str, Field(min_length=5, max_length=4_000)]
ExpertEmail = Annotated[str, Field(min_length=3, max_length=320)]
GapContext = Annotated[str | None, Field(max_length=8_000)]
FactName = Annotated[str, Field(min_length=2, max_length=300)]
FactValue = Annotated[str, Field(min_length=1, max_length=8_000)]
FactProvenance = Annotated[str, Field(min_length=2, max_length=2_000)]
BriefProjectName = Annotated[
    str,
    Field(
        min_length=2,
        max_length=300,
        description="Project or case-study name to show in the sales brief",
    ),
]
BriefContext = Annotated[
    str | None,
    Field(
        max_length=4_000,
        description="Optional audience, opportunity, or emphasis from the user",
    ),
]

_READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
_EMAIL_CREATE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
    openWorldHint=True,
)
_EMAIL_RESEND = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=True,
)
_INTERNAL_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
_OAUTH_META = {
    "securitySchemes": [
        {
            "type": "oauth2",
            "scopes": [MCP_SCOPE],
        }
    ]
}
_NO_AUTH_META = {"securitySchemes": [{"type": "noauth"}]}
_SALES_BRIEF_PROMPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "participant_sales_brief_generation_prompt.md"
)


@lru_cache(maxsize=1)
def _sales_brief_prompt_template() -> str:
    return _SALES_BRIEF_PROMPT_PATH.read_text(encoding="utf-8").strip()


def _web_application_url(container: ServiceContainer) -> str | None:
    settings = getattr(container, "settings", None)
    configured = getattr(settings, "application_base_url", None) or getattr(
        settings, "mcp_public_base_url", None
    )
    if not configured:
        return None
    return str(configured).rstrip("/") + "/"


def _server_instructions(container: ServiceContainer) -> str:
    instructions = [
        (
            "Use this evidence-first workflow for project questions; do not "
            "answer from memory or general knowledge."
        ),
        (
            "1. If the exact project_id is unknown, call list_projects and "
            "select the matching project. Never invent an ID."
        ),
        (
            "2. Call search_knowledge with several focused queries covering "
            "the user's question. Use top_k=5 for a narrow lookup or "
            "top_k=10-20 for broad dossier research; the valid range is 1-25."
        ),
        (
            "3. Search results are previews, not complete evidence. Call "
            "get_document_text for the strongest relevant documents before "
            "making material claims. Use get_document_download_url only when "
            "the user or workflow needs a local file. Use "
            "list_project_documents to inventory sources or check whether "
            "ingestion is READY."
        ),
        (
            "4. Answer only from retrieved document text and verified facts. "
            "Cite the document name and page, slide, or locator when present. "
            "Retrieval scores rank evidence; they are not probabilities or "
            "proof that a claim is true."
        ),
        (
            "5. If multiple focused searches and the relevant complete "
            "documents still do not answer the question, explain the gap. "
            "Only then consider create_knowledge_gap instead of guessing."
        ),
        (
            "6. Before create_knowledge_gap or resend_knowledge_gap_email, get "
            "explicit user confirmation because these tools send external "
            "email. Before record_verified_fact, get explicit confirmation; "
            "never store an inference as a verified fact."
        ),
        (
            "For a participant sales brief, use the "
            "participant_sales_brief_generation prompt and follow its inline "
            "citation requirements."
        ),
    ]
    web_url = _web_application_url(container)
    if web_url is None:
        instructions.append(
            "This MCP cannot upload documents. When a user needs to add one, "
            "direct them to the deployment's web application."
        )
        return "\n".join(instructions)

    settings = getattr(container, "settings", None)
    max_upload_bytes = getattr(settings, "max_upload_bytes", None)
    limit = ""
    if isinstance(max_upload_bytes, int) and max_upload_bytes > 0:
        limit_mib = max_upload_bytes / (1024 * 1024)
        rendered_limit = (
            str(int(limit_mib))
            if limit_mib.is_integer()
            else f"{limit_mib:.1f}"
        )
        limit = f" The current per-file limit is {rendered_limit} MiB."
    instructions.append(
        "This MCP cannot upload documents. When a user asks to add, upload, "
        f"import, or ingest a document, direct them to {web_url} and tell "
        f"them to use the document upload area.{limit} After upload, use "
        "list_project_documents to check ingestion status."
    )
    return "\n".join(instructions)


def build_mcp_server(
    container: ServiceContainer,
    *,
    oauth_provider: CognitoMcpOAuthProvider | None = None,
    auth_settings: AuthSettings | None = None,
) -> FastMCP:
    tool_meta = _OAUTH_META if auth_settings is not None else _NO_AUTH_META
    web_url = _web_application_url(container)
    mcp = FastMCP(
        "Blend Project Knowledge",
        instructions=_server_instructions(container),
        website_url=web_url,
        host="0.0.0.0",
        auth_server_provider=oauth_provider,
        auth=auth_settings,
        stateless_http=True,
        json_response=True,
        streamable_http_path=MCP_PUBLIC_PATH,
    )

    @mcp.prompt(
        name="participant_sales_brief_generation",
        description=(
            "Research one PIH project and produce a concise, source-cited "
            "Blend360 sales brief in Markdown."
        ),
    )
    def participant_sales_brief_generation(
        project_id: ProjectId,
        project_name: BriefProjectName,
        additional_context: BriefContext = None,
    ) -> str:
        """Build the evidence-first PIH participant sales-brief prompt."""
        return (
            _sales_brief_prompt_template()
            .replace("[PROJECT_ID]", project_id)
            .replace("[PROJECT_NAME]", project_name)
            .replace(
                "[ADDITIONAL_CONTEXT]",
                additional_context or "None provided.",
            )
        )

    if oauth_provider is not None:

        @mcp.custom_route("/oauth/callback", methods=["GET"])
        async def oauth_callback(request: Request):
            error = request.query_params.get("error")
            if error:
                description = request.query_params.get(
                    "error_description",
                    "Cognito authorization was not completed.",
                )
                state = request.query_params.get("state")
                if state:
                    try:
                        redirect_url = (
                            oauth_provider.reject_cognito_authorization(
                                state=state,
                                error_description=description,
                            )
                        )
                    except ValueError:
                        pass
                    else:
                        return RedirectResponse(
                            redirect_url,
                            status_code=302,
                        )
                return PlainTextResponse(
                    f"Authorization failed: {description}",
                    status_code=400,
                )
            state = request.query_params.get("state")
            code = request.query_params.get("code")
            if not state or not code:
                return PlainTextResponse(
                    "Authorization callback is missing state or code.",
                    status_code=400,
                )
            try:
                redirect_url = (
                    await oauth_provider.complete_cognito_authorization(
                        state=state,
                        code=code,
                    )
                )
            except (HTTPException, ValueError):
                return PlainTextResponse(
                    "Authorization could not be completed. Start the "
                    "connection again.",
                    status_code=400,
                )
            return RedirectResponse(redirect_url, status_code=302)

    @mcp.tool(annotations=_READ_ONLY, meta=tool_meta)
    def list_projects() -> list[McpProject]:
        """Discover valid project IDs and project names.

        Call this first when the user has not provided an exact project_id.
        Match by project name or description; never invent a project ID.
        """
        return [
            McpProject.model_validate(project)
            for project in container.repository.list_projects()
        ]

    @mcp.tool(annotations=_READ_ONLY, meta=tool_meta)
    def search_knowledge(
        project_id: ProjectId,
        query: QueryText,
        top_k: TopK = 5,
    ) -> McpSearchResponse:
        """Find evidence in one project and return ranked document previews.

        Use multiple focused queries for different aspects of a broad question.
        Use top_k=5 for focused lookup or 10-20 for broad dossier research.
        Results contain previews only: call get_document_text for the strongest
        relevant documents before making material claims. Scores rank results
        but are not calibrated probabilities or proof of a claim.
        """
        container.repository.require_project(project_id)
        response = container.retrieval.search(
            project_id=project_id,
            query=query,
            top_k=top_k,
        )
        return McpSearchResponse.from_search(response)

    @mcp.tool(annotations=_READ_ONLY, meta=tool_meta)
    def list_project_documents(
        project_id: ProjectId,
    ) -> list[McpDocumentSummary]:
        """Inventory a project's documents and inspect ingestion status.

        Use this to discover available sources or verify that documents are
        READY. markdown_available tells you whether the consolidated Markdown
        can be downloaded. This does not return document contents; use
        search_knowledge to find relevance and get_document_text to read
        evidence.
        """
        container.repository.require_project(project_id)
        return [
            McpDocumentSummary.from_record(document)
            for document in container.repository.list_documents(project_id)
        ]

    @mcp.tool(annotations=_READ_ONLY, meta=tool_meta)
    def get_document_text(
        project_id: ProjectId,
        document_id: DocumentId,
    ) -> McpDocumentText:
        """Read the complete indexed text of a relevant document.

        Call this with a document_id returned by search_knowledge before
        relying on a preview for material claims. Preserve the returned
        document name and page or locator metadata in source citations.
        """
        document = container.repository.get_document(
            project_id=project_id,
            document_id=document_id,
        )
        if document is None:
            raise ValueError(f"Unknown document: {document_id}")
        indexed_documents = container.search.get_indexed_documents(
            project_id=project_id,
            document_id=document_id,
            size=1000,
        )
        return McpDocumentText.from_records(
            document=document,
            indexed_documents=indexed_documents,
        )

    @mcp.tool(annotations=_READ_ONLY, meta=tool_meta)
    def get_document_download_url(
        project_id: ProjectId,
        document_id: DocumentId,
        download_format: DocumentDownloadFormat = "original",
    ) -> McpDocumentDownload:
        """Get a time-limited URL for a document file.

        Use original when the exact uploaded source is needed. Use markdown
        for the consolidated cleaned and enhanced Markdown generated during
        ingestion. This tool returns a download URL rather than document text;
        use get_document_text when the agent only needs to read evidence.
        """
        document = container.repository.get_document(
            project_id=project_id,
            document_id=document_id,
        )
        if document is None:
            raise ValueError(f"Unknown document: {document_id}")
        try:
            download = presign_document_download(
                s3=container.s3,
                document=document,
                download_format=download_format,
            )
        except DocumentDownloadUnavailable as exc:
            raise ValueError(str(exc)) from exc
        return McpDocumentDownload(
            project_id=project_id,
            document_id=document_id,
            document_name=str(document["document_name"]),
            download_format=download.download_format,
            filename=download.filename,
            content_type=download.content_type,
            url=download.url,
            expires_in_seconds=download.expires_in_seconds,
        )

    @mcp.tool(annotations=_READ_ONLY, meta=tool_meta)
    def list_verified_facts(project_id: ProjectId) -> list[McpVerifiedFact]:
        """List explicitly verified facts and their provenance.

        Use these as authoritative project context, but retain the provenance
        in the answer and prefer document evidence when a source is available.
        """
        container.repository.require_project(project_id)
        return [
            McpVerifiedFact.model_validate(fact)
            for fact in container.repository.list_verified_facts(project_id)
        ]

    @mcp.tool(annotations=_EMAIL_CREATE, meta=tool_meta)
    def create_knowledge_gap(
        project_id: ProjectId,
        question: QuestionText,
        assigned_expert_email: ExpertEmail,
        request_id: RequestId,
        context: GapContext = None,
        priority: Literal["low", "normal", "high"] = "normal",
    ) -> McpKnowledgeGap:
        """Record missing knowledge and immediately email the assigned expert.

        Use only after several focused searches and relevant complete documents
        still leave a material gap. Explain that gap to the user, then get
        explicit confirmation for the recipient, question, and context before
        calling because this sends external email. Reuse request_id when
        retrying the same intended action.
        """
        question_id = stable_action_id(
            prefix="gap",
            project_id=project_id,
            request_id=request_id,
        )
        existing = container.repository.get_question(
            project_id=project_id,
            question_id=question_id,
        )
        if existing is not None:
            return McpKnowledgeGap.model_validate(existing)
        gap = KnowledgeGapCreate(
            question=question,
            assigned_expert_email=assigned_expert_email,
            context=context,
            priority=priority,
        )
        created = container.questions.create_question(
            project_id=project_id,
            gap=gap,
            created_by="mcp-agent",
            question_id=question_id,
        )
        return McpKnowledgeGap.model_validate(created)

    @mcp.tool(annotations=_EMAIL_RESEND, meta=tool_meta)
    def resend_knowledge_gap_email(
        project_id: ProjectId,
        question_id: QuestionId,
    ) -> McpKnowledgeGap:
        """Resend an existing knowledge-gap email.

        First use get_knowledge_gap to inspect status. Resend only when the user
        explicitly asks or confirms it, because this contacts an external
        recipient. Do not resend a resolved gap.
        """
        return McpKnowledgeGap.model_validate(
            container.questions.resend_question(
                project_id=project_id,
                question_id=question_id,
            )
        )

    @mcp.tool(annotations=_READ_ONLY, meta=tool_meta)
    def get_knowledge_gap(
        project_id: ProjectId,
        question_id: QuestionId,
    ) -> McpKnowledgeGap:
        """Check one knowledge gap's status and notification outcome.

        Use this to report whether a question is open, needs more information,
        or is resolved. Reading status does not resend the email.
        """
        question = container.repository.get_question(
            project_id=project_id,
            question_id=question_id,
        )
        if question is None:
            raise ValueError(f"Unknown knowledge gap: {question_id}")
        return McpKnowledgeGap.model_validate(question)

    @mcp.tool(annotations=_INTERNAL_WRITE, meta=tool_meta)
    def record_verified_fact(
        project_id: ProjectId,
        name: FactName,
        value: FactValue,
        provenance: FactProvenance,
        request_id: RequestId,
    ) -> McpVerifiedFact:
        """Store an explicitly verified fact with human-readable provenance.

        Use only for information explicitly confirmed as authoritative by the
        user or a named expert. Get user confirmation first, include meaningful
        provenance, and never promote an inference or unverified search result.
        This is not a substitute for retrieval. Reuse request_id when retrying
        the same intended action.
        """
        fact_id = stable_action_id(
            prefix="fact",
            project_id=project_id,
            request_id=request_id,
        )
        existing = container.repository.get_verified_fact(
            project_id=project_id,
            fact_id=fact_id,
        )
        if existing is not None:
            return McpVerifiedFact.model_validate(existing)
        stored = container.repository.put_verified_fact(
            project_id=project_id,
            fact_id=fact_id,
            fact=VerifiedFactCreate(
                name=name,
                value=value,
                provenance=provenance,
            ),
            created_by="mcp-agent",
        )
        return McpVerifiedFact.model_validate(stored)

    return mcp


def build_mcp_asgi_app(mcp: FastMCP):
    return mcp.streamable_http_app()
