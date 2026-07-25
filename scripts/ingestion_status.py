#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any

from _bootstrap_aws import (
    create_session,
    find_project_by_name,
    get_project,
    load_stack_context,
    resolve_table_name,
)
from boto3.dynamodb.conditions import Key

TERMINAL_STATUSES = {
    "READY",
    "FAILED",
}


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report or wait for DynamoDB document ingestion status."
    )
    project = parser.add_mutually_exclusive_group()
    project.add_argument("--project-id")
    project.add_argument("--project-name")
    parser.add_argument(
        "--report",
        type=Path,
        help=(
            "Initial ingestion report. Uses its project and limits results to "
            "the documents it submitted."
        ),
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Poll until all selected documents are READY or FAILED.",
    )
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--poll-interval", type=float, default=10.0)
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
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def _load_report(path: Path) -> tuple[str, set[str]]:
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise SystemExit(f"Ingestion report not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Ingestion report is invalid JSON: {path}") from exc
    project_id = payload.get("project_id")
    if not isinstance(project_id, str):
        raise SystemExit(f"Report has no project_id: {path}")
    document_ids = {
        item["document_id"]
        for item in payload.get("results", [])
        if isinstance(item.get("document_id"), str)
    }
    return project_id, document_ids


def _list_documents(table: Any, project_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": (
            Key("PK").eq(f"PROJECT#{project_id}")
            & Key("SK").begins_with("DOCUMENT#")
        ),
        "ConsistentRead": True,
    }
    while True:
        response = table.query(**kwargs)
        items.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return items
        kwargs["ExclusiveStartKey"] = last_key


def _snapshot(
    table: Any,
    *,
    project_id: str,
    document_ids: set[str] | None,
) -> list[dict[str, Any]]:
    documents = _list_documents(table, project_id)
    if document_ids is None:
        return documents
    return [
        item
        for item in documents
        if str(item.get("document_id")) in document_ids
    ]


def _counts(documents: list[dict[str, Any]]) -> Counter[str]:
    return Counter(str(item.get("status", "UNKNOWN")) for item in documents)


def _render_counts(counts: Counter[str]) -> str:
    order = [
        "READY",
        "FAILED",
        "PARSING",
        "EMBEDDING",
        "INDEXING",
        "UPLOADING",
        "QUEUED",
        "UNKNOWN",
    ]
    return ", ".join(
        f"{status}={counts[status]}" for status in order if counts[status]
    )


def _result_payload(
    project: dict[str, Any],
    documents: list[dict[str, Any]],
) -> dict[str, Any]:
    counts = _counts(documents)
    failures = [
        {
            "document_id": item.get("document_id"),
            "document_name": item.get("document_name"),
            "error": item.get("error"),
        }
        for item in documents
        if item.get("status") == "FAILED"
    ]
    return {
        "project_id": project["project_id"],
        "project_name": project["name"],
        "total": len(documents),
        "counts": dict(sorted(counts.items())),
        "failures": failures,
    }


def main() -> None:
    args = _arguments()
    if args.timeout <= 0:
        raise SystemExit("--timeout must be greater than zero.")
    if args.poll_interval <= 0:
        raise SystemExit("--poll-interval must be greater than zero.")

    report_project_id: str | None = None
    document_ids: set[str] | None = None
    if args.report:
        report_project_id, document_ids = _load_report(args.report)
    project_id = args.project_id or report_project_id
    if args.project_id and report_project_id != args.project_id and args.report:
        raise SystemExit("--project-id does not match the ingestion report.")

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

    if project_id:
        project = get_project(table, project_id)
    elif args.project_name:
        project = find_project_by_name(table, args.project_name)
    else:
        raise SystemExit(
            "Pass --project-id, --project-name, or an ingestion --report."
        )
    if project is None:
        raise SystemExit("Project not found.")
    project_id = str(project["project_id"])

    deadline = time.monotonic() + args.timeout
    previous: Counter[str] | None = None
    while True:
        documents = _snapshot(
            table,
            project_id=project_id,
            document_ids=document_ids,
        )
        counts = _counts(documents)
        if not args.json and counts != previous:
            print(
                f"{project['name']} ({project_id}): "
                f"{len(documents)} documents; {_render_counts(counts)}"
            )
            previous = counts

        expected_count = (
            len(document_ids) if document_ids is not None else len(documents)
        )
        complete = (
            bool(documents)
            and len(documents) == expected_count
            and all(
                item.get("status") in TERMINAL_STATUSES for item in documents
            )
        )
        if not args.wait or complete:
            break
        if time.monotonic() >= deadline:
            payload = _result_payload(project, documents)
            if args.json:
                print(json.dumps(payload, default=str, indent=2))
            raise SystemExit("Timed out waiting for ingestion.")
        time.sleep(args.poll_interval)

    payload = _result_payload(project, documents)
    if args.json:
        print(json.dumps(payload, default=str, indent=2))
    else:
        for failure in payload["failures"]:
            print(
                f"FAILED {failure['document_name']} "
                f"({failure['document_id']}): {failure['error']}"
            )
    if payload["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
