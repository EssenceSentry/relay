from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import unquote_plus

import boto3

from knowledge_core.document_rendering import (
    render_document_as_pdf,
    split_pdf_pages,
)
from knowledge_core.dynamo import KnowledgeRepository
from knowledge_core.indexed_documents import build_indexed_document
from knowledge_core.indexing import DocumentIndexer
from knowledge_core.models import DocumentStatus, TextSection
from knowledge_core.openai_api import OpenAIService
from knowledge_core.opensearch import OpenSearchServerlessClient
from knowledge_core.page_processing import (
    combine_page_markdown,
    original_file_reference,
    should_process_by_page,
    wrap_page_markdown,
)
from knowledge_core.parsing import parse_document
from knowledge_core.secrets import SecretProvider
from knowledge_core.settings import IngestionSettings

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)
_MULTIMODAL_SUFFIXES = {".doc", ".docx", ".pdf", ".pptx"}
_PAGE_JOB_KIND = "document_page"

_SETTINGS = IngestionSettings.from_env()
_S3 = boto3.client("s3")
_SQS = boto3.client("sqs")
_REPOSITORY = KnowledgeRepository(
    _SETTINGS.table_name,
    region_name=_SETTINGS.aws_region,
)
_SECRETS = SecretProvider(region_name=_SETTINGS.aws_region)
_SEARCH = OpenSearchServerlessClient(
    endpoint=_SETTINGS.opensearch_endpoint,
    region=_SETTINGS.aws_region,
    index_name=_SETTINGS.opensearch_index,
    dimensions=_SETTINGS.embedding_dimensions,
)


def _openai_service() -> OpenAIService:
    api_key = _SECRETS.get(
        _SETTINGS.openai_secret_arn,
        "api_key",
        use_cache=False,
    )
    return OpenAIService(
        api_key=api_key,
        embedding_model=_SETTINGS.embedding_model,
        embedding_dimensions=_SETTINGS.embedding_dimensions,
        document_model=_SETTINGS.document_processing_model,
    )


def _indexer(openai: OpenAIService) -> DocumentIndexer:
    return DocumentIndexer(openai=openai, search=_SEARCH)


def _serialize_sections(sections: list[TextSection]) -> str:
    rendered: list[str] = []
    for section in sections:
        metadata = [
            value
            for value in (
                f"title={section.title}" if section.title else None,
                f"locator={section.locator}" if section.locator else None,
                (
                    f"page_number={section.page_number}"
                    if section.page_number is not None
                    else None
                ),
            )
            if value
        ]
        if metadata:
            rendered.append(f"[{', '.join(metadata)}]\n{section.text}")
        else:
            rendered.append(section.text)
    return "\n\n".join(rendered)


def _deterministic_sections(data: bytes, filename: str) -> list[TextSection]:
    try:
        return parse_document(data, filename)
    except Exception as exc:
        LOGGER.warning(
            "Deterministic text extraction failed for %s; continuing with "
            "the printed document: %s: %s",
            filename,
            type(exc).__name__,
            exc,
        )
        return []


def _page_extracted_text(
    *,
    page_pdf: bytes,
    deterministic_sections: list[TextSection],
    page_number: int,
) -> str:
    aligned = [
        section
        for section in deterministic_sections
        if section.page_number == page_number
    ]
    for rendered_section in parse_document(page_pdf, "rendered-page.pdf"):
        aligned.append(
            TextSection(
                text=rendered_section.text,
                title=rendered_section.title,
                locator=f"rendered page {page_number}",
                page_number=page_number,
            )
        )

    unique: list[TextSection] = []
    seen: set[str] = set()
    for section in aligned:
        normalized = section.text.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(section)
    return _serialize_sections(unique)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    del context
    failures: list[dict[str, str]] = []
    for record in event.get("Records", []):
        message_id = record.get("messageId", "unknown")
        try:
            _process_sqs_record(record)
        except Exception:
            LOGGER.exception(
                "Failed to process ingestion message %s", message_id
            )
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}


