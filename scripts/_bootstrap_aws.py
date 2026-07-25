from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
from _type_guards import is_string_keyed_dict
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ProfileNotFound


@dataclass(frozen=True)
class StackContext:
    stack_name: str
    outputs: dict[str, Any]


def load_stack_context(path: Path, stack: str | None) -> StackContext:
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise SystemExit(
            f"Outputs file not found: {path}. Deploy the stack first."
        ) from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Outputs file is not valid JSON: {path}") from exc

    if not is_string_keyed_dict(payload) or not payload:
        raise SystemExit(f"Outputs file contains no stacks: {path}")
    if stack is None:
        if len(payload) != 1:
            available = ", ".join(sorted(payload))
            raise SystemExit(
                "More than one stack is present; pass --stack. "
                f"Available: {available}"
            )
        stack = next(iter(payload))
    outputs = payload.get(stack)
    if not is_string_keyed_dict(outputs):
        available = ", ".join(sorted(payload))
        raise SystemExit(f"Unknown stack {stack!r}. Available: {available}")
    return StackContext(stack_name=stack, outputs=outputs)


def infer_region(outputs: dict[str, Any]) -> str | None:
    pool_id = outputs.get("UserPoolId")
    if isinstance(pool_id, str) and "_" in pool_id:
        return pool_id.split("_", 1)[0]
    for value in outputs.values():
        if isinstance(value, str) and value.startswith("arn:"):
            parts = value.split(":", 5)
            if len(parts) > 3 and parts[3]:
                return parts[3]
    return None


def create_session(
    *,
    profile: str | None,
    region: str | None,
    outputs: dict[str, Any],
) -> boto3.Session:
    try:
        return boto3.Session(
            profile_name=profile,
            region_name=region or infer_region(outputs),
        )
    except ProfileNotFound as exc:
        raise SystemExit(f"AWS profile not found: {profile}") from exc


def require_output(context: StackContext, key: str) -> str:
    value = context.outputs.get(key)
    if not isinstance(value, str) or not value:
        available = ", ".join(sorted(context.outputs))
        raise SystemExit(
            f"Missing stack output {key!r}. Available: {available}"
        )
    return value


def resolve_stack_resource(
    *,
    session: boto3.Session,
    stack_name: str,
    resource_type: str,
    logical_id_prefix: str,
) -> str:
    cloudformation = session.client("cloudformation")
    matches: list[str] = []
    paginator = cloudformation.get_paginator("list_stack_resources")
    for page in paginator.paginate(StackName=stack_name):
        for resource in page.get("StackResourceSummaries", []):
            logical_id = str(resource.get("LogicalResourceId", ""))
            physical_id = resource.get("PhysicalResourceId")
            if (
                resource.get("ResourceType") == resource_type
                and logical_id.startswith(logical_id_prefix)
                and isinstance(physical_id, str)
            ):
                matches.append(physical_id)
    if len(matches) != 1:
        rendered = ", ".join(matches) or "none"
        raise SystemExit(
            f"Expected one {resource_type} resource beginning with "
            f"{logical_id_prefix!r} in {stack_name}; found: {rendered}"
        )
    return matches[0]


def resolve_table_name(
    *,
    context: StackContext,
    session: boto3.Session,
    override: str | None,
) -> str:
    if override:
        return override
    output = context.outputs.get("KnowledgeTableName")
    if isinstance(output, str) and output:
        return output
    return resolve_stack_resource(
        session=session,
        stack_name=context.stack_name,
        resource_type="AWS::DynamoDB::Table",
        logical_id_prefix="KnowledgeTable",
    )


def list_projects(table: Any) -> list[dict[str, Any]]:
    projects: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {
        "IndexName": "GSI1",
        "KeyConditionExpression": Key("GSI1PK").eq("ENTITY#PROJECT"),
    }
    while True:
        response = table.query(**kwargs)
        projects.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return projects
        kwargs["ExclusiveStartKey"] = last_key


def get_project(table: Any, project_id: str) -> dict[str, Any] | None:
    response = table.get_item(
        Key={"PK": f"PROJECT#{project_id}", "SK": "META"},
        ConsistentRead=True,
    )
    item = response.get("Item")
    return item if is_string_keyed_dict(item) else None


def find_project_by_name(
    table: Any,
    project_name: str,
) -> dict[str, Any] | None:
    matches = [
        project
        for project in list_projects(table)
        if str(project.get("name", "")).casefold()
        == project_name.strip().casefold()
    ]
    if len(matches) > 1:
        ids = ", ".join(str(item["project_id"]) for item in matches)
        raise SystemExit(
            f"More than one project is named {project_name!r}: {ids}. "
            "Pass --project-id."
        )
    return matches[0] if matches else None
