from __future__ import annotations

from typing import Any

from knowledge_core.collaboration import CollaborationDiscovery
from knowledge_core.models import (
    ContributorCandidate,
    DocumentEnhancementResult,
    MembershipRole,
    MembershipSource,
    NotificationKind,
)


class FakeRepository:
    def __init__(self) -> None:
        self.memberships: list[dict[str, Any]] = []
        self.evidence: list[dict[str, Any]] = []
        self.discovery: dict[str, Any] | None = None

    def require_project(self, project_id: str) -> dict[str, Any]:
        assert project_id == "prj_1"
        return {"project_id": project_id, "name": "Project One"}

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
    ) -> tuple[dict[str, Any], bool]:
        item = {
            "entity_type": "PROJECT_MEMBERSHIP",
            "project_id": project_id,
            "email": email,
            "role": role.value,
            "source": source.value,
            "created_by": created_by,
            "user_subject": user_subject,
            "evidence": evidence,
        }
        self.memberships.append(item)
        return item, True

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
    ) -> tuple[dict[str, Any], bool]:
        item = {
            "project_id": project_id,
            "document_id": document_id,
            "document_name": document_name,
            "display_name": candidate.display_name,
            "relationship": candidate.relationship,
            "confidence": candidate.confidence,
            "evidence": candidate.evidence,
            "page_number": page_number,
            "locator": locator,
            "extraction_version": extraction_version,
        }
        self.evidence.append(item)
        return item, True

    def record_document_discovery(
        self,
        *,
        project_id: str,
        document_id: str,
        blend360_emails: list[str],
        extraction_version: str,
    ) -> None:
        self.discovery = {
            "project_id": project_id,
            "document_id": document_id,
            "blend360_emails": blend360_emails,
            "extraction_version": extraction_version,
        }


class FakeNotifications:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

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
    ) -> dict[str, Any]:
        call = {
            "email": email,
            "kind": kind,
            "title": title,
            "message": message,
            "project_id": project_id,
            "action_url": action_url,
            "send_email": send_email,
            "data": data,
            "notification_id": notification_id,
        }
        self.calls.append(call)
        return call


class FakeMatching:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def candidate_created(self, evidence: dict[str, object]) -> None:
        self.calls.append(evidence)


def test_discovery_uses_grounded_exact_emails_and_preserves_page_evidence() -> (
    None
):
    repository = FakeRepository()
    notifications = FakeNotifications()
    matching = FakeMatching()
    discovery = CollaborationDiscovery(
        repository=repository,
        notifications=notifications,
        matching=matching,
        application_base_url="https://knowledge.example.com",
    )

    discovery.record_document_enhancement(
        project_id="prj_1",
        document_id="doc_1",
        document_name="Delivery plan.pdf",
        extracted_text="Owner: JoAnn@Blend360.com.",
        result=DocumentEnhancementResult(
            markdown="# Delivery plan\nPriya led delivery.",
            contributors=[
                ContributorCandidate(
                    display_name="Priya Shah",
                    relationship="Delivery lead",
                    confidence=0.98,
                    evidence="Priya led delivery.",
                )
            ],
            blend360_emails=[
                "ann@blend360.com",
                "joann@blend360.com",
            ],
        ),
        page_number=3,
        locator="page 3 of 6",
    )

    assert [item["email"] for item in repository.memberships] == [
        "joann@blend360.com"
    ]
    assert notifications.calls[0]["kind"] == NotificationKind.COLLABORATOR_ADDED
    assert notifications.calls[0]["notification_id"] == (
        "exact-email-prj_1-joann-blend360-com"
    )
    assert notifications.calls[0]["data"]["page_number"] == 3
    assert repository.evidence[0]["display_name"] == "Priya Shah"
    assert matching.calls == repository.evidence
    assert repository.discovery is not None
    assert repository.discovery["blend360_emails"] == ["joann@blend360.com"]


def test_discovery_accepts_exact_email_read_from_a_scanned_page() -> None:
    repository = FakeRepository()
    notifications = FakeNotifications()
    discovery = CollaborationDiscovery(
        repository=repository,
        notifications=notifications,
        matching=FakeMatching(),
        application_base_url="https://knowledge.example.com",
    )

    discovery.record_document_enhancement(
        project_id="prj_1",
        document_id="doc_scanned",
        document_name="Scanned handoff.pdf",
        extracted_text="",
        result=DocumentEnhancementResult(
            markdown="# Handoff\nThe scan identifies a delivery contact.",
            blend360_emails=["priya.shah@blend360.com"],
        ),
        page_number=1,
        locator="page 1 of 1",
    )

    assert repository.memberships[0]["email"] == "priya.shah@blend360.com"
    assert notifications.calls[0]["data"]["page_number"] == 1
