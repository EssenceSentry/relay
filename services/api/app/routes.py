# FastAPI registers these nested route functions through decorators.
# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.application import (
    ApplicationError,
    KnowledgeApplication,
)
from app.auth import Principal
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

IdempotencyKey = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
]


class DownloadUrlResponse(BaseModel):
    url: str
    filename: str
    content_type: str
    download_format: Literal["original", "markdown"]
    expires_in_seconds: int


class PresignedUploadResponse(BaseModel):
    document: dict[str, Any]
    upload_url: str
    fields: dict[str, str]
    expires_in_seconds: int
    fallback_url: str
    max_upload_bytes: int
    supported_extensions: list[str]
    upload_required: bool


class DossierRenderResponse(BaseModel):
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


class WebSearchHitResponse(BaseModel):
    project_id: str
    project_name: str
    project_description: str | None = None
    document_id: str
    document_name: str
    source_type: str | None = None
    page_number: int | None = None
    page_count: int | None = None
    locator: str | None = None
    text_preview: str
    text_truncated: bool
    markdown_available: bool


class WebSearchResponse(BaseModel):
    query: str
    hits: list[WebSearchHitResponse]
    warnings: list[str]


def _api_call[T](function: Callable[[], T]) -> T:
    try:
        return function()
    except ApplicationError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=str(exc),
        ) from exc


def _required_request_id(
    *,
    body_request_id: str | None = None,
    idempotency_key: str | None = None,
) -> str:
    request_id = body_request_id or idempotency_key
    if request_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "A stable request_id or Idempotency-Key is required for "
                "this operation"
            ),
        )
    return request_id


