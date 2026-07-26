#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from _bootstrap_aws import (
    create_session,
    list_projects,
    load_stack_context,
    require_output,
    resolve_table_name,
)
from _project_mapping import ProjectFileGroup, load_project_mapping
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from ingest_local_documents import (
    get_document,
    resolve_mapped_projects,
    utc_now_iso,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPOSITORY_ROOT / "src"))

from knowledge_core.ids import stable_index_id  # noqa: E402
from knowledge_core.models import IndexedDocument  # noqa: E402
from knowledge_core.opensearch import (  # noqa: E402
    OpenSearchServerlessClient,
)

DEFAULT_PROJECT_MAP = Path("data/downloaded_markdown_projects.json")
DEFAULT_MARKDOWN_DIR = Path("data/downloaded_markdown")
DEFAULT_INDEX_NAME = "knowledge-documents-v1"
DEFAULT_DIMENSIONS = 1536
_SOURCE_HEADER = re.compile(
    r"^> Original file: .*?"
    r"\(`s3://(?P<bucket>[^/]+)/(?P<key>[^`]+)`\)\.\s*$",
    re.MULTILINE,
)
_COLLISION_DOCUMENT_ID = re.compile(
    r"__(?P<document_id>doc_[0-9a-f]{32})\.md$",
    re.IGNORECASE,
)


def _normalized_document_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


@dataclass(frozen=True)
class MappedMarkdown:
    group: ProjectFileGroup
    markdown_name: str
    markdown_path: Path


@dataclass(frozen=True)
class DocumentAssignment(MappedMarkdown):
    document_id: str
    s3_bucket: str
    s3_key: str


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reassign already-ingested documents to mapped projects without "
            "copying S3 objects, reprocessing documents, or regenerating "
            "embeddings. The default mode is a read-only dry run."
        )
    )
    parser.add_argument(
        "--source-project-id",
        required=True,
        help="Existing project that currently owns the documents.",
    )
    parser.add_argument(
        "--project-map",
        type=Path,
        default=DEFAULT_PROJECT_MAP,
    )
    parser.add_argument(
        "--markdown-dir",
        type=Path,
        default=DEFAULT_MARKDOWN_DIR,
        help=(
            "Downloaded Markdown directory. Each file must retain its "
            "Original file S3 header."
        ),
    )
    parser.add_argument(
        "--created-by",
        default=os.environ.get("EMAIL", "local-reassignment"),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the validated migration. Without this flag, no writes occur.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("document-reassignment-report.json"),
    )
    parser.add_argument(
        "--profile",
        default=os.environ.get("AWS_PROFILE"),
    )
    parser.add_argument("--region", default=os.environ.get("AWS_REGION"))
    parser.add_argument(
        "--outputs-file",
        type=Path,
        default=Path("cdk-outputs.json"),
    )
    parser.add_argument("--stack")
    parser.add_argument("--table-name")
    parser.add_argument("--index-name", default=DEFAULT_INDEX_NAME)
    parser.add_argument(
        "--embedding-dimensions",
        type=int,
        default=DEFAULT_DIMENSIONS,
    )
    return parser.parse_args()


def _parse_source_header(path: Path) -> tuple[str, str] | None:
    try:
        prefix = path.read_text(errors="replace")[:8192]
    except FileNotFoundError as exc:
        raise ValueError(f"Mapped Markdown file not found: {path}") from exc
    match = _SOURCE_HEADER.search(prefix)
    if match is None:
        return None
    return match.group("bucket"), match.group("key")


def _source_key_parts(key: str) -> tuple[str, str]:
    parts = key.split("/", 3)
    if len(parts) != 4 or parts[0] != "uploads":
        raise ValueError(f"Unexpected original S3 key: {key}")
    return parts[1], parts[2]


def load_mapped_markdown(
    *,
    groups: tuple[ProjectFileGroup, ...],
    markdown_dir: Path,
) -> tuple[MappedMarkdown, ...]:
    mapped: list[MappedMarkdown] = []
    for group in groups:
        for markdown_name in group.files:
            markdown_path = markdown_dir / markdown_name
            if not markdown_path.is_file():
                raise ValueError(
                    f"Mapped Markdown file not found: {markdown_path}"
                )
            mapped.append(
                MappedMarkdown(
                    group=group,
                    markdown_name=markdown_name,
                    markdown_path=markdown_path,
                )
            )
    return tuple(mapped)


