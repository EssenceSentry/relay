# pyright: reportUnusedFunction=false

from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from app.auth import Principal
from app.document_downloads import (
    DocumentDownloadUnavailable,
    presign_document_download,
)
from app.services import ServiceContainer
from knowledge_core.ids import new_id, safe_filename
from knowledge_core.models import (
    AnswerSubmit,
    DocumentStatus,
    KnowledgeGapCreate,
    ProjectCreate,
    SearchRequest,
    UploadRequest,
    VerifiedFactCreate,
)

_SUPPORTED_SUFFIXES = {
    ".pdf",
    ".doc",
    ".docx",
    ".pptx",
    ".txt",
    ".md",
    ".csv",
    ".json",
}


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


class PublicQuestionResponse(BaseModel):
    project_name: str
    question: str
    context: str | None = None
    priority: str
    status: str
    review_rationale: str | None = None
    can_answer: bool


class PublicAnswerResponse(BaseModel):
    status: str
    answer_id: str


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


AnswerTokenHeader = Annotated[
    str,
    Header(
        alias="X-Answer-Token",
        min_length=32,
        max_length=128,
        pattern=r"^[a-f0-9]+$",
    ),
]


def build_api_router(
    container: ServiceContainer,
    principal_dependency: Any,
) -> APIRouter:
    router = APIRouter(prefix="/api")
    principal_default = cast(
        Principal,
        Depends(principal_dependency),
    )

    @router.get(
        "/public/question",
        response_model=PublicQuestionResponse,
    )
    def get_public_question(
        answer_token: AnswerTokenHeader,
    ) -> PublicQuestionResponse:
        question = _question_for_answer_token(container, answer_token)
        return _public_question_response(question)

    @router.post(
        "/public/question/answers",
        response_model=PublicAnswerResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def submit_public_question_answer(
        body: AnswerSubmit,
        answer_token: AnswerTokenHeader,
    ) -> PublicAnswerResponse:
        question = _question_for_answer_token(container, answer_token)
        try:
            answer = container.repository.submit_answer(
                project_id=question["project_id"],
                question_id=question["question_id"],
                answer=body.answer,
                answered_by=question["assigned_expert_email"],
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return PublicAnswerResponse(
            status="SUBMITTED",
            answer_id=str(answer["answer_id"]),
        )

    @router.get("/me")
    def me(
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        return {
            "subject": principal.subject,
            "email": principal.email,
            "groups": sorted(principal.groups),
            "is_admin": principal.is_admin,
        }

    @router.get("/projects")
    def list_projects(
        principal: Principal = principal_default,
    ) -> list[dict[str, Any]]:
        del principal
        return container.repository.list_projects()

    @router.post("/projects", status_code=status.HTTP_201_CREATED)
    def create_project(
        body: ProjectCreate,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        return container.repository.create_project(
            name=body.name,
            description=body.description,
            created_by=principal.email,
        )

    @router.get("/projects/{project_id}")
    def get_project(
        project_id: str,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        del principal
        project = container.repository.get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    @router.get("/projects/{project_id}/documents")
    def list_documents(
        project_id: str,
        principal: Principal = principal_default,
    ) -> list[dict[str, Any]]:
        del principal
        _require_project(container, project_id)
        return container.repository.list_documents(project_id)

    @router.get("/projects/{project_id}/documents/{document_id}")
    def get_document(
        project_id: str,
        document_id: str,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        del principal
        document = container.repository.get_document(
            project_id=project_id,
            document_id=document_id,
        )
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return document

    @router.get(
        "/projects/{project_id}/documents/{document_id}/text",
    )
    def get_document_text(
        project_id: str,
        document_id: str,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        del principal
        document = container.repository.get_document(
            project_id=project_id,
            document_id=document_id,
        )
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        indexed_documents = container.search.get_indexed_documents(
            project_id=project_id,
            document_id=document_id,
            size=1000,
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
        principal: Principal = principal_default,
        download_format: Literal["original", "markdown"] = "original",
    ) -> DownloadUrlResponse:
        del principal
        document = container.repository.get_document(
            project_id=project_id,
            document_id=document_id,
        )
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        try:
            download = presign_document_download(
                s3=container.s3,
                document=document,
                download_format=download_format,
            )
        except DocumentDownloadUnavailable as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return DownloadUrlResponse(
            url=download.url,
            filename=download.filename,
            content_type=download.content_type,
            download_format=download.download_format,
            expires_in_seconds=download.expires_in_seconds,
        )

    @router.post(
        "/projects/{project_id}/uploads/presign",
        response_model=PresignedUploadResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def presign_upload(
        project_id: str,
        body: UploadRequest,
        principal: Principal = principal_default,
    ) -> PresignedUploadResponse:
        _require_project(container, project_id)
        filename = safe_filename(body.filename)
        suffix = _suffix(filename)
        if suffix not in _SUPPORTED_SUFFIXES:
            supported = ", ".join(sorted(_SUPPORTED_SUFFIXES))
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file extension. Supported: {supported}",
            )
        if body.size_bytes > container.settings.max_upload_bytes:
            limit_mib = container.settings.max_upload_bytes // (1024 * 1024)
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds the {limit_mib} MiB upload limit",
            )

        document_id = new_id("doc")
        key = f"uploads/{project_id}/{document_id}/{filename}"
        document = container.repository.create_document(
            project_id=project_id,
            document_id=document_id,
            document_name=body.filename,
            s3_bucket=container.settings.document_bucket,
            s3_key=key,
            content_type=body.content_type,
            size_bytes=body.size_bytes,
            status=DocumentStatus.UPLOADING,
            uploaded_by=principal.email,
        )
        fields = {
            "Content-Type": body.content_type,
            "x-amz-meta-project-id": project_id,
            "x-amz-meta-document-id": document_id,
        }
        presigned = container.s3.generate_presigned_post(
            Bucket=container.settings.document_bucket,
            Key=key,
            Fields=fields,
            Conditions=[
                {"Content-Type": body.content_type},
                {"x-amz-meta-project-id": project_id},
                {"x-amz-meta-document-id": document_id},
                [
                    "content-length-range",
                    1,
                    min(
                        body.size_bytes + 1024,
                        container.settings.max_upload_bytes,
                    ),
                ],
            ],
            ExpiresIn=900,
        )
        return PresignedUploadResponse(
            document=document,
            upload_url=presigned["url"],
            fields=presigned["fields"],
            expires_in_seconds=900,
        )

    @router.post("/search", response_model=WebSearchResponse)
    def search_all_projects(
        body: SearchRequest,
        principal: Principal = principal_default,
    ) -> WebSearchResponse:
        del principal
        response = container.retrieval.search_across_projects(
            query=body.query,
            top_k=body.top_k,
        )
        projects = {
            str(project["project_id"]): project
            for project in container.repository.list_projects()
        }
        hits: list[WebSearchHitResponse] = []
        for hit in response.hits:
            document = container.repository.get_document(
                project_id=hit.project_id,
                document_id=hit.document_id,
            )
            if document is None:
                continue
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
    def search_project(
        project_id: str,
        body: SearchRequest,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        del principal
        _require_project(container, project_id)
        return container.retrieval.search(
            project_id=project_id,
            query=body.query,
            top_k=body.top_k,
        ).model_dump()

    @router.get("/projects/{project_id}/facts")
    def list_facts(
        project_id: str,
        principal: Principal = principal_default,
    ) -> list[dict[str, Any]]:
        del principal
        _require_project(container, project_id)
        return container.repository.list_verified_facts(project_id)

    @router.post(
        "/projects/{project_id}/facts",
        status_code=status.HTTP_201_CREATED,
    )
    def create_fact(
        project_id: str,
        body: VerifiedFactCreate,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        return container.repository.put_verified_fact(
            project_id=project_id,
            fact=body,
            created_by=principal.email,
        )

    @router.get("/projects/{project_id}/questions")
    def list_project_questions(
        project_id: str,
        principal: Principal = principal_default,
    ) -> list[dict[str, Any]]:
        if not principal.is_admin:
            raise HTTPException(
                status_code=403,
                detail="Only administrators can list every project question",
            )
        _require_project(container, project_id)
        return container.repository.list_project_questions(project_id)

    @router.post(
        "/projects/{project_id}/questions",
        status_code=status.HTTP_201_CREATED,
    )
    def create_question(
        project_id: str,
        body: KnowledgeGapCreate,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        return container.questions.create_question(
            project_id=project_id,
            gap=body,
            created_by=principal.email,
        )

    @router.post(
        "/projects/{project_id}/questions/{question_id}/notification",
    )
    def resend_question_notification(
        project_id: str,
        question_id: str,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        if not principal.is_admin:
            raise HTTPException(
                status_code=403,
                detail="Only administrators can resend expert notifications",
            )
        try:
            return container.questions.resend_question(
                project_id=project_id,
                question_id=question_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/questions/assigned")
    def list_assigned_questions(
        include_resolved: bool = False,
        principal: Principal = principal_default,
    ) -> list[dict[str, Any]]:
        return container.repository.list_assigned_questions(
            principal.email,
            include_resolved=include_resolved,
        )

    @router.get("/projects/{project_id}/questions/{question_id}")
    def get_question(
        project_id: str,
        question_id: str,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        question = container.repository.get_question(
            project_id=project_id,
            question_id=question_id,
        )
        if question is None:
            raise HTTPException(status_code=404, detail="Question not found")
        if (
            not principal.is_admin
            and question["assigned_expert_email"] != principal.email
        ):
            raise HTTPException(
                status_code=403, detail="Question is not assigned to you"
            )
        return question

    @router.post(
        "/projects/{project_id}/questions/{question_id}/answers",
        status_code=status.HTTP_202_ACCEPTED,
    )
    def answer_question(
        project_id: str,
        question_id: str,
        body: AnswerSubmit,
        principal: Principal = principal_default,
    ) -> dict[str, Any]:
        question = container.repository.get_question(
            project_id=project_id,
            question_id=question_id,
        )
        if question is None:
            raise HTTPException(status_code=404, detail="Question not found")
        if (
            not principal.is_admin
            and question["assigned_expert_email"] != principal.email
        ):
            raise HTTPException(
                status_code=403,
                detail="Only the assigned expert or an administrator can answer",
            )
        try:
            return container.repository.submit_answer(
                project_id=project_id,
                question_id=question_id,
                answer=body.answer,
                answered_by=principal.email,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return router


def _question_for_answer_token(
    container: ServiceContainer,
    answer_token: str,
) -> dict[str, Any]:
    question = container.repository.get_question_by_reply_token(answer_token)
    if question is None:
        raise HTTPException(
            status_code=404,
            detail="This answer link is invalid or no longer available",
        )
    return question


def _public_question_response(
    question: dict[str, Any],
) -> PublicQuestionResponse:
    status_value = str(question["status"])
    return PublicQuestionResponse(
        project_name=str(question["project_name"]),
        question=str(question["question"]),
        context=(str(question["context"]) if question.get("context") else None),
        priority=str(question.get("priority") or "normal"),
        status=status_value,
        review_rationale=(
            str(question["review_rationale"])
            if question.get("review_rationale")
            else None
        ),
        can_answer=status_value != "RESOLVED",
    )


def _require_project(container: ServiceContainer, project_id: str) -> None:
    if container.repository.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")


def _suffix(filename: str) -> str:
    index = filename.rfind(".")
    return filename[index:].casefold() if index >= 0 else ""


def _search_text_preview(
    text: str, max_characters: int = 900
) -> tuple[str, bool]:
    normalized = text.strip()
    if len(normalized) <= max_characters:
        return normalized, False
    return normalized[:max_characters].rstrip() + "…", True
