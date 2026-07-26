from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError

from knowledge_core.dynamo import KnowledgeRepository
from knowledge_core.models import (
    DocumentStatus,
    MembershipSource,
    NameMatchDecision,
    NameMatchResult,
    VerifiedFactCreate,
)


class CapturingTable:
    def __init__(self) -> None:
        self.update_kwargs: dict[str, Any] | None = None

    def update_item(self, **kwargs: Any) -> dict[str, Any]:
        self.update_kwargs = kwargs
        return {
            "Attributes": {
                "project_id": "prj_1",
                "document_id": "doc_1",
                "status": DocumentStatus.READY.value,
            }
        }


class PaginatedProjectTable:
    def __init__(self) -> None:
        self.queries: list[dict[str, Any]] = []

    def query(self, **kwargs: Any) -> dict[str, Any]:
        self.queries.append(kwargs)
        if len(self.queries) == 1:
            return {
                "Items": [
                    {"project_id": "prj_2", "name": "Second"},
                ],
                "LastEvaluatedKey": {
                    "PK": "PROJECT#prj_2",
                    "SK": "META",
                },
            }
        return {
            "Items": [
                {"project_id": "prj_1", "name": "First"},
            ]
        }


class RenameProjectTable:
    def __init__(self) -> None:
        self.update_kwargs: dict[str, Any] | None = None

    def update_item(self, **kwargs: Any) -> dict[str, Any]:
        self.update_kwargs = kwargs
        return {
            "Attributes": {
                "project_id": "prj_1",
                "name": kwargs["ExpressionAttributeValues"][":name"],
                "updated_by": kwargs["ExpressionAttributeValues"][
                    ":updated_by"
                ],
            }
        }


def test_rename_project_updates_only_project_metadata() -> None:
    table = RenameProjectTable()
    repository = KnowledgeRepository.__new__(KnowledgeRepository)
    repository._table = table  # type: ignore[assignment]

    project = repository.rename_project(
        project_id="prj_1",
        name="  Renamed project  ",
        updated_by="owner@example.com",
    )

    assert table.update_kwargs is not None
    assert table.update_kwargs["Key"] == {
        "PK": "PROJECT#prj_1",
        "SK": "META",
    }
    assert table.update_kwargs["ExpressionAttributeValues"][":name"] == (
        "Renamed project"
    )
    assert table.update_kwargs["ExpressionAttributeValues"][":updated_by"] == (
        "owner@example.com"
    )
    assert table.update_kwargs["ReturnValues"] == "ALL_NEW"
    assert project["name"] == "Renamed project"


def test_list_projects_paginates_beyond_first_response() -> None:
    table = PaginatedProjectTable()
    repository = KnowledgeRepository.__new__(KnowledgeRepository)
    repository._table = table  # type: ignore[assignment]

    projects = repository.list_projects()

    assert [project["project_id"] for project in projects] == [
        "prj_2",
        "prj_1",
    ]
    assert table.queries[0]["Limit"] == 100
    assert table.queries[1]["ExclusiveStartKey"] == {
        "PK": "PROJECT#prj_2",
        "SK": "META",
    }


def test_status_update_removes_legacy_chunk_metadata() -> None:
    table = CapturingTable()
    repository = KnowledgeRepository.__new__(KnowledgeRepository)
    repository._table = table  # type: ignore[assignment]

    result = repository.update_document_status(
        project_id="prj_1",
        document_id="doc_1",
        status=DocumentStatus.READY,
        enhanced_s3_key="enhanced/prj_1/doc_1/document.md",
    )

    assert table.update_kwargs is not None
    assert table.update_kwargs["UpdateExpression"] == (
        "SET #status = :status, updated_at = :updated, "
        "enhanced_s3_key = :enhanced_s3_key "
        "REMOVE chunk_count, extracted_s3_key"
    )
    assert result["status"] == DocumentStatus.READY.value


def test_status_update_aliases_reserved_error_attribute() -> None:
    table = CapturingTable()
    repository = KnowledgeRepository.__new__(KnowledgeRepository)
    repository._table = table  # type: ignore[assignment]

    repository.update_document_status(
        project_id="prj_1",
        document_id="doc_1",
        status=DocumentStatus.FAILED,
        error="index failed",
    )

    assert table.update_kwargs is not None
    assert "#error = :error" in table.update_kwargs["UpdateExpression"]
    assert table.update_kwargs["ExpressionAttributeNames"]["#error"] == "error"
    assert table.update_kwargs["ExpressionAttributeValues"][":error"] == (
        "index failed"
    )


def test_page_ingestion_tracks_page_count_and_original_document_state() -> None:
    table = CapturingTable()
    repository = KnowledgeRepository.__new__(KnowledgeRepository)
    repository._table = table  # type: ignore[assignment]

    repository.begin_page_ingestion(
        project_id="prj_1",
        document_id="doc_1",
        page_count=8,
        enhanced_s3_key="extracted/prj_1/doc_1/document.md",
    )

    assert table.update_kwargs is not None
    values = table.update_kwargs["ExpressionAttributeValues"]
    assert values[":page_count"] == 8
    assert values[":processing_mode"] == "PAGE"
    assert "REMOVE completed_pages" in table.update_kwargs["UpdateExpression"]


def test_completed_pages_use_an_idempotent_dynamo_set() -> None:
    table = CapturingTable()
    repository = KnowledgeRepository.__new__(KnowledgeRepository)
    repository._table = table  # type: ignore[assignment]

    repository.record_completed_page(
        project_id="prj_1",
        document_id="doc_1",
        page_number=4,
    )

    assert table.update_kwargs is not None
    assert (
        "ADD completed_pages :page" in table.update_kwargs["UpdateExpression"]
    )
    assert table.update_kwargs["ExpressionAttributeValues"][":page"] == {"4"}