def resolve_assignments(
    *,
    mapped_markdown: tuple[MappedMarkdown, ...],
    documents: dict[str, dict[str, Any]],
    source_project_id: str,
) -> tuple[DocumentAssignment, ...]:
    documents_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for document in documents.values():
        documents_by_name[
            _normalized_document_name(str(document.get("document_name", "")))
        ].append(document)

    assignments: list[DocumentAssignment] = []
    resolved_document_ids: dict[str, str] = {}
    for mapped in mapped_markdown:
        source = _parse_source_header(mapped.markdown_path)
        document: dict[str, Any] | None = None
        if source is not None:
            bucket, key = source
            project_id, document_id = _source_key_parts(key)
            if project_id != source_project_id:
                raise ValueError(
                    f"{mapped.markdown_name!r} references project "
                    f"{project_id!r}, not {source_project_id!r}"
                )
            document = documents.get(document_id)
            if document is None:
                raise ValueError(
                    f"{mapped.markdown_name!r} references absent document "
                    f"{document_id!r}"
                )
            if (
                str(document.get("s3_bucket")) != bucket
                or str(document.get("s3_key")) != key
            ):
                raise ValueError(
                    f"S3 provenance mismatch for {mapped.markdown_name!r}"
                )
        else:
            collision = _COLLISION_DOCUMENT_ID.search(mapped.markdown_name)
            if collision is not None:
                document_id = collision.group("document_id")
                document = documents.get(document_id)
            else:
                original_name = (
                    mapped.markdown_name[:-3]
                    if mapped.markdown_name.casefold().endswith(".md")
                    else mapped.markdown_name
                )
                candidates = documents_by_name.get(
                    _normalized_document_name(original_name),
                    [],
                )
                if len(candidates) == 1:
                    document = candidates[0]
                elif len(candidates) > 1:
                    raise ValueError(
                        f"{mapped.markdown_name!r} matches "
                        f"{len(candidates)} source documents by name"
                    )
            if document is None:
                raise ValueError(
                    f"Cannot resolve source document for "
                    f"{mapped.markdown_name!r}"
                )

        document_id = str(document["document_id"])
        if previous := resolved_document_ids.get(document_id):
            raise ValueError(
                f"Document {document_id!r} is referenced by both "
                f"{previous!r} and {mapped.markdown_name!r}"
            )
        resolved_document_ids[document_id] = mapped.markdown_name
        assignments.append(
            DocumentAssignment(
                group=mapped.group,
                markdown_name=mapped.markdown_name,
                markdown_path=mapped.markdown_path,
                document_id=document_id,
                s3_bucket=str(document["s3_bucket"]),
                s3_key=str(document["s3_key"]),
            )
        )
    return tuple(assignments)


def _list_documents(table: Any, project_id: str) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": (
            Key("PK").eq(f"PROJECT#{project_id}")
            & Key("SK").begins_with("DOCUMENT#")
        ),
        "ConsistentRead": True,
    }
    while True:
        response = table.query(**kwargs)
        documents.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return documents
        kwargs["ExclusiveStartKey"] = last_key


