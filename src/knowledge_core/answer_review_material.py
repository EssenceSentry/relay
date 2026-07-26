from __future__ import annotations

from typing import Any, Protocol

from pydantic import TypeAdapter

from knowledge_core.models import DocumentStatus

_DOCUMENT_ID_LIST_ADAPTER = TypeAdapter(list[str])
_ATTACHMENT_LIST_ADAPTER = TypeAdapter(list[dict[str, Any]])


class AnswerDocumentRepository(Protocol):
    def get_document(
        self,
        *,
        project_id: str,
        document_id: str,
    ) -> dict[str, Any] | None: ...


class IndexedDocumentReader(Protocol):
    def get_indexed_documents(
        self,
        *,
        project_id: str,
        document_id: str,
        size: int,
    ) -> list[dict[str, Any]]: ...


def build_answer_review_material(
    *,
    answer_history: str,
    answers: list[dict[str, Any]],
    repository: AnswerDocumentRepository,
    search: IndexedDocumentReader,
    max_supporting_text_chars: int = 200_000,
) -> tuple[str, bool]:
    """Combine answer history with bounded text from READY supporting files."""
    if not answers:
        return answer_history, bool(answer_history.strip())
    document_ids: list[str] = []
    has_text = any(str(answer.get("answer") or "").strip() for answer in answers)
    attachment_warnings: list[str] = []
    for answer in answers[-6:]:
        supporting_document_ids = _DOCUMENT_ID_LIST_ADAPTER.validate_python(
            answer.get("supporting_document_ids") or []
        )
        for document_id in supporting_document_ids:
            if document_id not in document_ids:
                document_ids.append(document_id)
        attachments = _ATTACHMENT_LIST_ADAPTER.validate_python(
            answer.get("attachments") or []
        )
        for attachment in attachments:
            if attachment.get("status") == DocumentStatus.READY.value:
                normalized = str(attachment.get("document_id") or "")
                if normalized and normalized not in document_ids:
                    document_ids.append(normalized)
            elif attachment.get("error"):
                attachment_warnings.append(
                    f"{attachment.get('filename')}: {attachment.get('error')}"
                )

    remaining = max_supporting_text_chars
    evidence_blocks: list[str] = []
    project_id = str(answers[-1]["project_id"])
    for document_id in document_ids:
        if remaining <= 0:
            break
        document = repository.get_document(
            project_id=project_id,
            document_id=document_id,
        )
        if (
            document is None
            or document.get("status") != DocumentStatus.READY.value
        ):
            continue
        indexed = search.get_indexed_documents(
            project_id=project_id,
            document_id=document_id,
            size=1000,
        )
        text = "\n\n".join(
            str(record.get("text") or "").strip()
            for record in indexed
            if str(record.get("text") or "").strip()
        )
        if not text:
            continue
        excerpt = text[:remaining]
        remaining -= len(excerpt)
        evidence_blocks.append(
            f"Supporting document: {document['document_name']} "
            f"({document_id})\n{excerpt}"
        )

    parts = [answer_history]
    if evidence_blocks:
        parts.extend(
            [
                "Supporting project-document evidence:",
                "\n\n".join(evidence_blocks),
            ]
        )
    if attachment_warnings:
        parts.extend(
            [
                "Attachment extraction warnings:",
                "\n".join(f"- {warning}" for warning in attachment_warnings),
            ]
        )
    return "\n\n".join(parts), has_text or bool(evidence_blocks)
