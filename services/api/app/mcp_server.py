# FastMCP registers these nested callables through decorators.
# pyright: reportUnusedFunction=false

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import asdict
from functools import cache, lru_cache
from pathlib import Path
from typing import Annotated, Literal

from fastapi import HTTPException
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter, ValidationError
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse

from app.application import ApplicationError, KnowledgeApplication
from app.auth import Principal, with_configured_admin
from app.mcp_models import (
    McpAnswer,
    McpCollaborationInvitation,
    McpCollaborator,
    McpCurrentUser,
    McpDirectoryUser,
    McpDocumentDownload,
    McpDocumentSummary,
    McpDocumentText,
    McpDocumentUpload,
    McpDossierRender,
    McpDownloadArtifactManifest,
    McpNotification,
    McpProject,
    McpQuestion,
    McpSearchResponse,
    McpSkillDownload,
    McpSkillDownloadManifest,
    McpSkillDownloads,
    McpVerifiedFact,
    McpWorkflowGuide,
)
from app.mcp_oauth import MCP_SCOPE, CognitoMcpOAuthProvider
from app.services import ServiceContainer
from knowledge_core.ids import stable_action_id
from knowledge_core.models import (
    AnswerSubmit,
    CollaboratorInviteCreate,
    DossierRenderRequest,
    HumanAnswerReviewRequest,
    InvitationDecisionRequest,
    KnowledgeGapCreate,
    ProjectCreate,
    ProjectRename,
    SearchRequest,
    UploadRequest,
    VerifiedFactCreate,
)

MCP_PUBLIC_PATH = "/mcp/"

ProjectId = Annotated[
    str,
    Field(min_length=1, max_length=128, description="Exact project identifier"),
]
DocumentId = Annotated[
    str,
    Field(
        min_length=1, max_length=128, description="Exact document identifier"
    ),
]
QuestionId = Annotated[
    str,
    Field(
        min_length=1, max_length=128, description="Exact question identifier"
    ),
]
AnswerId = Annotated[
    str,
    Field(min_length=1, max_length=128, description="Exact answer identifier"),
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
DirectoryQuery = Annotated[
    str,
    Field(
        min_length=2,
        max_length=200,
        description="Person's name or exact known email address",
    ),
]
DirectoryLimit = Annotated[int, Field(ge=1, le=10)]
TopK = Annotated[
    int,
    Field(
        ge=1,
        le=25,
        description=(
            "Number of ranked results. Use 5 for focused lookup or 10-20 for "
            "broad dossier research."
        ),
    ),
]
ProjectName = Annotated[str, Field(min_length=2, max_length=200)]
ProjectDescription = Annotated[str | None, Field(max_length=2_000)]
Email = Annotated[str, Field(min_length=3, max_length=320)]
NotificationId = Annotated[str, Field(min_length=1, max_length=160)]
InvitationId = Annotated[str, Field(min_length=1, max_length=160)]
Filename = Annotated[str, Field(min_length=1, max_length=240)]
ContentType = Annotated[str, Field(min_length=1, max_length=120)]
FileSize = Annotated[int, Field(gt=0, le=100 * 1024 * 1024)]
QuestionText = Annotated[str, Field(min_length=5, max_length=4_000)]
AnswerText = Annotated[str, Field(max_length=20_000)]
SupportingDocumentIds = Annotated[
    list[str],
    Field(max_length=10),
]
QuestionContext = Annotated[str | None, Field(max_length=8_000)]
ReviewNote = Annotated[str | None, Field(max_length=2_000)]
FactName = Annotated[str, Field(min_length=2, max_length=300)]
FactValue = Annotated[str, Field(min_length=1, max_length=8_000)]
FactProvenance = Annotated[str, Field(min_length=2, max_length=2_000)]
BriefProjectName = Annotated[str, Field(min_length=2, max_length=300)]
BriefContext = Annotated[str | None, Field(max_length=4_000)]
DownloadFormat = Annotated[Literal["original", "markdown"], Field()]
DossierMarkdown = Annotated[
    str,
    Field(
        min_length=1,
        max_length=200_000,
        description=(
            "Complete final dossier Markdown following the Relay dossier "
            "section contract, including inline source citations"
        ),
    ),
]
DossierFilenameStem = Annotated[
    str | None,
    Field(
        max_length=96,
        description="Optional human-readable filename without an extension",
    ),
]

_READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
_INTERNAL_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
_EXTERNAL_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)
_DESTRUCTIVE_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
    openWorldHint=False,
)
_DESTRUCTIVE_EXTERNAL_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
    openWorldHint=True,
)
_OAUTH_META = {"securitySchemes": [{"type": "oauth2", "scopes": [MCP_SCOPE]}]}
_TEST_META = {"securitySchemes": [{"type": "noauth"}]}
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_SALES_BRIEF_PROMPT_PATH = (
    _REPOSITORY_ROOT / "participant_sales_brief_generation_prompt.md"
)
_RELAY_SKILLS_ROOT = _REPOSITORY_ROOT / "plugins" / "relay" / "skills"
_PROJECT_KNOWLEDGE_SKILL_PATH = (
    _RELAY_SKILLS_ROOT / "manage-project-knowledge" / "SKILL.md"
)
_DOSSIER_SKILL_PATH = _RELAY_SKILLS_ROOT / "create-project-dossier" / "SKILL.md"
_DOSSIER_FORMAT_PATH = (
    _RELAY_SKILLS_ROOT
    / "create-project-dossier"
    / "references"
    / "dossier-format.md"
)
_DOWNLOAD_MANIFEST_PATH = (
    _REPOSITORY_ROOT / "frontend" / "downloads" / "relay-downloads.json"
)
_STRING_LIST_ADAPTER = TypeAdapter(list[str])