def _process_sqs_record(record: dict[str, Any]) -> None:
    body = json.loads(record["body"])
    if body.get("kind") == _PAGE_JOB_KIND:
        _process_page_job(body)
        return

    for s3_record in body.get("Records", []):
        if not str(s3_record.get("eventName", "")).startswith("ObjectCreated"):
            continue
        bucket = s3_record["s3"]["bucket"]["name"]
        key = unquote_plus(s3_record["s3"]["object"]["key"])
        _process_object(bucket=bucket, key=key)


def _process_object(*, bucket: str, key: str) -> None:
    parts = key.split("/", 3)
    if len(parts) != 4 or parts[0] != "uploads":
        LOGGER.info("Ignoring object outside the upload key scheme: %s", key)
        return
    _, project_id, document_id, filename = parts
    document = _REPOSITORY.get_document(
        project_id=project_id,
        document_id=document_id,
    )
    if document is None:
        raise RuntimeError(
            f"No DynamoDB document record for s3://{bucket}/{key}"
        )
    if document.get("status") == DocumentStatus.READY.value:
        LOGGER.info("Document %s is already ready; skipping", document_id)
        return
    if (
        document.get("processing_mode") == "PAGE"
        and document.get("page_jobs_scheduled") is True
    ):
        LOGGER.info(
            "Page jobs for document %s are already scheduled; skipping",
            document_id,
        )
        return

    try:
        _REPOSITORY.update_document_status(
            project_id=project_id,
            document_id=document_id,
            status=DocumentStatus.PARSING,
        )
        response = _S3.get_object(Bucket=bucket, Key=key)
        data = response["Body"].read()
        suffix = Path(filename).suffix.casefold()
        use_multimodal = suffix in _MULTIMODAL_SUFFIXES
        openai = _openai_service() if use_multimodal else None

        if use_multimodal:
            assert openai is not None
            deterministic = _deterministic_sections(data, filename)
            rendered_pdf = render_document_as_pdf(data, filename)
            rendered_pages = split_pdf_pages(rendered_pdf)
            if should_process_by_page(len(rendered_pages)):
                _schedule_page_ingestion(
                    bucket=bucket,
                    key=key,
                    filename=filename,
                    project_id=project_id,
                    document_id=document_id,
                    document=document,
                    rendered_pages=rendered_pages,
                    deterministic_sections=deterministic,
                )
                return

            markdown = openai.enhance_document_markdown(
                filename=filename,
                rendered_pdf=rendered_pdf,
                extracted_text=_serialize_sections(deterministic),
            )
            reference = original_file_reference(
                filename=filename,
                bucket=bucket,
                key=key,
            )
            markdown = f"> {reference}.\n\n{markdown}"
            sections = [
                TextSection(
                    text=markdown,
                    title=filename,
                    locator="enhanced document",
                )
            ]
            enhanced_markdown: str | None = markdown
        else:
            sections = parse_document(data, filename)
            enhanced_markdown = None

        if not sections:
            raise ValueError("No searchable content was found in the document")
        _index_complete_document(
            bucket=bucket,
            key=key,
            project_id=project_id,
            document_id=document_id,
            document=document,
            sections=sections,
            enhanced_markdown=enhanced_markdown,
            openai=openai or _openai_service(),
        )
    except Exception as exc:
        _REPOSITORY.update_document_status(
            project_id=project_id,
            document_id=document_id,
            status=DocumentStatus.FAILED,
            error=f"{type(exc).__name__}: {exc}",
        )
        raise


def _index_complete_document(
    *,
    bucket: str,
    key: str,
    project_id: str,
    document_id: str,
    document: dict[str, Any],
    sections: list[TextSection],
    enhanced_markdown: str | None,
    openai: OpenAIService,
) -> None:
    enhanced_key: str | None = None
    if enhanced_markdown is not None:
        enhanced_key = f"extracted/{project_id}/{document_id}/document.md"
        _put_markdown(bucket, enhanced_key, enhanced_markdown)

    indexed_document = build_indexed_document(
        text="\n\n".join(section.text for section in sections),
        project_id=project_id,
        document_id=document_id,
        document_version=str(document.get("document_version", "1")),
        document_name=document["document_name"],
        s3_bucket=bucket,
        s3_key=key,
        source_type=str(document.get("source_type", "UPLOADED")),
    )

    _REPOSITORY.update_document_status(
        project_id=project_id,
        document_id=document_id,
        status=DocumentStatus.EMBEDDING,
        enhanced_s3_key=enhanced_key,
    )
    _SEARCH.ensure_index()
    _SEARCH.delete_document(
        project_id=project_id,
        document_id=document_id,
    )
    _REPOSITORY.update_document_status(
        project_id=project_id,
        document_id=document_id,
        status=DocumentStatus.INDEXING,
        enhanced_s3_key=enhanced_key,
    )
    _indexer(openai).index_document(indexed_document)
    _REPOSITORY.update_document_status(
        project_id=project_id,
        document_id=document_id,
        status=DocumentStatus.READY,
        enhanced_s3_key=enhanced_key,
    )
    LOGGER.info("Indexed complete document %s", document_id)