class FactTable:
    def __init__(self) -> None:
        self.put_kwargs: dict[str, Any] | None = None

    def get_item(self, **kwargs: Any) -> dict[str, Any]:
        key = kwargs["Key"]
        if key["SK"] == "META":
            return {"Item": {"project_id": "prj_1", "name": "Project one"}}
        return {}

    def put_item(self, **kwargs: Any) -> None:
        self.put_kwargs = kwargs


def test_verified_fact_create_is_conditionally_inserted() -> None:
    table = FactTable()
    repository = KnowledgeRepository.__new__(KnowledgeRepository)
    repository._table = table  # type: ignore[assignment]

    repository.put_verified_fact(
        project_id="prj_1",
        fact_id="fact_stable",
        fact=VerifiedFactCreate(
            name="Launch owner",
            value="A. Expert",
            provenance="Confirmed by the project lead",
        ),
        created_by="mcp-agent",
    )

    assert table.put_kwargs is not None
    assert table.put_kwargs["Item"]["SK"] == "FACT#fact_stable"
    assert table.put_kwargs["ConditionExpression"] == "attribute_not_exists(SK)"


class PutCaptureTable:
    def __init__(self) -> None:
        self.put_kwargs: dict[str, Any] | None = None

    def put_item(self, **kwargs: Any) -> None:
        self.put_kwargs = kwargs


def test_name_match_evaluation_is_stored_for_shadow_validation() -> None:
    table = PutCaptureTable()
    repository = KnowledgeRepository.__new__(KnowledgeRepository)
    repository._table = table  # type: ignore[assignment]

    stored = repository.put_name_match_evaluation(
        evidence={
            "project_id": "prj_1",
            "evidence_id": "author_1",
            "document_id": "doc_1",
            "document_name": "Delivery plan.pdf",
            "display_name": "María Pérez",
            "extraction_version": "2026-07-26-v1",
        },
        user_profile={
            "subject": "user-1",
            "email": "maria.perez@blend360.com",
            "display_name": "Maria Perez",
        },
        result=NameMatchResult(
            decision=NameMatchDecision.MATCH,
            confidence=0.98,
            rationale="Names and verified corporate identity align.",
        ),
        matching_model="gpt-5.6-luna",
        evaluated_by="contributor-matching-lambda",
    )

    assert table.put_kwargs is not None
    item = table.put_kwargs["Item"]
    assert item["entity_type"] == "NAME_MATCH_EVALUATION"
    assert item["decision"] == "MATCH"
    assert item["user_email"] == "maria.perez@blend360.com"
    assert item["matching_model"] == "gpt-5.6-luna"
    assert stored == item


class TransactionClient:
    def __init__(self, table: InvitationTable) -> None:
        self.table = table
        self.items: list[dict[str, Any]] | None = None

    def transact_write_items(
        self,
        *,
        TransactItems: list[dict[str, Any]],
    ) -> None:
        self.items = TransactItems
        self.table.decided = True


class TableMeta:
    def __init__(self, table: InvitationTable) -> None:
        self.client = TransactionClient(table)


class InvitationTable:
    name = "KnowledgeTable"

    def __init__(self) -> None:
        self.decided = False
        self.meta = TableMeta(self)

    def get_item(self, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        return {
            "Item": {
                "entity_type": "COLLABORATION_INVITATION",
                "invitation_id": "invite_1",
                "project_id": "prj_1",
                "email": "maria.perez@blend360.com",
                "source": MembershipSource.DOCUMENT_NAME_MATCH.value,
                "status": "DECLINED" if self.decided else "PENDING",
                "invited_by": "contributor-matching-lambda",
            }
        }


def test_declining_name_match_invitation_writes_suppression_atomically() -> None:
    table = InvitationTable()
    repository = KnowledgeRepository.__new__(KnowledgeRepository)
    repository._table = table  # type: ignore[assignment]

    result = repository.decide_collaboration_invitation(
        email="maria.perez@blend360.com",
        invitation_id="invite_1",
        accepted=False,
        user_subject="user-1",
    )

    assert result["status"] == "DECLINED"
    assert table.meta.client.items is not None
    suppression = table.meta.client.items[1]["Put"]["Item"]
    assert suppression["entity_type"] == {"S": "COLLABORATOR_SUPPRESSION"}
    assert suppression["reason"] == {"S": "INVITATION_DECLINED"}


class AlreadyReviewedTable:
    def update_item(self, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        raise ClientError(
            {
                "Error": {
                    "Code": "ConditionalCheckFailedException",
                    "Message": "already reviewed",
                }
            },
            "UpdateItem",
        )

    def get_item(self, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        return {
            "Item": {
                "answer_id": "ans_1",
                "review_status": "PENDING",
                "human_reviewed_by": "owner@blend360.com",
            }
        }


def test_repeating_same_human_review_decision_is_idempotent() -> None:
    table = AlreadyReviewedTable()
    repository = KnowledgeRepository.__new__(KnowledgeRepository)
    repository._table = table  # type: ignore[assignment]

    answer = repository.decide_answer_human_review(
        project_id="prj_1",
        question_id="gap_1",
        answer_id="ans_1",
        approved=True,
        reviewed_by="owner@blend360.com",
        note=None,
    )

    assert answer["answer_id"] == "ans_1"
