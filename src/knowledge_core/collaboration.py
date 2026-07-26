from __future__ import annotations

from typing import Any, Protocol

from knowledge_core.identity import (
    extract_blend_emails,
    normalize_blend_email,
)
from knowledge_core.models import (
    ContributorCandidate,
    DocumentEnhancementResult,
    MembershipRole,
    MembershipSource,
    NotificationKind,
)

CONTRIBUTOR_EXTRACTION_VERSION = "2026-07-26-v1"


class CandidateMatchingPublisher(Protocol):
    def candidate_created(self, evidence: dict[str, object]) -> None: ...


class DiscoveryNotificationPublisher(Protocol):
    def publish(
        self,
        *,
        email: str,
        kind: NotificationKind,
        title: str,
        message: str,
        project_id: str | None,
        action_url: str | None,
        send_email: bool,
        data: dict[str, Any] | None = None,
        notification_id: str | None = None,
    ) -> dict[str, Any]: ...


class DiscoveryRepository(Protocol):
    def require_project(self, project_id: str) -> dict[str, Any]: ...

    def ensure_project_membership(
        self,
        *,
        project_id: str,
        email: str,
        role: MembershipRole,
        source: MembershipSource,
        created_by: str,
        user_subject: str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]: ...

    def put_author_evidence(
        self,
        *,
        project_id: str,
        document_id: str,
        document_name: str,
        candidate: ContributorCandidate,
        page_number: int | None,
        locator: str | None,
        extraction_version: str,
    ) -> tuple[dict[str, Any], bool]: ...

    def record_document_discovery(
        self,
        *,
        project_id: str,
        document_id: str,
        blend360_emails: list[str],
        extraction_version: str,
    ) -> None: ...


class CollaborationDiscovery:
    def __init__(
        self,
        *,
        repository: DiscoveryRepository,
        notifications: DiscoveryNotificationPublisher,
        matching: CandidateMatchingPublisher,
        application_base_url: str,
    ) -> None:
        self._repository = repository
        self._notifications = notifications
        self._matching = matching
        self._application_base_url = application_base_url.rstrip("/") + "/"

    def record_document_enhancement(
        self,
        *,
        project_id: str,
        document_id: str,
        document_name: str,
        extracted_text: str,
        result: DocumentEnhancementResult,
        page_number: int | None = None,
        locator: str | None = None,
    ) -> None:
        source_text = f"{extracted_text}\n{result.markdown}"
        source_emails = set(extract_blend_emails(source_text))
        exact_emails = set(source_emails)
        for reported_email in result.blend360_emails:
            try:
                normalized = normalize_blend_email(reported_email)
            except ValueError:
                continue
            conflicts_with_visible_address = any(
                source_email != normalized
                and (source_email in normalized or normalized in source_email)
                for source_email in source_emails
            )
            if not conflicts_with_visible_address:
                exact_emails.add(normalized)

        project = self._repository.require_project(project_id)
        for email in sorted(exact_emails):
            evidence = {
                "document_id": document_id,
                "document_name": document_name,
                "page_number": page_number,
                "locator": locator,
                "extraction_version": CONTRIBUTOR_EXTRACTION_VERSION,
            }
            membership, _created = self._repository.ensure_project_membership(
                project_id=project_id,
                email=email,
                role=MembershipRole.COLLABORATOR,
                source=MembershipSource.DOCUMENT_EXACT_EMAIL,
                created_by="document-ingestion",
                evidence=evidence,
            )
            if (
                membership.get("entity_type") == "PROJECT_MEMBERSHIP"
                and membership.get("source")
                == MembershipSource.DOCUMENT_EXACT_EMAIL.value
            ):
                self._notifications.publish(
                    email=email,
                    kind=NotificationKind.COLLABORATOR_ADDED,
                    title=f"Added to {project['name']}",
                    message=(
                        "An exact Blend360 email address for you appeared in "
                        f"{document_name}. You were added as a project "
                        "collaborator."
                    ),
                    project_id=project_id,
                    action_url=self._application_base_url,
                    send_email=True,
                    data=evidence,
                    notification_id=(
                        f"exact-email-{project_id}-{_safe_id(email)}"
                    ),
                )

        for candidate in result.contributors:
            evidence, _created = self._repository.put_author_evidence(
                project_id=project_id,
                document_id=document_id,
                document_name=document_name,
                candidate=candidate,
                page_number=page_number,
                locator=locator,
                extraction_version=CONTRIBUTOR_EXTRACTION_VERSION,
            )
            self._matching.candidate_created(evidence)

        self._repository.record_document_discovery(
            project_id=project_id,
            document_id=document_id,
            blend360_emails=sorted(exact_emails),
            extraction_version=CONTRIBUTOR_EXTRACTION_VERSION,
        )


def _safe_id(value: str) -> str:
    return "".join(
        character if character.isalnum() else "-"
        for character in value.casefold()
    ).strip("-")