def build_api_router(
    container: ServiceContainer,
    principal_dependency: Any,
) -> APIRouter:
    router = APIRouter(prefix="/api")
    application = KnowledgeApplication(container)
    principal_default = cast(Principal, Depends(principal_dependency))

    @router.get("/downloads/{token}", include_in_schema=False)
    def redeem_download(token: str) -> RedirectResponse:
        url = _api_call(lambda: application.redeem_download(token))
        return RedirectResponse(
            url,
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
            },
        )

    @router.get("/me")
    def get_current_user(
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        return _api_call(lambda: application.get_current_user(principal))

    @router.get("/users/directory")
    def search_user_directory(
        query: Annotated[str, Query(min_length=2, max_length=200)],
        limit: Annotated[int, Query(ge=1, le=10)] = 8,
        principal: Principal = principal_default,
    ) -> list[dict[str, Any]]:
        return _api_call(
            lambda: application.search_user_directory(
                query,
                principal=principal,
                limit=limit,
            )
        )

    @router.get("/projects")
    def list_projects(
        include_archived: bool = False,
        principal: Principal = principal_default,
    ) -> list[dict[str, Any]]:
        return _api_call(
            lambda: application.list_projects(
                principal=principal,
                include_archived=include_archived,
            )
        )

    @router.post("/projects", status_code=status.HTTP_201_CREATED)
    def create_project(
        body: ProjectCreate,
        idempotency_key: IdempotencyKey = None,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        request_id = _required_request_id(idempotency_key=idempotency_key)
        return _api_call(
            lambda: application.create_project(
                body,
                principal=principal,
                request_id=request_id,
            )
        )

    @router.get("/projects/{project_id}")
    def get_project(
        project_id: str,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        return _api_call(
            lambda: application.get_project(
                project_id,
                principal=principal,
            )
        )

    @router.patch("/projects/{project_id}")
    def rename_project(
        project_id: str,
        body: ProjectRename,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        return _api_call(
            lambda: application.rename_project(
                project_id,
                body,
                principal=principal,
            )
        )

    @router.delete("/projects/{project_id}")
    def archive_project(
        project_id: str,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        return _api_call(
            lambda: application.set_project_archived(
                project_id,
                archived=True,
                principal=principal,
            )
        )

    @router.post("/projects/{project_id}/restore")
    def restore_project(
        project_id: str,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        return _api_call(
            lambda: application.set_project_archived(
                project_id,
                archived=False,
                principal=principal,
            )
        )

    @router.get("/projects/{project_id}/collaborators")
    def list_project_collaborators(
        project_id: str,
        principal: Principal = principal_default,
    ) -> list[dict[str, Any]]:
        return _api_call(
            lambda: application.list_project_collaborators(
                project_id,
                principal=principal,
            )
        )

    @router.post(
        "/projects/{project_id}/collaboration-invitations",
        status_code=status.HTTP_201_CREATED,
    )
    def invite_project_collaborator(
        project_id: str,
        body: CollaboratorInviteCreate,
        idempotency_key: IdempotencyKey = None,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        request_id = _required_request_id(idempotency_key=idempotency_key)
        return _api_call(
            lambda: application.invite_project_collaborator(
                project_id,
                body,
                principal=principal,
                request_id=request_id,
            )
        )

    @router.delete(
        "/projects/{project_id}/collaborators/{collaborator_email}",
    )
    def remove_project_collaborator(
        project_id: str,
        collaborator_email: str,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        return _api_call(
            lambda: application.remove_project_collaborator(
                project_id,
                collaborator_email,
                principal=principal,
            )
        )

    @router.get("/me/collaboration-invitations")
    def list_my_collaboration_invitations(
        include_decided: bool = False,
        principal: Principal = principal_default,
    ) -> list[dict[str, Any]]:
        return _api_call(
            lambda: application.list_my_collaboration_invitations(
                principal=principal,
                include_decided=include_decided,
            )
        )

    @router.post("/me/collaboration-invitations/{invitation_id}/decision")
    def decide_collaboration_invitation(
        invitation_id: str,
        body: InvitationDecisionRequest,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        return _api_call(
            lambda: application.decide_collaboration_invitation(
                invitation_id,
                body,
                principal=principal,
            )
        )

    @router.get("/me/notifications")
    def list_my_notifications(
        unread_only: bool = False,
        principal: Principal = principal_default,
    ) -> list[dict[str, Any]]:
        return _api_call(
            lambda: application.list_my_notifications(
                principal=principal,
                unread_only=unread_only,
            )
        )

    @router.post("/me/notifications/{notification_id}/read")
    def mark_notification_read(
        notification_id: str,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        return _api_call(
            lambda: application.mark_notification_read(
                notification_id,
                principal=principal,
            )
        )

    @router.get("/projects/{project_id}/documents")
    def list_project_documents(
        project_id: str,
        principal: Principal = principal_default,
    ) -> list[dict[str, Any]]:
        return _api_call(
            lambda: application.list_project_documents(
                project_id,
                principal=principal,
            )
        )

    @router.get("/projects/{project_id}/documents/{document_id}")
    def get_document(
        project_id: str,
        document_id: str,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        return _api_call(
            lambda: application.get_document(
                project_id,
                document_id,
                principal=principal,
            )
        )

    @router.get("/projects/{project_id}/documents/{document_id}/text")
    def get_document_text(
        project_id: str,
        document_id: str,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        document, indexed_documents = _api_call(
            lambda: application.get_document_text(
                project_id,
                document_id,
                principal=principal,
            )
        )
        return {
            "document": document,
            "indexed_documents": indexed_documents,
        }

    @router.get(
        "/projects/{project_id}/documents/{document_id}/download-url",
        response_model=DownloadUrlResponse,
    )
    def get_document_download_url(
        project_id: str,
        document_id: str,
        download_format: Literal["original", "markdown"] = "original",
        principal: Principal = principal_default,
    ) -> DownloadUrlResponse:
        download = _api_call(
            lambda: application.get_document_download(
                project_id,
                document_id,
                principal=principal,
                download_format=download_format,
            )
        )
        return DownloadUrlResponse(
            url=download.url,
            filename=download.filename,
            content_type=download.content_type,
            download_format=download.download_format,
            expires_in_seconds=download.expires_in_seconds,
        )

    @router.post(
        "/projects/{project_id}/dossiers/render",
        response_model=DossierRenderResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def render_project_dossier(
        project_id: str,
        body: DossierRenderRequest,
        idempotency_key: IdempotencyKey = None,
        principal: Principal = principal_default,
    ) -> DossierRenderResponse:
        request_id = _required_request_id(
            body_request_id=body.request_id,
            idempotency_key=idempotency_key,
        )
        rendered = _api_call(
            lambda: application.render_project_dossier(
                project_id,
                body,
                principal=principal,
                request_id=request_id,
            )
        )
        return DossierRenderResponse(
            project_id=rendered.project_id,
            render_id=rendered.render_id,
            title=rendered.title,
            source_sha256=rendered.source_sha256,
            docx_url=rendered.docx_url,
            pdf_url=rendered.pdf_url,
            docx_filename=rendered.docx_filename,
            pdf_filename=rendered.pdf_filename,
            expires_in_seconds=rendered.expires_in_seconds,
            reused_existing_render=rendered.reused_existing_render,
        )

    @router.post(
        "/projects/{project_id}/uploads/presign",
        response_model=PresignedUploadResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def prepare_document_upload(
        project_id: str,
        body: UploadRequest,
        idempotency_key: IdempotencyKey = None,
        principal: Principal = principal_default,
    ) -> PresignedUploadResponse:
        request_id = _required_request_id(
            body_request_id=body.request_id,
            idempotency_key=idempotency_key,
        )
        upload = _api_call(
            lambda: application.prepare_document_upload(
                project_id,
                body,
                principal=principal,
                request_id=request_id,
            )
        )
        return PresignedUploadResponse(
            document=upload.document,
            upload_url=upload.upload_url,
            fields=upload.fields,
            expires_in_seconds=upload.expires_in_seconds,
            fallback_url=upload.fallback_url,
            max_upload_bytes=upload.max_upload_bytes,
            supported_extensions=list(upload.supported_extensions),
            upload_required=upload.upload_required,
        )

    @router.post("/search", response_model=WebSearchResponse)
    def search_all_projects(
        body: SearchRequest,
        principal: Principal = principal_default,
    ) -> WebSearchResponse:
        response = _api_call(
            lambda: application.search_all_projects(
                body,
                principal=principal,
            )
        )
        projects = {
            str(project["project_id"]): project
            for project in _api_call(
                lambda: application.list_projects(principal=principal)
            )
        }
        hits: list[WebSearchHitResponse] = []
        for hit in response.hits:
            document = _api_call(
                partial(
                    application.get_document,
                    hit.project_id,
                    hit.document_id,
                    principal=principal,
                )
            )
            project = projects.get(hit.project_id, {})
            preview, truncated = _search_text_preview(hit.text)
            hits.append(
                WebSearchHitResponse(
                    project_id=hit.project_id,
                    project_name=str(project.get("name") or hit.project_id),
                    project_description=project.get("description"),
                    document_id=hit.document_id,
                    document_name=hit.document_name,
                    source_type=hit.source_type,
                    page_number=hit.page_number,
                    page_count=hit.page_count,
                    locator=hit.locator,
                    text_preview=preview,
                    text_truncated=truncated,
                    markdown_available=bool(document.get("enhanced_s3_key")),
                )
            )
        return WebSearchResponse(
            query=response.query,
            hits=hits,
            warnings=response.warnings,
        )

    @router.post("/projects/{project_id}/search")
    def search_project_knowledge(
        project_id: str,
        body: SearchRequest,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        return _api_call(
            lambda: application.search_project_knowledge(
                project_id,
                body,
                principal=principal,
            ).model_dump()
        )

    @router.get("/projects/{project_id}/facts")
    def list_verified_facts(
        project_id: str,
        principal: Principal = principal_default,
    ) -> list[dict[str, Any]]:
        return _api_call(
            lambda: application.list_verified_facts(
                project_id,
                principal=principal,
            )
        )

    @router.post(
        "/projects/{project_id}/facts",
        status_code=status.HTTP_201_CREATED,
    )
    def create_verified_fact(
        project_id: str,
        body: VerifiedFactCreate,
        idempotency_key: IdempotencyKey = None,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        request_id = _required_request_id(idempotency_key=idempotency_key)
        fact_id = stable_action_id(
            prefix="fact",
            project_id=project_id,
            request_id=request_id,
        )
        return _api_call(
            lambda: application.create_verified_fact(
                project_id,
                body,
                principal=principal,
                fact_id=fact_id,
            )
        )

    @router.get("/projects/{project_id}/questions")
    def list_project_questions(
        project_id: str,
        principal: Principal = principal_default,
    ) -> list[dict[str, Any]]:
        return _api_call(
            lambda: application.list_project_questions(
                project_id,
                principal=principal,
            )
        )

    @router.post(
        "/projects/{project_id}/questions",
        status_code=status.HTTP_201_CREATED,
    )
    def create_project_question(
        project_id: str,
        body: KnowledgeGapCreate,
        idempotency_key: IdempotencyKey = None,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        request_id = _required_request_id(idempotency_key=idempotency_key)
        question_id = stable_action_id(
            prefix="gap",
            project_id=project_id,
            request_id=request_id,
        )
        return _api_call(
            lambda: application.create_project_question(
                project_id,
                body,
                principal=principal,
                question_id=question_id,
            )
        )

    @router.post(
        "/projects/{project_id}/questions/{question_id}/notification",
    )
    def resend_question_email(
        project_id: str,
        question_id: str,
        idempotency_key: IdempotencyKey = None,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        request_id = _required_request_id(idempotency_key=idempotency_key)
        return _api_call(
            lambda: application.resend_question_email(
                project_id,
                question_id,
                principal=principal,
                request_id=request_id,
            )
        )

    @router.get("/questions/assigned")
    def list_my_assigned_questions(
        include_resolved: bool = False,
        principal: Principal = principal_default,
    ) -> list[dict[str, Any]]:
        return _api_call(
            lambda: application.list_my_assigned_questions(
                principal=principal,
                include_resolved=include_resolved,
            )
        )

    @router.get("/projects/{project_id}/questions/{question_id}")
    def get_project_question(
        project_id: str,
        question_id: str,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        return _api_call(
            lambda: application.get_project_question(
                project_id,
                question_id,
                principal=principal,
            )
        )

    @router.get(
        "/projects/{project_id}/questions/{question_id}/answers",
    )
    def list_question_answers(
        project_id: str,
        question_id: str,
        principal: Principal = principal_default,
    ) -> list[dict[str, Any]]:
        return _api_call(
            lambda: application.list_question_answers(
                project_id,
                question_id,
                principal=principal,
            )
        )

    @router.post(
        "/projects/{project_id}/questions/{question_id}/answers",
        status_code=status.HTTP_202_ACCEPTED,
    )
    def submit_question_answer(
        project_id: str,
        question_id: str,
        body: AnswerSubmit,
        idempotency_key: IdempotencyKey = None,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        request_id = _required_request_id(
            body_request_id=body.request_id,
            idempotency_key=idempotency_key,
        )
        answer_id = stable_action_id(
            prefix="ans",
            project_id=project_id,
            request_id=f"{question_id}:{request_id}",
        )
        return _api_call(
            lambda: application.submit_question_answer(
                project_id,
                question_id,
                body,
                principal=principal,
                answer_id=answer_id,
            )
        )

    @router.post(
        "/projects/{project_id}/questions/{question_id}/answers/"
        "{answer_id}/human-review",
    )
    def review_question_answer(
        project_id: str,
        question_id: str,
        answer_id: str,
        body: HumanAnswerReviewRequest,
        idempotency_key: IdempotencyKey = None,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        request_id = _required_request_id(idempotency_key=idempotency_key)
        return _api_call(
            lambda: application.review_question_answer(
                project_id,
                question_id,
                answer_id,
                body,
                principal=principal,
                request_id=request_id,
            )
        )

    return router


def _search_text_preview(
    text: str,
    *,
    limit: int = 1600,
) -> tuple[str, bool]:
    normalized = text.strip()
    if len(normalized) <= limit:
        return normalized, False
    return normalized[:limit].rstrip() + "…", True
