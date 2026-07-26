#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

import boto3
from _bootstrap_aws import (
    infer_region,
    load_stack_context,
    require_output,
)

from knowledge_core.collaboration import CollaborationDiscovery
from knowledge_core.dynamo import KnowledgeRepository
from knowledge_core.models import DocumentEnhancementResult
from knowledge_core.notifications import (
    MatchingPublisher,
    NotificationPublisher,
)
from knowledge_core.openai_api import OpenAIService
from knowledge_core.opensearch import OpenSearchServerlessClient
from knowledge_core.secrets import SecretProvider


class DeferredMatchingPublisher:
    def candidate_created(self, evidence: dict[str, object]) -> None:
        del evidence


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract contributor metadata from existing enhanced Markdown. "
            "Dry-run is the default; --apply stores evidence, creates exact-"
            "email collaborators, and queues their notifications."
        )
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--match-existing",
        action="store_true",
        help=(
            "Queue already stored contributor evidence for name matching. "
            "Requires --apply and does not call document extraction."
        ),
    )
    parser.add_argument("--project-id")
    parser.add_argument("--limit", type=int, default=100)
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
    parser.add_argument(
        "--document-model",
        default="gpt-5.4-mini",
    )
    return parser.parse_args()


def main() -> None:
    args = _arguments()
    if args.limit <= 0:
        raise SystemExit("--limit must be positive")
    if args.match_existing and not args.apply:
        raise SystemExit("--match-existing requires --apply")

    context = load_stack_context(args.outputs_file, args.stack)
    region = args.region or infer_region(context.outputs) or "us-east-1"
    boto3.setup_default_session(
        profile_name=args.profile,
        region_name=region,
    )
    table_name = require_output(context, "KnowledgeTableName")
    bucket_name = require_output(context, "DocumentBucketName")
    matching_queue_url = require_output(context, "MatchingQueueUrl")
    notification_queue_url = require_output(context, "NotificationQueueUrl")
    openai_secret_arn = require_output(context, "OpenAISecretArn")
    opensearch_endpoint = require_output(context, "OpenSearchEndpoint")
    application_url = str(
        context.outputs.get("FrontendUrl") or "https://essencesentry.shop/"
    )

    repository = KnowledgeRepository(table_name, region_name=region)
    sqs = boto3.client("sqs", region_name=region)
    matching = MatchingPublisher(
        queue_url=matching_queue_url,
        sqs_client=sqs,
    )
    if args.match_existing:
        queued = _queue_existing(
            repository=repository,
            matching=matching,
            project_id=args.project_id,
            limit=args.limit,
        )
        print(f"Queued {queued} stored contributor evidence records.")
        return

    secret = SecretProvider(region_name=region).get(
        openai_secret_arn,
        "api_key",
    )
    openai = OpenAIService(
        api_key=secret,
        embedding_model="text-embedding-3-large",
        embedding_dimensions=1536,
        document_model=args.document_model,
    )
    search = OpenSearchServerlessClient(
        endpoint=opensearch_endpoint,
        region=region,
        index_name="knowledge-documents-v1",
        dimensions=1536,
    )
    notifications = NotificationPublisher(
        repository=repository,
        queue_url=notification_queue_url,
        sqs_client=sqs,
    )
    discovery = CollaborationDiscovery(
        repository=repository,
        notifications=notifications,
        matching=DeferredMatchingPublisher(),
        application_base_url=application_url,
    )
    s3 = boto3.client("s3", region_name=region)

    processed = 0
    for project in repository.list_projects():
        project_id = str(project["project_id"])
        if args.project_id and project_id != args.project_id:
            continue
        for document in repository.list_documents(project_id):
            if processed >= args.limit:
                break
            if document.get("contributor_extraction_version"):
                continue
            markdown = _document_markdown(
                document=document,
                bucket_name=bucket_name,
                s3=s3,
                search=search,
            )
            if not markdown:
                print(
                    f"SKIP {project_id}/{document['document_id']}: "
                    "no Markdown or indexed text"
                )
                continue
            extraction = openai.extract_contributors_from_markdown(
                filename=str(document["document_name"]),
                markdown=markdown,
            )
            emails = ", ".join(extraction.blend360_emails) or "none"
            names = ", ".join(
                candidate.display_name
                for candidate in extraction.contributors
            ) or "none"
            print(
                f"{'APPLY' if args.apply else 'DRY-RUN'} "
                f"{project_id}/{document['document_id']}: "
                f"emails=[{emails}] contributors=[{names}]"
            )
            if args.apply:
                discovery.record_document_enhancement(
                    project_id=project_id,
                    document_id=str(document["document_id"]),
                    document_name=str(document["document_name"]),
                    extracted_text=markdown,
                    result=DocumentEnhancementResult(
                        markdown=markdown,
                        contributors=extraction.contributors,
                        blend360_emails=extraction.blend360_emails,
                    ),
                    locator="consolidated Markdown backfill",
                )
            processed += 1
        if processed >= args.limit:
            break
    print(f"Processed {processed} documents.")


def _queue_existing(
    *,
    repository: KnowledgeRepository,
    matching: MatchingPublisher,
    project_id: str | None,
    limit: int,
) -> int:
    queued = 0
    for project in repository.list_projects():
        current_project_id = str(project["project_id"])
        if project_id and current_project_id != project_id:
            continue
        for evidence in repository.list_author_evidence(current_project_id):
            matching.candidate_created(evidence)
            queued += 1
            if queued >= limit:
                return queued
    return queued


def _document_markdown(
    *,
    document: dict[str, Any],
    bucket_name: str,
    s3: Any,
    search: OpenSearchServerlessClient,
) -> str:
    enhanced_key = document.get("enhanced_s3_key")
    if isinstance(enhanced_key, str) and enhanced_key:
        response = s3.get_object(Bucket=bucket_name, Key=enhanced_key)
        return response["Body"].read().decode("utf-8")
    records = search.get_indexed_documents(
        project_id=str(document["project_id"]),
        document_id=str(document["document_id"]),
        size=1000,
    )
    return "\n\n".join(
        str(record.get("text") or "").strip()
        for record in records
        if str(record.get("text") or "").strip()
    )


if __name__ == "__main__":
    main()
