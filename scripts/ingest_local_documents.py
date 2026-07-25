#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import random
import re
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from _bootstrap_aws import (
    create_session,
    find_project_by_name,
    get_project,
    load_stack_context,
    require_output,
    resolve_table_name,
)
from _type_guards import is_string_keyed_dict
from botocore.exceptions import ClientError

DEFAULT_EXTENSIONS = (
    ".pdf",
    ".doc",
    ".docx",
    ".pptx",
    ".txt",
    ".md",
    ".csv",
    ".json",
)
DEFAULT_MAX_BYTES = 25 * 1024 * 1024
DEFAULT_SEED = 20260725
STATUS_UPLOADING = "UPLOADING"
STATUS_FAILED = "FAILED"
_SAFE_COMPONENT = re.compile(r"[^a-zA-Z0-9._-]+")
CONTENT_TYPES = {
    ".doc": "application/msword",
    ".docx": (
        "application/vnd.openxmlformats-officedocument."
        "wordprocessingml.document"
    ),
    ".pptx": (
        "application/vnd.openxmlformats-officedocument."
        "presentationml.presentation"
    ),
    ".md": "text/markdown",
}


def _utc_now_iso() -> str:
    return (
        datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _safe_filename(filename: str) -> str:
    name = Path(filename).name.strip()
    if not name:
        return "document"
    cleaned = _SAFE_COMPONENT.sub("-", name).strip(".-")
    return cleaned[:180] or "document"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Provision a project and upload a reproducible sample of local "
            "documents directly with boto3. S3 events start normal ingestion."
        )
    )
    parser.add_argument(
        "source",
        nargs="?",
        type=Path,
        default=Path("PIH - Dataset"),
        help="Local directory to scan recursively (default: PIH - Dataset).",
    )
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--extensions",
        default=",".join(DEFAULT_EXTENSIONS),
        help="Comma-separated allowed extensions.",
    )
    project = parser.add_mutually_exclusive_group()
    project.add_argument("--project-id", help="Use an existing project.")
    project.add_argument(
        "--project-name",
        help=(
            "Reuse or create a project with this name. Defaults to the source "
            "directory name."
        ),
    )
    parser.add_argument("--project-description")
    parser.add_argument(
        "--uploaded-by",
        default=os.environ.get("EMAIL", "local-bootstrap"),
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Re-upload deterministic document IDs currently marked FAILED.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Select and display files without calling AWS.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("initial-ingestion-report.json"),
    )
    parser.add_argument(
        "--profile",
        default=os.environ.get("AWS_PROFILE"),
        help="AWS profile (defaults to AWS_PROFILE or the default chain).",
    )
    parser.add_argument("--region", default=os.environ.get("AWS_REGION"))
    parser.add_argument(
        "--outputs-file",
        type=Path,
        default=Path("cdk-outputs.json"),
    )
    parser.add_argument("--stack", help="Stack key in the CDK outputs file.")
    parser.add_argument(
        "--table-name", help="Override the DynamoDB table name."
    )
    parser.add_argument(
        "--upload-delay",
        type=float,
        default=0.1,
        help="Seconds between uploads (default: 0.1).",
    )
    return parser.parse_args()


def parse_extensions(value: str) -> frozenset[str]:
    extensions = {
        item.strip().casefold()
        if item.strip().startswith(".")
        else f".{item.strip().casefold()}"
        for item in value.split(",")
        if item.strip()
    }
    unsupported = extensions.difference(DEFAULT_EXTENSIONS)
    if unsupported:
        rendered = ", ".join(sorted(unsupported))
        raise SystemExit(f"Unsupported extensions requested: {rendered}")
    if not extensions:
        raise SystemExit("At least one extension is required.")
    return frozenset(extensions)