def _existing_group_projects(
    table: Any,
    groups: tuple[ProjectFileGroup, ...],
) -> dict[str, dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for project in list_projects(table):
        external_key = project.get("external_project_key")
        if isinstance(external_key, str) and external_key:
            by_key[external_key] = project
        name = project.get("name")
        if isinstance(name, str) and name:
            by_name[name.strip().casefold()] = project
    return {
        group.key: project
        for group in groups
        if (
            project := by_key.get(group.key)
            or by_name.get(group.title.casefold())
        )
        is not None
    }


def _candidate_documents(
    table: Any,
    *,
    source_documents: dict[str, dict[str, Any]],
    existing_projects: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    candidates = dict(source_documents)
    project_ids = {
        str(project["project_id"]) for project in existing_projects.values()
    }
    for project_id in project_ids:
        for document in _list_documents(table, project_id):
            document_id = str(document["document_id"])
            existing = candidates.get(document_id)
            if existing is not None:
                if existing.get("s3_bucket") != document.get(
                    "s3_bucket"
                ) or existing.get("s3_key") != document.get("s3_key"):
                    raise ValueError(
                        f"Document {document_id!r} has conflicting S3 pointers"
                    )
                continue
            candidates[document_id] = document
    return candidates


def _validate_document_pointer(
    assignment: DocumentAssignment,
    document: dict[str, Any],
) -> None:
    if str(document.get("document_id")) != assignment.document_id:
        raise ValueError(
            f"Document ID mismatch for {assignment.markdown_name!r}"
        )
    if str(document.get("s3_bucket")) != assignment.s3_bucket:
        raise ValueError(f"S3 bucket mismatch for {assignment.markdown_name!r}")
    if str(document.get("s3_key")) != assignment.s3_key:
        raise ValueError(f"S3 key mismatch for {assignment.markdown_name!r}")


def _partition_assignments(
    *,
    assignments: tuple[DocumentAssignment, ...],
    source_documents: dict[str, dict[str, Any]],
    existing_projects: dict[str, dict[str, Any]],
    table: Any,
) -> tuple[list[DocumentAssignment], list[DocumentAssignment]]:
    to_move: list[DocumentAssignment] = []
    already_moved: list[DocumentAssignment] = []
    missing: list[str] = []
    for assignment in assignments:
        source_document = source_documents.get(assignment.document_id)
        if source_document is not None:
            _validate_document_pointer(assignment, source_document)
            if source_document.get("status") != "READY":
                raise ValueError(
                    f"Document {assignment.document_id} is "
                    f"{source_document.get('status')}, not READY"
                )
            to_move.append(assignment)
            continue
        target_project = existing_projects.get(assignment.group.key)
        if target_project is None:
            missing.append(assignment.markdown_name)
            continue
        target_document = get_document(
            table,
            project_id=str(target_project["project_id"]),
            document_id=assignment.document_id,
        )
        if target_document is None:
            missing.append(assignment.markdown_name)
            continue
        _validate_document_pointer(assignment, target_document)
        already_moved.append(assignment)
    if missing:
        preview = ", ".join(repr(name) for name in missing[:5])
        suffix = "" if len(missing) <= 5 else f", and {len(missing) - 5} more"
        raise ValueError(
            f"{len(missing)} mapped documents are absent from both source and "
            f"target projects: {preview}{suffix}"
        )
    return to_move, already_moved


def _validated_index_documents(
    raw_documents: list[dict[str, Any]],
    *,
    assignments: list[DocumentAssignment],
) -> dict[str, list[IndexedDocument]]:
    requested_ids = {assignment.document_id for assignment in assignments}
    by_document: dict[str, list[IndexedDocument]] = defaultdict(list)
    for raw_document in raw_documents:
        payload = {
            key: value
            for key, value in raw_document.items()
            if not key.startswith("_")
        }
        document = IndexedDocument.model_validate(payload)
        if document.document_id not in requested_ids:
            continue
        if document.embedding is None:
            raise ValueError(
                f"Indexed document {document.index_id} has no embedding"
            )
        by_document[document.document_id].append(document)
    missing = sorted(requested_ids.difference(by_document))
    if missing:
        preview = ", ".join(missing[:5])
        suffix = "" if len(missing) <= 5 else f", and {len(missing) - 5} more"
        raise ValueError(
            f"{len(missing)} documents have no OpenSearch entries: "
            f"{preview}{suffix}"
        )
    return dict(by_document)


def _mapped_source_index_ids(
    raw_documents: list[dict[str, Any]],
    *,
    assignments: tuple[DocumentAssignment, ...],
) -> list[str]:
    requested_ids = {assignment.document_id for assignment in assignments}
    return [
        str(document.get("_id") or document["index_id"])
        for document in raw_documents
        if str(document.get("document_id")) in requested_ids
    ]


def _target_index_documents(
    *,
    source_documents: dict[str, list[IndexedDocument]],
    assignments: list[DocumentAssignment],
    projects: dict[str, dict[str, Any]],
) -> list[IndexedDocument]:
    assignments_by_id = {
        assignment.document_id: assignment for assignment in assignments
    }
    target_documents: list[IndexedDocument] = []
    for document_id, indexed_documents in source_documents.items():
        assignment = assignments_by_id[document_id]
        target_project_id = str(projects[assignment.group.key]["project_id"])
        for document in indexed_documents:
            target_documents.append(
                document.model_copy(
                    update={
                        "project_id": target_project_id,
                        "index_id": stable_index_id(
                            project_id=target_project_id,
                            document_id=document.document_id,
                            document_version=document.document_version,
                            text=document.text,
                        ),
                    }
                )
            )
    return target_documents


def _delete_source_document(
    table: Any,
    *,
    source_project_id: str,
    document_id: str,
) -> None:
    table.delete_item(
        Key={
            "PK": f"PROJECT#{source_project_id}",
            "SK": f"DOCUMENT#{document_id}",
        },
        ConditionExpression=(
            "project_id = :project_id AND document_id = :document_id"
        ),
        ExpressionAttributeValues={
            ":project_id": source_project_id,
            ":document_id": document_id,
        },
    )


def _move_document_record(
    table: Any,
    *,
    assignment: DocumentAssignment,
    source_document: dict[str, Any],
    source_project_id: str,
    target_project_id: str,
) -> None:
    existing = get_document(
        table,
        project_id=target_project_id,
        document_id=assignment.document_id,
    )
    if existing is not None:
        _validate_document_pointer(assignment, existing)
        _delete_source_document(
            table,
            source_project_id=source_project_id,
            document_id=assignment.document_id,
        )
        return

    moved_at = utc_now_iso()
    target_document = {
        **source_document,
        "PK": f"PROJECT#{target_project_id}",
        "project_id": target_project_id,
        "updated_at": moved_at,
        "reassigned_at": moved_at,
        "reassigned_from_project_id": source_project_id,
    }
    try:
        table.put_item(
            Item=target_document,
            ConditionExpression="attribute_not_exists(PK)",
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code != "ConditionalCheckFailedException":
            raise
        existing = get_document(
            table,
            project_id=target_project_id,
            document_id=assignment.document_id,
        )
        if existing is None:
            raise
        _validate_document_pointer(assignment, existing)
    _delete_source_document(
        table,
        source_project_id=source_project_id,
        document_id=assignment.document_id,
    )


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _wait_for_source_search_cleanup(
    search: OpenSearchServerlessClient,
    *,
    source_project_id: str,
    moved_document_ids: set[str],
    timeout_seconds: float = 180.0,
    poll_interval_seconds: float = 3.0,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        source_documents = search.get_project_documents(
            project_id=source_project_id,
        )
        remaining_moved_ids = {
            str(document.get("document_id"))
            for document in source_documents
            if str(document.get("document_id")) in moved_document_ids
        }
        if not remaining_moved_ids:
            return source_documents
        if time.monotonic() >= deadline:
            preview = ", ".join(sorted(remaining_moved_ids)[:5])
            raise RuntimeError(
                "Timed out waiting for OpenSearch to remove "
                f"{len(remaining_moved_ids)} moved documents: {preview}"
            )
        time.sleep(poll_interval_seconds)


def main() -> None:
    args = _arguments()
    try:
        groups = load_project_mapping(args.project_map)
        mapped_markdown = load_mapped_markdown(
            groups=groups,
            markdown_dir=args.markdown_dir,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    context = load_stack_context(args.outputs_file, args.stack)
    session = create_session(
        profile=args.profile,
        region=args.region,
        outputs=context.outputs,
    )
    table_name = resolve_table_name(
        context=context,
        session=session,
        override=args.table_name,
    )
    table = session.resource("dynamodb").Table(table_name)
    source_documents = {
        str(document["document_id"]): document
        for document in _list_documents(table, args.source_project_id)
    }
    existing_projects = _existing_group_projects(table, groups)
    candidate_documents = _candidate_documents(
        table,
        source_documents=source_documents,
        existing_projects=existing_projects,
    )
    try:
        assignments = resolve_assignments(
            mapped_markdown=mapped_markdown,
            documents=candidate_documents,
            source_project_id=args.source_project_id,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    try:
        to_move, already_moved = _partition_assignments(
            assignments=assignments,
            source_documents=source_documents,
            existing_projects=existing_projects,
            table=table,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    search = OpenSearchServerlessClient(
        endpoint=require_output(context, "OpenSearchEndpoint"),
        region=session.region_name or "us-east-1",
        index_name=args.index_name,
        dimensions=args.embedding_dimensions,
        aws_session=session,
    )
    raw_index_documents = search.get_project_documents(
        project_id=args.source_project_id,
        include_embedding=True,
        page_size=100,
    )
    try:
        indexed_by_document = _validated_index_documents(
            raw_index_documents,
            assignments=to_move,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    indexed_count = sum(len(items) for items in indexed_by_document.values())
    source_index_ids = _mapped_source_index_ids(
        raw_index_documents,
        assignments=assignments,
    )

    preview = {
        "mode": "apply" if args.apply else "dry-run",
        "source_project_id": args.source_project_id,
        "mapping_projects": len(groups),
        "mapped_documents": len(assignments),
        "projects_already_present": len(existing_projects),
        "projects_to_create": len(groups) - len(existing_projects),
        "documents_to_move": len(to_move),
        "documents_already_moved": len(already_moved),
        "search_entries_to_copy": indexed_count,
        "source_search_entries_to_delete": len(source_index_ids),
        "s3_objects_to_upload": 0,
        "embeddings_to_generate": 0,
    }
    if not args.apply:
        _write_report(args.report, preview)
        print(json.dumps(preview, indent=2))
        print(f"Dry run complete. Report: {args.report}")
        return

    projects, created_keys = resolve_mapped_projects(
        table,
        groups=set(groups),
        created_by=args.created_by,
    )
    target_index_documents = _target_index_documents(
        source_documents=indexed_by_document,
        assignments=to_move,
        projects=projects,
    )
    search.bulk_index(
        [document.search_document() for document in target_index_documents],
    )

    for index, assignment in enumerate(to_move, start=1):
        source_document = source_documents[assignment.document_id]
        target_project_id = str(projects[assignment.group.key]["project_id"])
        _move_document_record(
            table,
            assignment=assignment,
            source_document=source_document,
            source_project_id=args.source_project_id,
            target_project_id=target_project_id,
        )
        if index % 50 == 0 or index == len(to_move):
            print(f"Moved {index}/{len(to_move)} DynamoDB document records.")

    search.bulk_delete(source_index_ids)

    remaining_source = {
        str(document["document_id"]): document
        for document in _list_documents(table, args.source_project_id)
    }
    unexpectedly_remaining = sorted(
        assignment.document_id
        for assignment in to_move
        if assignment.document_id in remaining_source
    )
    missing_targets: list[str] = []
    for assignment in assignments:
        target_project_id = str(projects[assignment.group.key]["project_id"])
        target = get_document(
            table,
            project_id=target_project_id,
            document_id=assignment.document_id,
        )
        if target is None:
            missing_targets.append(assignment.document_id)
        else:
            _validate_document_pointer(assignment, target)
    moved_ids = {assignment.document_id for assignment in assignments}
    remaining_source_index = _wait_for_source_search_cleanup(
        search,
        source_project_id=args.source_project_id,
        moved_document_ids=moved_ids,
    )
    if unexpectedly_remaining or missing_targets:
        raise RuntimeError(
            "Post-migration verification failed: "
            f"source records={len(unexpectedly_remaining)}, "
            f"missing targets={len(missing_targets)}, "
            "source search documents=0"
        )

    result = {
        **preview,
        "mode": "applied",
        "projects_created": len(created_keys),
        "documents_moved": len(to_move),
        "documents_verified": len(assignments),
        "search_entries_copied": len(target_index_documents),
        "search_entries_deleted": len(source_index_ids),
        "source_documents_remaining": len(remaining_source),
        "source_search_entries_remaining": len(remaining_source_index),
        "completed_at": utc_now_iso(),
        "projects": [
            {
                "project_key": group.key,
                "project_id": str(projects[group.key]["project_id"]),
                "project_name": str(projects[group.key]["name"]),
                "document_count": len(group.files),
            }
            for group in groups
        ],
    }
    _write_report(args.report, result)
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "projects"},
            indent=2,
        )
    )
    print(f"Migration complete. Report: {args.report}")


if __name__ == "__main__":
    main()
