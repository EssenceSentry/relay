from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlencode

from app.auth import Principal
from app.document_downloads import (
    DocumentDownloadUnavailable,
    presign_document_download,
)
from app.services import ServiceContainer
from knowledge_core.answer_attachments import AnswerAttachmentPromoter
from knowledge_core.document_formats import (
    SUPPORTED_DOCUMENT_SUFFIXES,
    document_suffix,
)
from knowledge_core.ids import safe_filename, stable_action_id
from knowledge_core.models import (
    AnswerSubmit,
    CollaboratorInviteCreate,
    DocumentStatus,
    HumanAnswerReviewRequest,
    InvitationDecisionRequest,
    KnowledgeGapCreate,
    MembershipSource,
    NotificationKind,
    ProjectCreate,
    ProjectRename,
    ProjectStatus,
    SearchRequest,
    UploadRequest,
    VerifiedFactCreate,
)


class ApplicationError(RuntimeError):
    status_code = 500


class AuthenticationRequired(ApplicationError):
    status_code = 401


class PermissionDenied(ApplicationError):
    status_code = 403


class NotFound(ApplicationError):
    status_code = 404


class Conflict(ApplicationError):
    status_code = 409


class InvalidOperation(ApplicationError):
    status_code = 400


@dataclass(frozen=True, slots=True)
class UploadSession:
    document: dict[str, Any]
    upload_url: str
    fields: dict[str, str]
    expires_in_seconds: int
    fallback_url: str
    max_upload_bytes: int
    supported_extensions: tuple[str, ...]
    upload_required: bool