def _schedule_page_ingestion(
    *,
    bucket: str,
    key: str,
    filename: str,
    project_id: str,
    document_id: str,
    document: dict[str, Any],
    rendered_pages: list[bytes],
    deterministic_sections: list[TextSection],
) -> None:
    page_count = len(rendered_pages)
    enhanced_key = f"extracted/{project_id}/{document_id}/document.md"
    jobs: list[dict[str, Any]] = []

    for page_number, page_pdf in enumerate(rendered_pages, start=1):
        page_prefix = (
            f"processing/{project_id}/{document_id}/pages/{page_number:06d}"
        )
        rendered_key = f"{page_prefix}.pdf"
        extracted_text_key = f"{page_prefix}.txt"
        extracted_text = _page_extracted_text(
            page_pdf=page_pdf,
            deterministic_sections=deterministic_sections,
            page_number=page_number,
        )
        _S3.put_object(
            Bucket=bucket,
            Key=rendered_key,
            Body=page_pdf,
            ContentType="application/pdf",
            ServerSideEncryption="AES256",
        )
        _S3.put_object(
            Bucket=bucket,
            Key=extracted_text_key,
            Body=extracted_text.encode("utf-8"),
            ContentType="text/plain; charset=utf-8",
            ServerSideEncryption="AES256",
        )
        jobs.append(
            {
                "kind": _PAGE_JOB_KIND,
                "bucket": bucket,
                "original_key": key,
                "filename": filename,
                "project_id": project_id,
                "document_id": document_id,
                "document_version": str(document.get("document_version", "1")),
                "page_number": page_number,
                "page_count": page_count,
                "rendered_pdf_key": rendered_key,
                "extracted_text_key": extracted_text_key,
            }
        )

    _SEARCH.ensure_index()
    _SEARCH.delete_document(
        project_id=project_id,
        document_id=document_id,
    )
    _REPOSITORY.begin_page_ingestion(
        project_id=project_id,
        document_id=document_id,
        page_count=page_count,
        enhanced_s3_key=enhanced_key,
    )
    _send_page_jobs(jobs)
    _REPOSITORY.mark_page_jobs_scheduled(
        project_id=project_id,
        document_id=document_id,
    )
    LOGGER.info(
        "Scheduled %s page jobs for document %s",
        page_count,
        document_id,
    )


def _send_page_jobs(jobs: list[dict[str, Any]]) -> None:
    for start in range(0, len(jobs), 10):
        batch = jobs[start : start + 10]
        response = _SQS.send_message_batch(
            QueueUrl=_SETTINGS.ingestion_queue_url,
            Entries=[
                {
                    "Id": f"page-{job['page_number']:06d}",
                    "MessageBody": json.dumps(job, separators=(",", ":")),
                }
                for job in batch
            ],
        )
        failures = response.get("Failed", [])
        if failures:
            raise RuntimeError(f"Failed to enqueue page jobs: {failures}")


