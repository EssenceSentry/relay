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


def _load_report(path: Path) -> dict[str, set[str]]:
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise SystemExit(f"Ingestion report not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Ingestion report is invalid JSON: {path}") from exc
    root_project_id = payload.get("project_id")
    selections: dict[str, set[str]] = {}
    for item in payload.get("results", []):
        document_id = item.get("document_id")
        project_id = item.get("project_id", root_project_id)
        if isinstance(document_id, str) and isinstance(project_id, str):
            selections.setdefault(project_id, set()).add(document_id)
    if not selections:
        raise SystemExit(f"Report has no project documents: {path}")
    return selections


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


def _combined_result_payload(
    payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    failures: list[dict[str, Any]] = []
    for payload in payloads:
        counts.update(payload["counts"])
        failures.extend(payload["failures"])
    return {
        "projects": payloads,
        "total": sum(int(payload["total"]) for payload in payloads),
        "counts": dict(sorted(counts.items())),
        "failures": failures,
    }


def _selection_complete(
    documents: list[dict[str, Any]],
    document_ids: set[str] | None,
) -> bool:
    expected_count = (
        len(document_ids) if document_ids is not None else len(documents)
    )
    return (
        bool(documents)
        and len(documents) == expected_count
        and all(item.get("status") in TERMINAL_STATUSES for item in documents)
    )


def main() -> None:
    args = _arguments()
    if args.timeout <= 0:
        raise SystemExit("--timeout must be greater than zero.")
    if args.poll_interval <= 0:
        raise SystemExit("--poll-interval must be greater than zero.")

    report_selections = _load_report(args.report) if args.report else {}
    if (
        args.project_id
        and report_selections
        and args.project_id not in report_selections
    ):
        raise SystemExit("--project-id is not present in the ingestion report.")

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

    projects: dict[str, dict[str, Any]] = {}
    selections: dict[str, set[str] | None] = {}
    if args.project_id:
        project = get_project(table, args.project_id)
        if project is not None:
            projects[args.project_id] = project
            selections[args.project_id] = report_selections.get(args.project_id)
    elif args.project_name:
        project = find_project_by_name(table, args.project_name)
        if project is not None:
            project_id = str(project["project_id"])
            projects[project_id] = project
            selections[project_id] = report_selections.get(project_id)
    elif report_selections:
        for project_id, document_ids in report_selections.items():
            project = get_project(table, project_id)
            if project is None:
                raise SystemExit(f"Project not found: {project_id}")
            projects[project_id] = project
            selections[project_id] = document_ids
    else:
        raise SystemExit(
            "Pass --project-id, --project-name, or an ingestion --report."
        )
    if not projects:
        raise SystemExit("Project not found.")

    deadline = time.monotonic() + args.timeout
    previous: dict[str, Counter[str]] = {}
    while True:
        documents_by_project = {
            project_id: _snapshot(
                table,
                project_id=project_id,
                document_ids=selections[project_id],
            )
            for project_id in projects
        }
        if not args.json:
            for project_id, documents in documents_by_project.items():
                counts = _counts(documents)
                if counts != previous.get(project_id):
                    print(
                        f"{projects[project_id]['name']} ({project_id}): "
                        f"{len(documents)} documents; {_render_counts(counts)}"
                    )
                    previous[project_id] = counts

        complete = all(
            _selection_complete(
                documents,
                selections[project_id],
            )
            for project_id, documents in documents_by_project.items()
        )
        if not args.wait or complete:
            break
        if time.monotonic() >= deadline:
            payloads = [
                _result_payload(
                    projects[project_id],
                    documents,
                )
                for project_id, documents in documents_by_project.items()
            ]
            payload = (
                payloads[0]
                if len(payloads) == 1
                else _combined_result_payload(payloads)
            )
            if args.json:
                print(json.dumps(payload, default=str, indent=2))
            raise SystemExit("Timed out waiting for ingestion.")
        time.sleep(args.poll_interval)

    payloads = [
        _result_payload(projects[project_id], documents)
        for project_id, documents in documents_by_project.items()
    ]
    payload = (
        payloads[0]
        if len(payloads) == 1
        else _combined_result_payload(payloads)
    )
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