class KnowledgeApplication:
    """Shared authenticated operations used by both HTTP and MCP adapters."""

    def __init__(self, container: ServiceContainer) -> None:
        self.container = container

    def require_authenticated(self, principal: Principal) -> None:
        if principal.claims.get("authentication_mode") == "public":
            raise AuthenticationRequired(
                "Sign in with a verified @blend360.com account"
            )

    def require_project(
        self,
        project_id: str,
        *,
        principal: Principal,
        allow_archived_for_admin: bool = True,
    ) -> dict[str, Any]:
        self.require_authenticated(principal)
        project = self.container.repository.get_project(project_id)
        if project is None:
            raise NotFound("Project not found")
        archived = (
            project.get("status", ProjectStatus.ACTIVE.value)
            == ProjectStatus.ARCHIVED.value
        )
        if archived and not (
            allow_archived_for_admin and principal.is_admin
        ):
            raise NotFound("Project not found")
        return project

    def require_member(
        self,
        project_id: str,
        *,
        principal: Principal,
    ) -> dict[str, Any]:
        self.require_authenticated(principal)
        project = self.require_project(project_id, principal=principal)
        if principal.is_admin:
            return project
        if not self.container.repository.is_project_member(
            project_id=project_id,
            email=principal.email,
        ):
            raise PermissionDenied(
                "Project author or collaborator access is required"
            )
        return project

    def require_admin(self, principal: Principal) -> None:
        self.require_authenticated(principal)
        if not principal.is_admin:
            raise PermissionDenied("Administrator access is required")

    def get_current_user(self, principal: Principal) -> dict[str, Any]:
        self.require_authenticated(principal)
        return {
            "subject": principal.subject,
            "email": principal.email,
            "groups": sorted(principal.groups),
            "is_admin": principal.is_admin,
            "profile": self.container.repository.get_user_profile(
                principal.email
            ),
        }

    def list_projects(
        self,
        *,
        principal: Principal,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        self.require_authenticated(principal)
        if include_archived:
            self.require_admin(principal)
        return [
            self._project_for_principal(project, principal)
            for project in self.container.repository.list_projects(
                include_archived=include_archived
            )
        ]

    def get_project(
        self,
        project_id: str,
        *,
        principal: Principal,
    ) -> dict[str, Any]:
        project = self.require_project(project_id, principal=principal)
        return self._project_for_principal(project, principal)

    def create_project(
        self,
        body: ProjectCreate,
        *,
        principal: Principal,
        request_id: str,
    ) -> dict[str, Any]:
        self.require_authenticated(principal)
        project_id = stable_action_id(
            prefix="prj",
            project_id=principal.email,
            request_id=request_id,
        )
        existing = self.container.repository.get_project(project_id)
        if existing is not None:
            if str(existing.get("created_by")) != principal.email:
                raise Conflict("The request ID is already in use")
            return self._project_for_principal(existing, principal)
        project = self.container.repository.create_project(
            project_id=project_id,
            name=body.name,
            description=body.description,
            created_by=principal.email,
        )
        return self._project_for_principal(project, principal)

    def rename_project(
        self,
        project_id: str,
        body: ProjectRename,
        *,
        principal: Principal,
    ) -> dict[str, Any]:
        self.require_member(project_id, principal=principal)
        try:
            project = self.container.repository.rename_project(
                project_id=project_id,
                name=body.name,
                updated_by=principal.email,
            )
        except KeyError as exc:
            raise NotFound("Project not found") from exc
        return self._project_for_principal(project, principal)

    def set_project_archived(
        self,
        project_id: str,
        *,
        archived: bool,
        principal: Principal,
    ) -> dict[str, Any]:
        self.require_admin(principal)
        try:
            project = self.container.repository.set_project_archived(
                project_id=project_id,
                archived=archived,
                updated_by=principal.email,
            )
        except KeyError as exc:
            raise NotFound("Project not found") from exc
        return self._project_for_principal(project, principal)

    def list_project_collaborators(
        self,
        project_id: str,
        *,
        principal: Principal,
    ) -> list[dict[str, Any]]:
        self.require_member(project_id, principal=principal)
        return self.container.repository.list_project_members(project_id)

    def invite_project_collaborator(
        self,
        project_id: str,
        body: CollaboratorInviteCreate,
        *,
        principal: Principal,
        request_id: str,
    ) -> dict[str, Any]:
        del request_id
        project = self.require_member(project_id, principal=principal)
        if self.container.repository.get_user_profile(body.email) is None:
            raise NotFound(
                "The collaborator must first register a verified account"
            )
        if self.container.repository.is_project_member(
            project_id=project_id,
            email=body.email,
        ):
            raise Conflict("That user is already a project collaborator")
        self.container.repository.clear_collaborator_suppression(
            project_id=project_id,
            email=body.email,
        )
        invitation, created = (
            self.container.repository.create_collaboration_invitation(
                project_id=project_id,
                email=body.email,
                source=MembershipSource.MANUAL_INVITATION,
                invited_by=principal.email,
            )
        )
        if created:
            self.container.notifications.publish(
                email=body.email,
                kind=NotificationKind.COLLABORATION_INVITATION,
                title=f"Invitation to collaborate on {project['name']}",
                message=(
                    f"{principal.email} invited you to collaborate on "
                    f"{project['name']}."
                ),
                project_id=project_id,
                action_url=self.container.settings.application_base_url,
                send_email=True,
                data={
                    "project_name": project["name"],
                    "invitation_id": invitation["invitation_id"],
                },
                notification_id=(
                    f"manual-invite-{invitation['invitation_id']}"
                ),
            )
        return invitation

    def remove_project_collaborator(
        self,
        project_id: str,
        collaborator_email: str,
        *,
        principal: Principal,
    ) -> dict[str, Any]:
        self.require_member(project_id, principal=principal)
        try:
            return self.container.repository.remove_project_member(
                project_id=project_id,
                email=collaborator_email,
                removed_by=principal.email,
            )
        except KeyError as exc:
            raise NotFound(str(exc)) from exc
        except ValueError as exc:
            raise Conflict(str(exc)) from exc

    def list_my_collaboration_invitations(
        self,
        *,
        principal: Principal,
        include_decided: bool = False,
    ) -> list[dict[str, Any]]:
        self.require_authenticated(principal)
        return self.container.repository.list_collaboration_invitations(
            email=principal.email,
            include_decided=include_decided,
        )

    def decide_collaboration_invitation(
        self,
        invitation_id: str,
        body: InvitationDecisionRequest,
        *,
        principal: Principal,
    ) -> dict[str, Any]:
        self.require_authenticated(principal)
        try:
            return self.container.repository.decide_collaboration_invitation(
                email=principal.email,
                invitation_id=invitation_id,
                accepted=body.decision == "accept",
                user_subject=principal.subject,
            )
        except KeyError as exc:
            raise NotFound(str(exc)) from exc
        except ValueError as exc:
            raise Conflict(str(exc)) from exc

    def list_my_notifications(
        self,
        *,
        principal: Principal,
        unread_only: bool = False,
    ) -> list[dict[str, Any]]:
        self.require_authenticated(principal)
        return self.container.repository.list_notifications(
            email=principal.email,
            unread_only=unread_only,
        )

    def mark_notification_read(
        self,
        notification_id: str,
        *,
        principal: Principal,
    ) -> dict[str, Any]:
        self.require_authenticated(principal)
        try:
            return self.container.repository.mark_notification_read(
                email=principal.email,
                notification_id=notification_id,
            )
        except KeyError as exc:
            raise NotFound(str(exc)) from exc

    def list_project_documents(
        self,
        project_id: str,
        *,
        principal: Principal,
    ) -> list[dict[str, Any]]:
        self.require_project(project_id, principal=principal)
        return self.container.repository.list_documents(project_id)

    def get_document(
        self,
        project_id: str,
        document_id: str,
        *,
        principal: Principal,
    ) -> dict[str, Any]:
        self.require_project(project_id, principal=principal)
        document = self.container.repository.get_document(
            project_id=project_id,
            document_id=document_id,
        )
        if document is None:
            raise NotFound("Document not found")
        return document

    def get_document_text(
        self,
        project_id: str,
        document_id: str,
        *,
        principal: Principal,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        document = self.get_document(
            project_id,
            document_id,
            principal=principal,
        )
        indexed = self.container.search.get_indexed_documents(
            project_id=project_id,
            document_id=document_id,
            size=1000,
        )
        return document, indexed

    def get_document_download(
        self,
        project_id: str,
        document_id: str,
        *,
        principal: Principal,
        download_format: Literal["original", "markdown"],
    ):
        document = self.get_document(
            project_id,
            document_id,
            principal=principal,
        )
        try:
            return presign_document_download(
                s3=self.container.s3,
                document=document,
                download_format=download_format,
            )
        except DocumentDownloadUnavailable as exc:
            raise Conflict(str(exc)) from exc

    def prepare_document_upload(
        self,
        project_id: str,
        body: UploadRequest,
        *,
        principal: Principal,
        request_id: str,
    ) -> UploadSession:
        self.require_member(project_id, principal=principal)
        filename = safe_filename(body.filename)
        suffix = document_suffix(filename)
        if suffix not in SUPPORTED_DOCUMENT_SUFFIXES:
            supported = ", ".join(sorted(SUPPORTED_DOCUMENT_SUFFIXES))
            raise InvalidOperation(
                f"Unsupported file extension. Supported: {supported}"
            )
        if body.size_bytes > self.container.settings.max_upload_bytes:
            limit_mib = self.container.settings.max_upload_bytes // (
                1024 * 1024
            )
            raise InvalidOperation(
                f"File exceeds the {limit_mib} MiB upload limit"
            )
        document_id = stable_action_id(
            prefix="doc",
            project_id=project_id,
            request_id=request_id,
        )
        key = f"uploads/{project_id}/{document_id}/{filename}"
        existing = self.container.repository.get_document(
            project_id=project_id,
            document_id=document_id,
        )
        if existing is not None:
            expected = (
                str(existing.get("document_name")),
                int(existing.get("size_bytes") or 0),
                str(existing.get("content_type")),
            )
            requested = (body.filename, body.size_bytes, body.content_type)
            if expected != requested:
                raise Conflict(
                    "The upload request ID is already bound to another file"
                )
            document = existing
        else:
            document = self.container.repository.create_document(
                project_id=project_id,
                document_id=document_id,
                document_name=body.filename,
                s3_bucket=self.container.settings.document_bucket,
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
        presigned = self.container.s3.generate_presigned_post(
            Bucket=self.container.settings.document_bucket,
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
                        self.container.settings.max_upload_bytes,
                    ),
                ],
            ],
            ExpiresIn=900,
        )
        query = urlencode(
            {
                "upload_project_id": project_id,
                "upload_request_id": request_id,
            }
        )
        application_base_url = self._application_base_url()
        return UploadSession(
            document=document,
            upload_url=str(presigned["url"]),
            fields={
                str(key): str(value)
                for key, value in presigned["fields"].items()
            },
            expires_in_seconds=900,
            fallback_url=f"{application_base_url}/upload.html?{query}",
            max_upload_bytes=self.container.settings.max_upload_bytes,
            supported_extensions=tuple(sorted(SUPPORTED_DOCUMENT_SUFFIXES)),
            upload_required=(
                document.get("status") == DocumentStatus.UPLOADING.value
            ),
        )

    def search_all_projects(
        self,
        body: SearchRequest,
        *,
        principal: Principal,
    ):
        self.require_authenticated(principal)
        return self.container.retrieval.search_across_projects(
            query=body.query,
            top_k=body.top_k,
        )

    def search_project_knowledge(
        self,
        project_id: str,
        body: SearchRequest,
        *,
        principal: Principal,
    ):
        self.require_project(project_id, principal=principal)
        return self.container.retrieval.search(
            project_id=project_id,
            query=body.query,
            top_k=body.top_k,
        )

    def list_verified_facts(
        self,
        project_id: str,
        *,
        principal: Principal,
    ) -> list[dict[str, Any]]:
        self.require_project(project_id, principal=principal)
        return self.container.repository.list_verified_facts(project_id)

    def create_verified_fact(
        self,
        project_id: str,
        body: VerifiedFactCreate,
        *,
        principal: Principal,
        fact_id: str | None = None,
    ) -> dict[str, Any]:
        self.require_member(project_id, principal=principal)
        if fact_id is not None:
            existing = self.container.repository.get_verified_fact(
                project_id=project_id,
                fact_id=fact_id,
            )
            if existing is not None:
                return existing
        return self.container.repository.put_verified_fact(
            project_id=project_id,
            fact_id=fact_id,
            fact=body,
            created_by=principal.email,
        )

    def list_project_questions(
        self,
        project_id: str,
        *,
        principal: Principal,
    ) -> list[dict[str, Any]]:
        self.require_authenticated(principal)
        self.require_project(project_id, principal=principal)
        return self.container.repository.list_project_questions(project_id)

    def create_project_question(
        self,
        project_id: str,
        body: KnowledgeGapCreate,
        *,
        principal: Principal,
        question_id: str | None = None,
    ) -> dict[str, Any]:
        self.require_authenticated(principal)
        self.require_project(project_id, principal=principal)
        if question_id is not None:
            existing = self.container.repository.get_question(
                project_id=project_id,
                question_id=question_id,
            )
            if existing is not None:
                return existing
        return self.container.questions.create_question(
            project_id=project_id,
            gap=body,
            created_by=principal.email,
            question_id=question_id,
        )

    def resend_question_email(
        self,
        project_id: str,
        question_id: str,
        *,
        principal: Principal,
        request_id: str,
    ) -> dict[str, Any]:
        self.require_member(project_id, principal=principal)
        question = self.container.repository.get_question(
            project_id=project_id,
            question_id=question_id,
        )
        if question is None:
            raise NotFound("Question not found")
        if not self.container.repository.claim_question_email_resend(
            project_id=project_id,
            question_id=question_id,
            request_id=request_id,
        ):
            return question
        try:
            return self.container.questions.resend_question(
                project_id=project_id,
                question_id=question_id,
            )
        except KeyError as exc:
            raise NotFound(str(exc)) from exc
        except RuntimeError as exc:
            raise Conflict(str(exc)) from exc

    def list_my_assigned_questions(
        self,
        *,
        principal: Principal,
        include_resolved: bool = False,
    ) -> list[dict[str, Any]]:
        self.require_authenticated(principal)
        return self.container.repository.list_assigned_questions(
            principal.email,
            include_resolved=include_resolved,
        )

    def get_project_question(
        self,
        project_id: str,
        question_id: str,
        *,
        principal: Principal,
    ) -> dict[str, Any]:
        self.require_authenticated(principal)
        self.require_project(project_id, principal=principal)
        question = self.container.repository.get_question(
            project_id=project_id,
            question_id=question_id,
        )
        if question is None:
            raise NotFound("Question not found")
        return question

    def list_question_answers(
        self,
        project_id: str,
        question_id: str,
        *,
        principal: Principal,
    ) -> list[dict[str, Any]]:
        self.get_project_question(
            project_id,
            question_id,
            principal=principal,
        )
        answers = self.container.repository.list_question_answers(
            project_id=project_id,
            question_id=question_id,
        )
        if principal.is_admin or self.container.repository.is_project_member(
            project_id=project_id,
            email=principal.email,
        ):
            return answers
        return [
            answer
            for answer in answers
            if str(answer.get("answered_by")) == principal.email
        ]

    def submit_question_answer(
        self,
        project_id: str,
        question_id: str,
        body: AnswerSubmit,
        *,
        principal: Principal,
        answer_id: str | None = None,
    ) -> dict[str, Any]:
        self.require_authenticated(principal)
        project = self.require_project(project_id, principal=principal)
        self.get_project_question(
            project_id,
            question_id,
            principal=principal,
        )
        self._validate_supporting_documents(
            project_id=project_id,
            document_ids=body.supporting_document_ids,
            principal=principal,
        )
        is_member = principal.is_admin or (
            self.container.repository.is_project_member(
                project_id=project_id,
                email=principal.email,
            )
        )
        try:
            answer = self.container.repository.submit_answer(
                project_id=project_id,
                question_id=question_id,
                answer=body.answer,
                answered_by=principal.email,
                requires_human_review=not is_member,
                source="AUTHENTICATED_MCP_OR_API",
                answer_id=answer_id,
                supporting_document_ids=body.supporting_document_ids,
            )
        except (KeyError, ValueError) as exc:
            raise Conflict(str(exc)) from exc
        if not is_member:
            self._publish_answer_review_notifications(
                project=project,
                answered_by=principal.email,
                question_id=question_id,
                answer=answer,
            )
        return answer

    def review_question_answer(
        self,
        project_id: str,
        question_id: str,
        answer_id: str,
        body: HumanAnswerReviewRequest,
        *,
        principal: Principal,
        request_id: str,
    ) -> dict[str, Any]:
        del request_id
        self.require_member(project_id, principal=principal)
        try:
            reviewed = self.container.repository.decide_answer_human_review(
                project_id=project_id,
                question_id=question_id,
                answer_id=answer_id,
                approved=body.decision == "approve",
                reviewed_by=principal.email,
                note=body.note,
            )
        except KeyError as exc:
            raise NotFound(str(exc)) from exc
        except ValueError as exc:
            raise Conflict(str(exc)) from exc
        if body.decision == "approve" and reviewed.get("attachments"):
            reviewed = AnswerAttachmentPromoter(
                repository=self.container.repository,
                s3=self.container.s3,
                document_bucket=self.container.settings.document_bucket,
            ).promote(reviewed)
        answered_by = str(reviewed["answered_by"])
        project = self.container.repository.require_project(project_id)
        self.container.notifications.publish(
            email=answered_by,
            kind=NotificationKind.ANSWER_REVIEWED,
            title=(
                "Your answer was approved"
                if body.decision == "approve"
                else "Your answer needs revision"
            ),
            message=(
                (
                    "A project collaborator approved your answer. Supporting "
                    "documents are being processed before completeness review."
                    if reviewed.get("attachments")
                    else (
                        "A project collaborator approved your answer. It is "
                        "now being reviewed for completeness."
                    )
                )
                if body.decision == "approve"
                else (
                    body.note
                    or "A project collaborator rejected the submitted answer."
                )
            ),
            project_id=project_id,
            action_url=self.container.settings.application_base_url,
            send_email=True,
            data={
                "project_name": project["name"],
                "question_id": question_id,
                "answer_id": answer_id,
                "decision": body.decision,
            },
            notification_id=f"answer-reviewed-{answer_id}",
        )
        return reviewed

    def _project_for_principal(
        self,
        project: dict[str, Any],
        principal: Principal,
    ) -> dict[str, Any]:
        membership = (
            None
            if principal.is_admin
            else self.container.repository.get_project_membership(
                project_id=str(project["project_id"]),
                email=principal.email,
            )
        )
        role = (
            "ADMIN"
            if principal.is_admin
            else (
                str(membership.get("role"))
                if membership is not None
                else "READER"
            )
        )
        can_edit = principal.is_admin or membership is not None
        query = urlencode({"upload_project_id": project["project_id"]})
        upload_url = (
            f"{self._application_base_url()}/upload.html?{query}"
            if can_edit
            else None
        )
        return {
            **project,
            "my_role": role,
            "can_edit": can_edit,
            "can_archive": principal.is_admin,
            "upload_page_url": upload_url,
        }

    def _validate_supporting_documents(
        self,
        *,
        project_id: str,
        document_ids: list[str],
        principal: Principal,
    ) -> None:
        for document_id in document_ids:
            document = self.get_document(
                project_id,
                document_id,
                principal=principal,
            )
            if document.get("status") != DocumentStatus.READY.value:
                raise Conflict(
                    f"Supporting document {document_id} is not READY"
                )

    def _publish_answer_review_notifications(
        self,
        *,
        project: dict[str, Any],
        answered_by: str,
        question_id: str,
        answer: dict[str, Any],
    ) -> None:
        for member in self.container.repository.list_project_members(
            str(project["project_id"])
        ):
            member_email = str(member["email"])
            self.container.notifications.publish(
                email=member_email,
                kind=NotificationKind.ANSWER_REVIEW_REQUIRED,
                title=f"Answer review needed for {project['name']}",
                message=(
                    f"{answered_by} submitted an answer that needs "
                    "project-member approval before LLM review."
                ),
                project_id=str(project["project_id"]),
                action_url=self.container.settings.application_base_url,
                send_email=True,
                data={
                    "project_name": project["name"],
                    "question_id": question_id,
                    "answer_id": answer["answer_id"],
                },
                notification_id=(
                    f"answer-review-{answer['answer_id']}-"
                    f"{member_email.replace('@', '-')}"
                ),
            )

    def _application_base_url(self) -> str:
        value = self.container.settings.application_base_url
        if not value:
            raise InvalidOperation("The application base URL is not configured")
        return value.rstrip("/")
