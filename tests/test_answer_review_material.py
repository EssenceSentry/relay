from __future__ import annotations

from typing import Any

from knowledge_core.answer_review_material import build_answer_review_material


class FakeRepository:
    def __init__(self, documents: dict[str, dict[str, Any]]) -> None:
        self.documents = documents

    def get_document(
        self,
        *,
        project_id: str,
        document_id: str,
    ) -> dict[str, Any] | None:
        assert project_id == "prj_1"
        return self.documents.get(document_id)


class FakeSearch:
    def __init__(self, texts: dict[str, str]) -> None:
        self.texts = texts

    def get_indexed_documents(
        self,
        *,
        project_id: str,
        document_id: str,
        size: int,
    ) -> list[dict[str, Any]]:
        assert project_id == "prj_1"
        assert size == 1000
        text = self.texts.get(document_id)
        return [] if text is None else [{"text": text}]


def test_review_material_uses_ready_documents_and_bounds_supporting_text() -> (
    None
):
    material, usable = build_answer_review_material(
        answer_history="Expert answer: [supporting documents only]",
        answers=[
            {
                "project_id": "prj_1",
                "answer": "",
                "supporting_document_ids": ["doc_ready", "doc_failed"],
                "attachments": [
                    {
                        "document_id": "doc_attachment",
                        "filename": "Attachment.pdf",
                        "status": "FAILED",
                        "error": "could not render",
                    }
                ],
            }
        ],
        repository=FakeRepository(
            {
                "doc_ready": {
                    "project_id": "prj_1",
                    "document_id": "doc_ready",
                    "document_name": "Ready.pdf",
                    "status": "READY",
                },
                "doc_failed": {
                    "project_id": "prj_1",
                    "document_id": "doc_failed",
                    "document_name": "Failed.pdf",
                    "status": "FAILED",
                },
            }
        ),
        search=FakeSearch({"doc_ready": "abcdefghijk"}),
        max_supporting_text_chars=5,
    )

    assert usable is True
    assert "Supporting document: Ready.pdf (doc_ready)\nabcde" in material
    assert "Failed.pdf" not in material
    assert "Attachment.pdf: could not render" in material


def test_review_material_marks_failed_attachment_only_reply_unusable() -> None:
    material, usable = build_answer_review_material(
        answer_history="Expert answer: [supporting documents only]",
        answers=[
            {
                "project_id": "prj_1",
                "answer": "",
                "attachments": [
                    {
                        "document_id": "doc_failed",
                        "filename": "Broken.doc",
                        "status": "FAILED",
                        "error": "conversion failed",
                    }
                ],
            }
        ],
        repository=FakeRepository({}),
        search=FakeSearch({}),
    )

    assert usable is False
    assert "Broken.doc: conversion failed" in material