def _process_page_job(job: dict[str, Any]) -> None:
    project_id = str(job["project_id"])
    document_id = str(job["document_id"])
    page_number = int(job["page_number"])
    page_count = int(job["page_count"])
    bucket = str(job["bucket"])
    original_key = str(job["original_key"])
    filename = str(job["filename"])
    document = _REPOSITORY.get_document(
        project_id=project_id,
        document_id=document_id,
    )
    if document is None:
        raise RuntimeError(f"Unknown document {document_id}")
    if document.get("status") == DocumentStatus.READY.value:
        LOGGER.info(
            "Document %s is already ready; skipping page %s",
            document_id,
            page_number,
        )
        return
    if document.get("processing_mode") != "PAGE":
        raise RuntimeError(
            f"Document {document_id} is not configured for page processing"
        )
    if int(document.get("page_count") or 0) != page_count:
        raise RuntimeError(
            f"Page count changed while processing document {document_id}"
        )

    try:
        page_pdf = _read_s3_bytes(bucket, str(job["rendered_pdf_key"]))
        extracted_text = _read_s3_bytes(
            bucket,
            str(job["extracted_text_key"]),
        ).decode("utf-8")
        openai = _openai_service()
        markdown = openai.enhance_document_markdown(
            filename=f"{filename} - page {page_number} of {page_count}",
            rendered_pdf=page_pdf,
            extracted_text=extracted_text,
        )
        page_markdown = wrap_page_markdown(
            markdown,
            filename=filename,
            bucket=bucket,
            key=original_key,
            page_number=page_number,
            page_count=page_count,
        )
        page_markdown_key = (
            f"extracted/{project_id}/{document_id}/pages/{page_number:06d}.md"
        )
        _put_markdown(bucket, page_markdown_key, page_markdown)

        indexed_page = build_indexed_document(
            text=page_markdown,
            project_id=project_id,
            document_id=document_id,
            document_version=str(
                document.get(
                    "document_version",
                    job.get("document_version", "1"),
                )
            ),
            document_name=str(document["document_name"]),
            s3_bucket=bucket,
            s3_key=original_key,
            source_type=str(document.get("source_type", "UPLOADED")),
            page_number=page_number,
            page_count=page_count,
            locator=f"page {page_number} of {page_count}",
        )
        _REPOSITORY.update_document_status(
            project_id=project_id,
            document_id=document_id,
            status=DocumentStatus.INDEXING,
            enhanced_s3_key=(
                f"extracted/{project_id}/{document_id}/document.md"
            ),
        )
        _indexer(openai).index_document(indexed_page)
        updated = _REPOSITORY.record_completed_page(
            project_id=project_id,
            document_id=document_id,
            page_number=page_number,
        )
        completed_pages = {
            str(value) for value in updated.get("completed_pages", set())
        }
        if len(completed_pages) >= page_count:
            _finalize_page_document(
                bucket=bucket,
                original_key=original_key,
                filename=filename,
                project_id=project_id,
                document_id=document_id,
                page_count=page_count,
            )
    except Exception as exc:
        _REPOSITORY.update_document_status(
            project_id=project_id,
            document_id=document_id,
            status=DocumentStatus.EMBEDDING,
            error=f"Page {page_number}: {type(exc).__name__}: {exc}",
        )
        raise


def _finalize_page_document(
    *,
    bucket: str,
    original_key: str,
    filename: str,
    project_id: str,
    document_id: str,
    page_count: int,
) -> None:
    pages = [
        _read_s3_bytes(
            bucket,
            (
                f"extracted/{project_id}/{document_id}/"
                f"pages/{page_number:06d}.md"
            ),
        ).decode("utf-8")
        for page_number in range(1, page_count + 1)
    ]
    combined = combine_page_markdown(
        pages,
        filename=filename,
        bucket=bucket,
        key=original_key,
    )
    enhanced_key = f"extracted/{project_id}/{document_id}/document.md"
    _put_markdown(bucket, enhanced_key, combined)
    _REPOSITORY.update_document_status(
        project_id=project_id,
        document_id=document_id,
        status=DocumentStatus.READY,
        enhanced_s3_key=enhanced_key,
    )
    LOGGER.info(
        "Indexed and concatenated %s pages for document %s",
        page_count,
        document_id,
    )


def _read_s3_bytes(bucket: str, key: str) -> bytes:
    response = _S3.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def _put_markdown(bucket: str, key: str, markdown: str) -> None:
    _S3.put_object(
        Bucket=bucket,
        Key=key,
        Body=markdown.encode("utf-8"),
        ContentType="text/markdown; charset=utf-8",
        ServerSideEncryption="AES256",
    )
