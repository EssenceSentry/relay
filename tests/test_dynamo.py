from __future__ import annotations

from typing import Any

from knowledge_core.dynamo import KnowledgeRepository
from knowledge_core.models import DocumentStatus, VerifiedFactCreate


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
