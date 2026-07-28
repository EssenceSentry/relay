#!/usr/bin/env python3
"""Transfer existing project authorship to one verified Relay identity."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import boto3
from _bootstrap_aws import (
    create_session,
    load_stack_context,
    resolve_table_name,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPOSITORY_ROOT / "src"))

from knowledge_core.dynamo import KnowledgeRepository  # noqa: E402
from knowledge_core.identity import normalize_email  # noqa: E402


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Transfer project authorship to one verified Relay identity. "
            "Every project not already owned by that identity is selected by "
            "default. Dry-run is the default; --apply performs atomic "
            "per-project updates and replaces each previous author membership."
        )
    )
    parser.add_argument("new_author_email")
    parser.add_argument(
        "--previous-author-email",
        action="append",
        default=[],
        help=(
            "Restrict transfers to this current author; may be repeated. "
            "Omit to transfer projects from every current author."
        ),
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--project-id",
        action="append",
        default=[],
        help="Restrict the transfer to this project ID; may be repeated.",
    )
    parser.add_argument(
        "--transferred-by",
        help="Audit actor; defaults to the new author.",
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
    return parser.parse_args()


def main() -> None:
    args = _arguments()
    new_author = normalize_email(args.new_author_email)
    actor = normalize_email(args.transferred_by or new_author)
    previous_authors = frozenset(
        normalize_email(email) for email in args.previous_author_email
    )
    if new_author in previous_authors:
        raise SystemExit(
            "The new author cannot also be a previous-author filter."
        )

    context = load_stack_context(args.outputs_file, args.stack)
    session = create_session(
        profile=args.profile,
        region=args.region,
        outputs=context.outputs,
    )
    region = session.region_name or "us-east-1"
    boto3.setup_default_session(
        profile_name=args.profile,
        region_name=region,
    )
    table_name = resolve_table_name(
        context=context,
        session=session,
        override=args.table_name,
    )
    repository = KnowledgeRepository(table_name, region_name=region)
    new_profile = repository.get_user_profile(new_author)
    if new_profile is None or not new_profile.get("email_verified"):
        raise SystemExit(
            f"New author {new_author!r} is not a verified Relay user."
        )

    selected_ids = set(args.project_id)
    all_projects = repository.list_projects(
        limit=10_000,
        include_archived=True,
    )
    known_ids = {
        str(project.get("project_id") or "") for project in all_projects
    }
    unknown_ids = sorted(selected_ids - known_ids)
    if unknown_ids:
        raise SystemExit("Unknown project IDs: " + ", ".join(unknown_ids))
    scoped_projects = [
        project
        for project in all_projects
        if not selected_ids or str(project.get("project_id")) in selected_ids
    ]
    already_owned = [
        project
        for project in scoped_projects
        if str(project.get("created_by") or "").strip().casefold() == new_author
    ]
    projects = [
        project
        for project in scoped_projects
        if str(project.get("created_by") or "").strip().casefold() != new_author
        and (
            not previous_authors
            or str(project.get("created_by") or "").strip().casefold()
            in previous_authors
        )
    ]
    source_authors = sorted(
        {
            str(project.get("created_by") or "").strip().casefold()
            for project in projects
        }
    )
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(
        f"{mode}: {len(projects)} projects from {len(source_authors)} current "
        f"authors will transfer to {new_author}; "
        f"{len(already_owned)} are already owned by the target."
    )
    for project in projects[:10]:
        print(
            f"  {project['project_id']}: {project['name']} "
            f"({project.get('created_by')} -> {new_author})"
        )
    if len(projects) > 10:
        print(f"  ... and {len(projects) - 10} more")
    if not args.apply:
        print("No records changed. Pass --apply to perform the transfer.")
        return

    changed = 0
    reused = 0
    for index, project in enumerate(projects, start=1):
        previous_author = normalize_email(str(project.get("created_by") or ""))
        _, created = repository.transfer_project_authorship(
            project_id=str(project["project_id"]),
            previous_author_email=previous_author,
            new_author_email=new_author,
            transferred_by=actor,
        )
        if created:
            changed += 1
        else:
            reused += 1
        if index % 50 == 0 or index == len(projects):
            print(f"Transferred {index}/{len(projects)} projects.")
    print(
        "Complete: "
        f"changed={changed}, "
        f"already_owned={len(already_owned)}, "
        f"concurrently_transferred={reused}."
    )


if __name__ == "__main__":
    main()
