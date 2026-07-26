from __future__ import annotations

from typing import Any

from knowledge_core.answer_attachments import AnswerAttachmentPromoter
from knowledge_core.models import DocumentStatus


class FakeRepository:
    def __init__(self) -> None:
        self.create_calls: list[dict[str, Any]] = []
        self.updated: list[dict[str, Any]] = []

    def create_document(self, **kwargs: Any) -> dict[str, Any]:
        self.create_calls.append(kwargs)
        return {
            **kwargs,
            "status": DocumentStatus.UPLOADING.value,
        }

    def update_answer_attachments(
        self,
        *,
        project_id: str,
        question_id: str,
        answer_id: str,
        attachments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self.updated = attachments
        return {
            "project_id": project_id,
            "question_id": question_id,
            "answer_id": answer_id,
            "attachments": attachments,
        }


class FakeS3:
    def __init__(self) -> None:
        self.copies: list[dict[str, Any]] = []

    def copy_object(self, **kwargs: Any) -> dict[str, Any]:
        self.copies.append(kwargs)
        return {}


def _answer(*, status: str = "QUARANTINED") -> dict[str, Any]:
    return {
        "project_id": "prj_1",
        "question_id": "gap_1",
        "answer_id": "ans_1",
        "answered_by": "expert@blend360.com",
        "attachments": [
            {
                "attachment_id": "att_1",
                "document_id": "doc_1",
                "filename": "Evidence.pdf",
                "content_type": "application/pdf",
                "size_bytes": 100,
                "sha256": "a" * 64,
                "status": status,
                "quarantine_bucket": "inbound",
                "quarantine_key": "answer-attachments/message/att/Evidence.pdf",
            }
        ],
    }


def test_attachment_promotion_copies_server_side_and_starts_ingestion() -> None:
    repository = FakeRepository()
    s3 = FakeS3()
    promoter = AnswerAttachmentPromoter(
        repository=repository,
        s3=s3,  # pyright: ignore[reportArgumentType]
        document_bucket="documents",
    )

    promoted = promoter.promote(_answer())

    assert repository.create_calls[0]["source_type"] == "EXPERT_ATTACHMENT"
    assert repository.create_calls[0]["return_existing"] is True
    assert s3.copies[0]["CopySource"]["Bucket"] == "inbound"
    assert s3.copies[0]["Key"].startswith("uploads/prj_1/doc_1/")
    assert promoted["attachments"][0]["status"] == "PROMOTED"


def test_already_promoted_attachment_is_not_copied_again() -> None:
    repository = FakeRepository()
    s3 = FakeS3()
    promoter = AnswerAttachmentPromoter(
        repository=repository,
        s3=s3,  # pyright: ignore[reportArgumentType]
        document_bucket="documents",
    )

    promoter.promote(_answer(status="PROMOTED"))

    assert repository.create_calls == []
    assert s3.copies == []