@lru_cache(maxsize=1)
def _sales_brief_prompt_template() -> str:
    return _SALES_BRIEF_PROMPT_PATH.read_text(encoding="utf-8").strip()


@cache
def _markdown_body(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if not text.startswith("---\n"):
        return text
    _, separator, body = text[4:].partition("\n---\n")
    if not separator:
        raise ValueError(f"Invalid skill frontmatter in {path.name}")
    return body.strip()


def _workflow_guide(
    *,
    workflow: Literal[
        "manage-project-knowledge",
        "create-project-dossier",
    ],
    purpose: str,
    skill_path: Path,
    bundled_reference_path: Path | None,
    next_action: str,
) -> McpWorkflowGuide:
    instructions = _markdown_body(skill_path)
    bundled_reference = (
        _markdown_body(bundled_reference_path)
        if bundled_reference_path is not None
        else None
    )
    hash_input = instructions
    if bundled_reference is not None:
        hash_input += f"\n\n{bundled_reference}"
    return McpWorkflowGuide(
        workflow=workflow,
        purpose=purpose,
        workflow_instructions=instructions,
        bundled_reference=bundled_reference,
        content_sha256=hashlib.sha256(hash_input.encode("utf-8")).hexdigest(),
        next_action=next_action,
    )


@lru_cache(maxsize=1)
def _skill_download_manifest() -> McpSkillDownloadManifest:
    return McpSkillDownloadManifest.model_validate_json(
        _DOWNLOAD_MANIFEST_PATH.read_text(encoding="utf-8")
    )


def _skill_download(
    artifact: McpDownloadArtifactManifest,
    *,
    base_url: str,
) -> McpSkillDownload:
    return McpSkillDownload(
        **artifact.model_dump(),
        url=f"{base_url}downloads/{artifact.filename}",
    )


def _web_application_url(container: ServiceContainer) -> str | None:
    settings = getattr(container, "settings", None)
    configured = getattr(settings, "application_base_url", None) or getattr(
        settings, "mcp_public_base_url", None
    )
    if not configured:
        return None
    return str(configured).rstrip("/") + "/"


def _server_instructions(container: ServiceContainer) -> str:
    web_url = _web_application_url(container) or "the deployment website"
    return "\n".join(
        [
            "Use Relay as the source of truth for project work.",
            (
                "1. Before a substantial project operation, call "
                "get_project_knowledge_workflow and apply its current "
                "instructions. Before researching or drafting a dossier, "
                "sales brief, success story, capability story, or case study, "
                "call get_project_dossier_template and treat its workflow and "
                "bundled format as binding."
            ),
            (
                "2. Call get_current_user when permissions matter. If an exact "
                "project_id is unknown, locate it through search_all_projects; "
                "never invent an ID."
            ),
            (
                "3. For evidence questions, begin with several focused "
                "search_all_projects queries. Open material hits with "
                "get_document_text, then use search_project_knowledge only to "
                "deepen or disambiguate a likely project."
            ),
            (
                "4. Cite document name plus page, slide, or locator. Treat "
                "retrieval scores as ranking signals, not proof."
            ),
            (
                "5. Do not list projects, enumerate project documents, and "
                "read everything as a retrieval strategy. Use list_projects "
                "and list_project_documents for explicit inventory, "
                "administration, status checks, or only as a last resort "
                "after search fails."
            ),
            (
                "6. For uploads, call prepare_document_upload only when the "
                "client can send a local file to the returned presigned S3 "
                "POST. Otherwise direct the user to its fallback_url. Poll "
                "get_document until READY or FAILED."
            ),
            (
                "7. Use list_my_notifications, "
                "list_my_collaboration_invitations, and "
                "list_my_assigned_questions for inbox work. Inspect a question "
                "and its answers before responding or reviewing."
            ),
            (
                "8. Every authenticated reader may create and answer project "
                "questions. can_edit=false limits project content changes; it "
                "does not prevent create_project_question. Non-collaborator "
                "answers require member review."
            ),
            (
                "9. When a requested answerer is named but no exact email is "
                "known, call search_user_directory. Use only a unique match; "
                "ask the user to disambiguate multiple results and never "
                "construct an address from a name."
            ),
            (
                "10. Get explicit user confirmation before sending email, "
                "inviting or removing collaborators, archiving a project, "
                "rejecting an answer, or creating a verified fact. Never store "
                "an inference as verified fact."
            ),
            (
                "11. When project-specific evidence remains insufficient after "
                "retrieval, do not stop after reporting the gap. Before "
                "responding, you MUST call get_project and "
                "list_project_collaborators for the relevant project. State "
                "what is missing, suggest the verified project author first "
                "using author_display_name and author_email, suggest other "
                "project members only when email_verified is true, and offer "
                "to draft a question for the user's approval. If no unique "
                "project is known, ask the user to identify it. These people "
                "are suggestions only: do not call create_project_question "
                "until the user confirms the exact recipient and question. "
                "Reuse request_id when retrying any write."
            ),
            (
                "12. For a finished project dossier, follow the workflow and "
                "inline-citation contract returned by "
                "get_project_dossier_template, then call "
                "render_project_dossier with the complete final Markdown. "
                "Return both expiring DOCX and PDF links."
            ),
            (
                "For participant sales briefs, use the "
                "participant_sales_brief_generation prompt and follow every "
                "inline citation requirement."
            ),
            (
                "Dynamic MCP workflow guidance is the default. Call "
                "get_relay_skill_downloads only when the user asks about "
                "installation, portability, offline use, or compatibility, or "
                "when the client cannot use the dynamic workflow tools. Do not "
                "advertise downloads during ordinary Relay work or claim that "
                "a skill was installed without client confirmation."
            ),
            f"Connection and browser-upload fallback: {web_url}",
        ]
    )


def build_mcp_server(
    container: ServiceContainer,
    *,
    oauth_provider: CognitoMcpOAuthProvider | None = None,
    auth_settings: AuthSettings | None = None,
) -> FastMCP:
    tool_meta = _OAUTH_META if auth_settings is not None else _TEST_META
    application = KnowledgeApplication(container)
    mcp = FastMCP(
        "Relay",
        instructions=_server_instructions(container),
        website_url=_web_application_url(container),
        host="0.0.0.0",
        auth_server_provider=oauth_provider,
        auth=auth_settings,
        stateless_http=True,
        json_response=True,
        streamable_http_path=MCP_PUBLIC_PATH,
    )

    def current_principal() -> Principal:
        access_token = get_access_token()
        if access_token is None:
            if auth_settings is not None:
                raise ValueError(
                    "This operation requires an authenticated Blend360 user"
                )
            return Principal(
                subject="local-test-user",
                email="local.test@blend360.com",
                groups=frozenset(),
                claims={"authentication_mode": "test"},
            )
        claims = access_token.claims or {}
        groups: frozenset[str]
        try:
            groups = frozenset(
                _STRING_LIST_ADAPTER.validate_python(
                    claims.get("groups") or [],
                    strict=True,
                )
            )
        except ValidationError:
            groups = frozenset()
        return with_configured_admin(
            Principal(
                subject=str(access_token.subject or ""),
                email=str(claims.get("email") or "").strip().casefold(),
                groups=groups,
                claims=dict(claims),
            ),
            container.settings.initial_admin_emails,
        )

    def call[T](operation: Callable[[], T]) -> T:
        try:
            return operation()
        except ApplicationError as exc:
            raise ValueError(str(exc)) from exc

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
        return (
            _sales_brief_prompt_template()
            .replace("[PROJECT_ID]", project_id)
            .replace("[PROJECT_NAME]", project_name)
            .replace(
                "[ADDITIONAL_CONTEXT]",
                additional_context or "None provided.",
            )
        )

    @mcp.tool(annotations=_READ_ONLY, meta=tool_meta)
    def get_project_knowledge_workflow() -> McpWorkflowGuide:
        """Call before substantial Relay project operations.

        Returns the current project, collaboration, retrieval, upload, fact,
        inbox, question, answer, and safety workflow without requiring a
        locally installed skill.
        """
        return _workflow_guide(
            workflow="manage-project-knowledge",
            purpose=(
                "Manage Relay project knowledge safely through the remote MCP."
            ),
            skill_path=_PROJECT_KNOWLEDGE_SKILL_PATH,
            bundled_reference_path=None,
            next_action=(
                "Apply these instructions to the current Relay task, then use "
                "the narrowest relevant project tools."
            ),
        )

    @mcp.tool(annotations=_READ_ONLY, meta=tool_meta)
    def get_project_dossier_template() -> McpWorkflowGuide:
        """Call before researching or drafting a Relay project artifact.

        Returns the evidence-first dossier workflow plus the complete required
        Markdown structure, inline-citation contract, style rules, and render
        handoff for dossiers, sales briefs, success stories, capability stories,
        and case studies.
        """
        return _workflow_guide(
            workflow="create-project-dossier",
            purpose=(
                "Create a source-cited Relay project dossier or related "
                "business-facing artifact."
            ),
            skill_path=_DOSSIER_SKILL_PATH,
            bundled_reference_path=_DOSSIER_FORMAT_PATH,
            next_action=(
                "Treat both workflow_instructions and bundled_reference as the "
                "binding contract, then begin focused Relay evidence research."
            ),
        )

    @mcp.tool(annotations=_READ_ONLY, meta=tool_meta)
    def get_relay_skill_downloads() -> McpSkillDownloads:
        """Return optional Relay skill ZIPs and the full plugin bundle.

        Use only when the user asks about installation, portability, offline
        use, or client compatibility, or when dynamic MCP workflow retrieval is
        unavailable. Ordinary Relay work should use the workflow tools instead.
        """
        base_url = _web_application_url(container)
        if base_url is None:
            raise ValueError("Relay skill download URLs are not configured")
        manifest = _skill_download_manifest()
        return McpSkillDownloads(
            version=manifest.version,
            plugin_bundle=_skill_download(
                manifest.plugin_bundle,
                base_url=base_url,
            ),
            skills=[
                _skill_download(artifact, base_url=base_url)
                for artifact in manifest.skills
            ],
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
                        return RedirectResponse(redirect_url, status_code=302)
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
    def get_current_user() -> McpCurrentUser:
        """Return the authenticated identity and administrator status."""
        return McpCurrentUser.model_validate(
            call(lambda: application.get_current_user(current_principal()))
        )

    @mcp.tool(annotations=_READ_ONLY, meta=tool_meta)
    def search_user_directory(
        query: DirectoryQuery,
        limit: DirectoryLimit = 8,
    ) -> list[McpDirectoryUser]:
        """Resolve a person's name to verified users before targeting email."""
        return [
            McpDirectoryUser.model_validate(item)
            for item in call(
                lambda: application.search_user_directory(
                    query,
                    principal=current_principal(),
                    limit=limit,
                )
            )
        ]

    @mcp.tool(annotations=_READ_ONLY, meta=tool_meta)
    def list_projects(
        include_archived: bool = False,
    ) -> list[McpProject]:
        """List real project IDs, names, access roles, and allowed actions."""
        return [
            McpProject.model_validate(item)
            for item in call(
                lambda: application.list_projects(
                    principal=current_principal(),
                    include_archived=include_archived,
                )
            )
        ]

    @mcp.tool(annotations=_READ_ONLY, meta=tool_meta)
    def get_project(project_id: ProjectId) -> McpProject:
        """Get one project and the current user's capabilities for it."""
        return McpProject.model_validate(
            call(
                lambda: application.get_project(
                    project_id,
                    principal=current_principal(),
                )
            )
        )

    @mcp.tool(annotations=_INTERNAL_WRITE, meta=tool_meta)
    def create_project(
        name: ProjectName,
        request_id: RequestId,
        description: ProjectDescription = None,
    ) -> McpProject:
        """Create a project and make the current user its author."""
        return McpProject.model_validate(
            call(
                lambda: application.create_project(
                    ProjectCreate(name=name, description=description),
                    principal=current_principal(),
                    request_id=request_id,
                )
            )
        )

    @mcp.tool(annotations=_INTERNAL_WRITE, meta=tool_meta)
    def rename_project(
        project_id: ProjectId,
        name: ProjectName,
    ) -> McpProject:
        """Rename a project without changing its ID or documents."""
        return McpProject.model_validate(
            call(
                lambda: application.rename_project(
                    project_id,
                    ProjectRename(name=name),
                    principal=current_principal(),
                )
            )
        )

    @mcp.tool(annotations=_DESTRUCTIVE_WRITE, meta=tool_meta)
    def archive_project(project_id: ProjectId) -> McpProject:
        """Archive a project. Confirm explicitly; only admins may call this."""
        return McpProject.model_validate(
            call(
                lambda: application.set_project_archived(
                    project_id,
                    archived=True,
                    principal=current_principal(),
                )
            )
        )

    @mcp.tool(annotations=_INTERNAL_WRITE, meta=tool_meta)
    def restore_project(project_id: ProjectId) -> McpProject:
        """Restore an archived project; only admins may call this."""
        return McpProject.model_validate(
            call(
                lambda: application.set_project_archived(
                    project_id,
                    archived=False,
                    principal=current_principal(),
                )
            )
        )

    @mcp.tool(annotations=_READ_ONLY, meta=tool_meta)
    def list_project_collaborators(
        project_id: ProjectId,
    ) -> list[McpCollaborator]:
        """List project authors and collaborators with membership sources."""
        return [
            McpCollaborator.model_validate(item)
            for item in call(
                lambda: application.list_project_collaborators(
                    project_id,
                    principal=current_principal(),
                )
            )
        ]

    @mcp.tool(annotations=_EXTERNAL_WRITE, meta=tool_meta)
    def invite_project_collaborator(
        project_id: ProjectId,
        email: Email,
        request_id: RequestId,
    ) -> McpCollaborationInvitation:
        """Invite a registered Blend employee; confirm because this emails them."""
        return McpCollaborationInvitation.model_validate(
            call(
                lambda: application.invite_project_collaborator(
                    project_id,
                    CollaboratorInviteCreate(email=email),
                    principal=current_principal(),
                    request_id=request_id,
                )
            )
        )

    @mcp.tool(annotations=_DESTRUCTIVE_WRITE, meta=tool_meta)
    def remove_project_collaborator(
        project_id: ProjectId,
        email: Email,
    ) -> McpCollaborator:
        """Remove a collaborator and preserve suppression; confirm first."""
        return McpCollaborator.model_validate(
            call(
                lambda: application.remove_project_collaborator(
                    project_id,
                    email,
                    principal=current_principal(),
                )
            )
        )

    @mcp.tool(annotations=_READ_ONLY, meta=tool_meta)
    def list_my_collaboration_invitations(
        include_decided: bool = False,
    ) -> list[McpCollaborationInvitation]:
        """List pending collaboration invitations for the current user."""
        return [
            McpCollaborationInvitation.model_validate(item)
            for item in call(
                lambda: application.list_my_collaboration_invitations(
                    principal=current_principal(),
                    include_decided=include_decided,
                )
            )
        ]

    @mcp.tool(annotations=_DESTRUCTIVE_WRITE, meta=tool_meta)
    def decide_collaboration_invitation(
        invitation_id: InvitationId,
        decision: Literal["accept", "decline"],
    ) -> McpCollaborationInvitation:
        """Accept or decline an invitation addressed to the current user."""
        return McpCollaborationInvitation.model_validate(
            call(
                lambda: application.decide_collaboration_invitation(
                    invitation_id,
                    InvitationDecisionRequest(decision=decision),
                    principal=current_principal(),
                )
            )
        )

    @mcp.tool(annotations=_READ_ONLY, meta=tool_meta)
    def list_my_notifications(
        unread_only: bool = False,
    ) -> list[McpNotification]:
        """List durable notifications for the current user."""
        return [
            McpNotification.model_validate(item)
            for item in call(
                lambda: application.list_my_notifications(
                    principal=current_principal(),
                    unread_only=unread_only,
                )
            )
        ]

    @mcp.tool(annotations=_INTERNAL_WRITE, meta=tool_meta)
    def mark_notification_read(
        notification_id: NotificationId,
    ) -> McpNotification:
        """Mark one notification belonging to the current user as read."""
        return McpNotification.model_validate(
            call(
                lambda: application.mark_notification_read(
                    notification_id,
                    principal=current_principal(),
                )
            )
        )

    @mcp.tool(annotations=_READ_ONLY, meta=tool_meta)
    def search_all_projects(
        query: QueryText,
        top_k: TopK = 8,
    ) -> McpSearchResponse:
        """Search knowledge across every active project and return previews."""
        return McpSearchResponse.from_search(
            call(
                lambda: application.search_all_projects(
                    SearchRequest(query=query, top_k=top_k),
                    principal=current_principal(),
                )
            )
        )

    @mcp.tool(annotations=_READ_ONLY, meta=tool_meta)
    def search_project_knowledge(
        project_id: ProjectId,
        query: QueryText,
        top_k: TopK = 5,
    ) -> McpSearchResponse:
        """Search one project; open material preview hits before citing them."""
        return McpSearchResponse.from_search(
            call(
                lambda: application.search_project_knowledge(
                    project_id,
                    SearchRequest(query=query, top_k=top_k),
                    principal=current_principal(),
                )
            )
        )

    @mcp.tool(annotations=_READ_ONLY, meta=tool_meta)
    def list_project_documents(
        project_id: ProjectId,
    ) -> list[McpDocumentSummary]:
        """Inventory project documents and inspect ingestion status."""
        return [
            McpDocumentSummary.from_record(item)
            for item in call(
                lambda: application.list_project_documents(
                    project_id,
                    principal=current_principal(),
                )
            )
        ]

    @mcp.tool(annotations=_READ_ONLY, meta=tool_meta)
    def get_document(
        project_id: ProjectId,
        document_id: DocumentId,
    ) -> McpDocumentSummary:
        """Get metadata, status, failure detail, and next action for a document."""
        return McpDocumentSummary.from_record(
            call(
                lambda: application.get_document(
                    project_id,
                    document_id,
                    principal=current_principal(),
                )
            )
        )

    @mcp.tool(annotations=_READ_ONLY, meta=tool_meta)
    def get_document_text(
        project_id: ProjectId,
        document_id: DocumentId,
    ) -> McpDocumentText:
        """Read complete indexed text after selecting a relevant document."""
        document, indexed = call(
            lambda: application.get_document_text(
                project_id,
                document_id,
                principal=current_principal(),
            )
        )
        return McpDocumentText.from_records(
            document=document,
            indexed_documents=indexed,
        )

    @mcp.tool(annotations=_READ_ONLY, meta=tool_meta)
    def get_document_download_url(
        project_id: ProjectId,
        document_id: DocumentId,
        download_format: DownloadFormat = "original",
    ) -> McpDocumentDownload:
        """Return a time-limited original or enhanced-Markdown download URL."""
        document = call(
            lambda: application.get_document(
                project_id,
                document_id,
                principal=current_principal(),
            )
        )
        download = call(
            lambda: application.get_document_download(
                project_id,
                document_id,
                principal=current_principal(),
                download_format=download_format,
            )
        )
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

    @mcp.tool(annotations=_INTERNAL_WRITE, meta=tool_meta)
    def render_project_dossier(
        project_id: ProjectId,
        markdown: DossierMarkdown,
        request_id: RequestId,
        filename_stem: DossierFilenameStem = None,
    ) -> McpDossierRender:
        """Render final cited Markdown to private DOCX and PDF download links."""
        rendered = call(
            lambda: application.render_project_dossier(
                project_id,
                DossierRenderRequest(
                    markdown=markdown,
                    filename_stem=filename_stem,
                    request_id=request_id,
                ),
                principal=current_principal(),
                request_id=request_id,
            )
        )
        return McpDossierRender.model_validate(asdict(rendered))

    @mcp.tool(annotations=_EXTERNAL_WRITE, meta=tool_meta)
    def prepare_document_upload(
        project_id: ProjectId,
        filename: Filename,
        content_type: ContentType,
        size_bytes: FileSize,
        request_id: RequestId,
    ) -> McpDocumentUpload:
        """Prepare direct-to-S3 upload fields plus a browser fallback URL."""
        return McpDocumentUpload.from_session(
            call(
                lambda: application.prepare_document_upload(
                    project_id,
                    UploadRequest(
                        filename=filename,
                        content_type=content_type,
                        size_bytes=size_bytes,
                        request_id=request_id,
                    ),
                    principal=current_principal(),
                    request_id=request_id,
                )
            )
        )

    @mcp.tool(annotations=_READ_ONLY, meta=tool_meta)
    def list_verified_facts(
        project_id: ProjectId,
    ) -> list[McpVerifiedFact]:
        """List explicitly verified facts and their provenance."""
        return [
            McpVerifiedFact.model_validate(item)
            for item in call(
                lambda: application.list_verified_facts(
                    project_id,
                    principal=current_principal(),
                )
            )
        ]

    @mcp.tool(annotations=_INTERNAL_WRITE, meta=tool_meta)
    def create_verified_fact(
        project_id: ProjectId,
        name: FactName,
        value: FactValue,
        provenance: FactProvenance,
        request_id: RequestId,
    ) -> McpVerifiedFact:
        """Store a confirmed fact; get explicit confirmation and never infer."""
        fact_id = stable_action_id(
            prefix="fact",
            project_id=project_id,
            request_id=request_id,
        )
        return McpVerifiedFact.model_validate(
            call(
                lambda: application.create_verified_fact(
                    project_id,
                    VerifiedFactCreate(
                        name=name,
                        value=value,
                        provenance=provenance,
                    ),
                    principal=current_principal(),
                    fact_id=fact_id,
                )
            )
        )

    @mcp.tool(annotations=_READ_ONLY, meta=tool_meta)
    def list_project_questions(
        project_id: ProjectId,
    ) -> list[McpQuestion]:
        """List a project's open, follow-up, and resolved questions."""
        return [
            McpQuestion.model_validate(item)
            for item in call(
                lambda: application.list_project_questions(
                    project_id,
                    principal=current_principal(),
                )
            )
        ]

    @mcp.tool(annotations=_READ_ONLY, meta=tool_meta)
    def list_my_assigned_questions(
        include_resolved: bool = False,
    ) -> list[McpQuestion]:
        """List questions explicitly assigned to the current user."""
        return [
            McpQuestion.model_validate(item)
            for item in call(
                lambda: application.list_my_assigned_questions(
                    principal=current_principal(),
                    include_resolved=include_resolved,
                )
            )
        ]

    @mcp.tool(annotations=_READ_ONLY, meta=tool_meta)
    def get_project_question(
        project_id: ProjectId,
        question_id: QuestionId,
    ) -> McpQuestion:
        """Get one question, its notification state, and latest review state."""
        return McpQuestion.model_validate(
            call(
                lambda: application.get_project_question(
                    project_id,
                    question_id,
                    principal=current_principal(),
                )
            )
        )

    @mcp.tool(annotations=_READ_ONLY, meta=tool_meta)
    def list_question_answers(
        project_id: ProjectId,
        question_id: QuestionId,
    ) -> list[McpAnswer]:
        """Inspect answer text, evidence, and human/LLM review state."""
        return [
            McpAnswer.model_validate(item)
            for item in call(
                lambda: application.list_question_answers(
                    project_id,
                    question_id,
                    principal=current_principal(),
                )
            )
        ]

    @mcp.tool(annotations=_EXTERNAL_WRITE, meta=tool_meta)
    def create_project_question(
        project_id: ProjectId,
        question: QuestionText,
        request_id: RequestId,
        assigned_expert_email: Email | None = None,
        context: QuestionContext = None,
        priority: Literal["low", "normal", "high"] = "normal",
    ) -> McpQuestion:
        """Create as any reader; resolve named targets first and confirm email."""
        question_id = stable_action_id(
            prefix="gap",
            project_id=project_id,
            request_id=request_id,
        )
        return McpQuestion.model_validate(
            call(
                lambda: application.create_project_question(
                    project_id,
                    KnowledgeGapCreate(
                        question=question,
                        assigned_expert_email=assigned_expert_email,
                        context=context,
                        priority=priority,
                    ),
                    principal=current_principal(),
                    question_id=question_id,
                )
            )
        )

    @mcp.tool(annotations=_EXTERNAL_WRITE, meta=tool_meta)
    def submit_question_answer(
        project_id: ProjectId,
        question_id: QuestionId,
        request_id: RequestId,
        answer: AnswerText = "",
        supporting_document_ids: SupportingDocumentIds | None = None,
    ) -> McpAnswer:
        """Answer with text and/or READY project documents; retries are safe."""
        answer_id = stable_action_id(
            prefix="ans",
            project_id=project_id,
            request_id=f"{question_id}:{request_id}",
        )
        return McpAnswer.model_validate(
            call(
                lambda: application.submit_question_answer(
                    project_id,
                    question_id,
                    AnswerSubmit(
                        answer=answer,
                        supporting_document_ids=supporting_document_ids or [],
                        request_id=request_id,
                    ),
                    principal=current_principal(),
                    answer_id=answer_id,
                )
            )
        )

    @mcp.tool(annotations=_DESTRUCTIVE_EXTERNAL_WRITE, meta=tool_meta)
    def review_question_answer(
        project_id: ProjectId,
        question_id: QuestionId,
        answer_id: AnswerId,
        decision: Literal["approve", "reject"],
        request_id: RequestId,
        note: ReviewNote = None,
    ) -> McpAnswer:
        """Approve or reject an external answer; confirm before rejecting."""
        return McpAnswer.model_validate(
            call(
                lambda: application.review_question_answer(
                    project_id,
                    question_id,
                    answer_id,
                    HumanAnswerReviewRequest(
                        decision=decision,
                        note=note,
                    ),
                    principal=current_principal(),
                    request_id=request_id,
                )
            )
        )

    @mcp.tool(annotations=_EXTERNAL_WRITE, meta=tool_meta)
    def resend_question_email(
        project_id: ProjectId,
        question_id: QuestionId,
        request_id: RequestId,
    ) -> McpQuestion:
        """Resend a question email only after explicit user confirmation."""
        return McpQuestion.model_validate(
            call(
                lambda: application.resend_question_email(
                    project_id,
                    question_id,
                    principal=current_principal(),
                    request_id=request_id,
                )
            )
        )

    return mcp


def build_mcp_asgi_app(mcp: FastMCP):
    return mcp.streamable_http_app()
