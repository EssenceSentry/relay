from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from pydantic import TypeAdapter

from knowledge_core.ids import safe_filename
from knowledge_core.models import DocumentStatus

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

_ATTACHMENT_LIST_ADAPTER = TypeAdapter(list[dict[str, Any]])


class AttachmentRepository(Protocol):
    def create_document(
        self,
        *,
        project_id: str,
        document_id: str,
        document_name: str,
        s3_bucket: str,
        s3_key: str,
        content_type: str,
        size_bytes: int,
        status: DocumentStatus,
        uploaded_by: str,
        source_type: str,
        source_answer_id: str,
        source_attachment_id: str,
        source_question_id: str,
        return_existing: bool,
    ) -> dict[str, Any]: ...

    def update_answer_attachments(
        self,
        *,
        project_id: str,
        question_id: str,
        answer_id: str,
        attachments: list[dict[str, Any]],
    ) -> dict[str, Any]: ...


class AnswerAttachmentPromoter:
    def __init__(
        self,
        *,
        repository: AttachmentRepository,
        s3: S3Client,
        document_bucket: str,
    ) -> None:
        self._repository = repository
        self._s3 = s3
        self._document_bucket = document_bucket

    def promote(self, answer: dict[str, Any]) -> dict[str, Any]:
        promoted: list[dict[str, Any]] = []
        attachments = _ATTACHMENT_LIST_ADAPTER.validate_python(
            answer.get("attachments") or []
        )
        for attachment in attachments:
            item = dict(attachment)
            if item.get("status") in {"PROMOTED", "READY"}:
                promoted.append(item)
                continue
            document_id = str(item["document_id"])
            filename = safe_filename(str(item["filename"]))
            project_id = str(answer["project_id"])
            answer_id = str(answer["answer_id"])
            key = f"uploads/{project_id}/{document_id}/{filename}"
            document = self._repository.create_document(
                project_id=project_id,
                document_id=document_id,
                document_name=str(item["filename"]),
                s3_bucket=self._document_bucket,
                s3_key=key,
                content_type=str(item["content_type"]),
                size_bytes=int(item["size_bytes"]),
                status=DocumentStatus.UPLOADING,
                uploaded_by=str(answer["answered_by"]),
                source_type="EXPERT_ATTACHMENT",
                source_answer_id=answer_id,
                source_attachment_id=str(item["attachment_id"]),
                source_question_id=str(answer["question_id"]),
                return_existing=True,
            )
            if document.get("status") == DocumentStatus.UPLOADING.value:
                self._s3.copy_object(
                    Bucket=self._document_bucket,
                    Key=key,
                    CopySource={
                        "Bucket": str(item["quarantine_bucket"]),
                        "Key": str(item["quarantine_key"]),
                    },
                    ContentType=str(item["content_type"]),
                    MetadataDirective="REPLACE",
                    Metadata={
                        "project-id": project_id,
                        "document-id": document_id,
                        "answer-id": answer_id,
                    },
                    ServerSideEncryption="AES256",
                )
            item["status"] = "PROMOTED"
            item["promoted_s3_key"] = key
            promoted.append(item)
        return self._repository.update_answer_attachments(
            project_id=str(answer["project_id"]),
            question_id=str(answer["question_id"]),
            answer_id=str(answer["answer_id"]),
            attachments=promoted,
        )