def eligible_files(
    source: Path,
    *,
    extensions: frozenset[str],
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> list[Path]:
    files = [
        path
        for path in source.rglob("*")
        if path.is_file()
        and path.suffix.casefold() in extensions
        and 0 < path.stat().st_size <= max_bytes
    ]
    return sorted(
        files,
        key=lambda path: path.relative_to(source).as_posix().casefold(),
    )


def select_files(
    files: list[Path],
    *,
    count: int,
    seed: int,
) -> list[Path]:
    if count <= 0:
        raise SystemExit("--count must be greater than zero.")
    if count >= len(files):
        return files
    return random.Random(seed).sample(files, count)


def _content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _document_id(project_id: str, content_hash: str) -> str:
    digest = hashlib.sha256(
        f"{project_id}\x1f{content_hash}".encode()
    ).hexdigest()
    return f"doc_{digest[:32]}"


def _content_type(path: Path) -> str:
    return (
        CONTENT_TYPES.get(path.suffix.casefold())
        or mimetypes.guess_type(path.name)[0]
        or "application/octet-stream"
    )


def _create_project(
    table: Any,
    *,
    name: str,
    description: str | None,
    created_by: str,
) -> dict[str, Any]:
    project_id = _new_id("prj")
    now = _utc_now_iso()
    item = {
        "PK": f"PROJECT#{project_id}",
        "SK": "META",
        "GSI1PK": "ENTITY#PROJECT",
        "GSI1SK": f"{now}#{project_id}",
        "entity_type": "PROJECT",
        "project_id": project_id,
        "name": name.strip(),
        "description": (description or "").strip() or None,
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
    }
    stored = {key: value for key, value in item.items() if value is not None}
    table.put_item(
        Item=stored,
        ConditionExpression="attribute_not_exists(PK)",
    )
    return stored


def _resolve_project(
    table: Any,
    *,
    project_id: str | None,
    project_name: str,
    project_description: str | None,
    created_by: str,
) -> tuple[dict[str, Any], bool]:
    if project_id:
        project = get_project(table, project_id)
        if project is None:
            raise SystemExit(f"Project not found: {project_id}")
        return project, False
    project = find_project_by_name(table, project_name)
    if project is not None:
        return project, False
    return (
        _create_project(
            table,
            name=project_name,
            description=project_description,
            created_by=created_by,
        ),
        True,
    )


def _get_document(
    table: Any,
    *,
    project_id: str,
    document_id: str,
) -> dict[str, Any] | None:
    response = table.get_item(
        Key={
            "PK": f"PROJECT#{project_id}",
            "SK": f"DOCUMENT#{document_id}",
        },
        ConsistentRead=True,
    )
    item = response.get("Item")
    return item if is_string_keyed_dict(item) else None


def _create_document(
    table: Any,
    *,
    project_id: str,
    document_id: str,
    document_name: str,
    bucket: str,
    key: str,
    content_type: str,
    size_bytes: int,
    uploaded_by: str,
) -> None:
    now = _utc_now_iso()
    table.put_item(
        Item={
            "PK": f"PROJECT#{project_id}",
            "SK": f"DOCUMENT#{document_id}",
            "entity_type": "DOCUMENT",
            "project_id": project_id,
            "document_id": document_id,
            "document_version": "1",
            "document_name": document_name,
            "s3_bucket": bucket,
            "s3_key": key,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "status": STATUS_UPLOADING,
            "source_type": "UPLOADED",
            "uploaded_by": uploaded_by,
            "created_at": now,
            "updated_at": now,
        },
        ConditionExpression="attribute_not_exists(SK)",
    )


def _reset_failed_document(
    table: Any,
    *,
    project_id: str,
    document_id: str,
) -> None:
    table.update_item(
        Key={
            "PK": f"PROJECT#{project_id}",
            "SK": f"DOCUMENT#{document_id}",
        },
        UpdateExpression=(
            "SET #status = :status, updated_at = :updated REMOVE #error"
        ),
        ExpressionAttributeNames={
            "#status": "status",
            "#error": "error",
        },
        ExpressionAttributeValues={
            ":status": STATUS_UPLOADING,
            ":updated": _utc_now_iso(),
        },
    )


def _mark_upload_failed(
    table: Any,
    *,
    project_id: str,
    document_id: str,
    error: Exception,
) -> None:
    table.update_item(
        Key={
            "PK": f"PROJECT#{project_id}",
            "SK": f"DOCUMENT#{document_id}",
        },
        UpdateExpression=(
            "SET #status = :status, updated_at = :updated, #error = :error"
        ),
        ExpressionAttributeNames={
            "#status": "status",
            "#error": "error",
        },
        ExpressionAttributeValues={
            ":status": STATUS_FAILED,
            ":updated": _utc_now_iso(),
            ":error": f"{type(error).__name__}: {error}"[:4000],
        },
    )


def _upload_one(
    *,
    path: Path,
    source: Path,
    table: Any,
    s3: Any,
    bucket: str,
    project_id: str,
    uploaded_by: str,
    retry_failed: bool,
) -> dict[str, Any]:
    content_hash = _content_hash(path)
    document_id = _document_id(project_id, content_hash)
    filename = _safe_filename(path.name)
    key = f"uploads/{project_id}/{document_id}/{filename}"
    relative_path = path.relative_to(source).as_posix()
    existing = _get_document(
        table,
        project_id=project_id,
        document_id=document_id,
    )
    if existing is not None:
        status = str(existing.get("status", "UNKNOWN"))
        if status != STATUS_FAILED or not retry_failed:
            return {
                "path": relative_path,
                "document_id": document_id,
                "status": "skipped",
                "existing_status": status,
            }
        key = str(existing.get("s3_key") or key)
        _reset_failed_document(
            table,
            project_id=project_id,
            document_id=document_id,
        )
    else:
        try:
            _create_document(
                table,
                project_id=project_id,
                document_id=document_id,
                document_name=path.name,
                bucket=bucket,
                key=key,
                content_type=_content_type(path),
                size_bytes=path.stat().st_size,
                uploaded_by=uploaded_by,
            )
        except ClientError as exc:
            error = exc.response.get("Error", {})
            if error.get("Code") != "ConditionalCheckFailedException":
                raise
            return {
                "path": relative_path,
                "document_id": document_id,
                "status": "skipped",
                "existing_status": "RACE",
            }

    try:
        s3.upload_file(
            str(path),
            bucket,
            key,
            ExtraArgs={
                "ContentType": _content_type(path),
                "Metadata": {
                    "project-id": project_id,
                    "document-id": document_id,
                },
                "ServerSideEncryption": "AES256",
            },
        )
    except Exception as exc:
        _mark_upload_failed(
            table,
            project_id=project_id,
            document_id=document_id,
            error=exc,
        )
        return {
            "path": relative_path,
            "document_id": document_id,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "path": relative_path,
        "document_id": document_id,
        "status": "uploaded",
        "s3_key": key,
    }


def _print_selection(source: Path, selected: Iterable[Path]) -> None:
    for path in selected:
        size_mib = path.stat().st_size / (1024 * 1024)
        print(f"- {path.relative_to(source)} ({size_mib:.2f} MiB)")


def main() -> None:
    args = _arguments()
    source = args.source.expanduser().resolve()
    if not source.is_dir():
        raise SystemExit(f"Source directory not found: {source}")
    if args.upload_delay < 0:
        raise SystemExit("--upload-delay cannot be negative.")

    extensions = parse_extensions(args.extensions)
    files = eligible_files(source, extensions=extensions)
    if not files:
        raise SystemExit(
            f"No eligible files found in {source} for "
            f"{', '.join(sorted(extensions))}."
        )
    selected = select_files(files, count=args.count, seed=args.seed)
    print(
        f"Selected {len(selected)} of {len(files)} eligible files "
        f"with seed {args.seed}:"
    )
    _print_selection(source, selected)
    if args.dry_run:
        print("Dry run complete; no AWS resources were changed.")
        return

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
    bucket = require_output(context, "DocumentBucketName")
    table = session.resource("dynamodb").Table(table_name)
    s3 = session.client("s3")

    project_name = args.project_name or source.name
    project, created = _resolve_project(
        table,
        project_id=args.project_id,
        project_name=project_name,
        project_description=args.project_description,
        created_by=args.uploaded_by,
    )
    project_id = str(project["project_id"])
    project_action = "Created" if created else "Using"
    print(
        f"{project_action} project {project['name']!r} "
        f"({project_id}); uploading to {bucket}."
    )

    started_at = _utc_now_iso()
    results: list[dict[str, Any]] = []
    for index, path in enumerate(selected, start=1):
        result = _upload_one(
            path=path,
            source=source,
            table=table,
            s3=s3,
            bucket=bucket,
            project_id=project_id,
            uploaded_by=args.uploaded_by,
            retry_failed=args.retry_failed,
        )
        results.append(result)
        print(f"[{index}/{len(selected)}] {result['status']}: {result['path']}")
        if index < len(selected) and args.upload_delay:
            time.sleep(args.upload_delay)

    report = {
        "stack": context.stack_name,
        "region": session.region_name,
        "source": str(source),
        "seed": args.seed,
        "requested_count": args.count,
        "eligible_count": len(files),
        "project_id": project_id,
        "project_name": project["name"],
        "started_at": started_at,
        "completed_at": _utc_now_iso(),
        "results": results,
    }
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    counts = {
        status: sum(item["status"] == status for item in results)
        for status in ("uploaded", "skipped", "failed")
    }
    print(
        f"Submitted {counts['uploaded']}; skipped {counts['skipped']}; "
        f"upload failures {counts['failed']}."
    )
    print(f"Report: {args.report}")
    print(
        "Monitor ingestion with: "
        f"uv run python scripts/ingestion_status.py --project-id {project_id} "
        f"--report {args.report} --wait"
    )
    if counts["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
