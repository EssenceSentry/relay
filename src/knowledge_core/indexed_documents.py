from __future__ import annotations

import hashlib

from knowledge_core.ids import stable_index_id
from knowledge_core.models import IndexedDocument


def build_indexed_document(
    *,
    text: str,
    project_id: str,
    document_id: str,
    document_version: str,
    document_name: str,
    s3_bucket: str,
    s3_key: str,
    source_type: str = "UPLOADED",
    page_number: int | None = None,
    page_count: int | None = None,
    locator: str | None = None,
) -> IndexedDocument:
    content = text.strip()
    if not content:
        raise ValueError("Indexed document text must not be empty")
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return IndexedDocument(
        index_id=stable_index_id(
            project_id=project_id,
            document_id=document_id,
            document_version=document_version,
            text=content,
        ),
        project_id=project_id,
        document_id=document_id,
        document_version=document_version,
        document_name=document_name,
        source_type=source_type,
        text=content,
        content_hash=content_hash,
        s3_bucket=s3_bucket,
        s3_key=s3_key,
        page_number=page_number,
        page_count=page_count,
        locator=locator,
    )
