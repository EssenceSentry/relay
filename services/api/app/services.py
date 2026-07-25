from __future__ import annotations

from functools import cached_property

import boto3

from app.mcp_oauth_store import McpOAuthStore
from knowledge_core.dynamo import KnowledgeRepository
from knowledge_core.email_service import SesEmailService
from knowledge_core.openai_api import OpenAIService
from knowledge_core.opensearch import OpenSearchServerlessClient
from knowledge_core.question_workflow import QuestionWorkflow
from knowledge_core.retrieval import RetrievalService
from knowledge_core.secrets import SecretProvider
from knowledge_core.settings import ApiSettings


class ServiceContainer:
    def __init__(self, settings: ApiSettings | None = None) -> None:
        self.settings = settings or ApiSettings.from_env()

    @cached_property
    def repository(self) -> KnowledgeRepository:
        return KnowledgeRepository(
            self.settings.table_name,
            region_name=self.settings.aws_region,
        )

    @cached_property
    def oauth_store(self) -> McpOAuthStore:
        return McpOAuthStore(
            self.settings.table_name,
            region_name=self.settings.aws_region,
        )

    @cached_property
    def secrets(self) -> SecretProvider:
        return SecretProvider(region_name=self.settings.aws_region)

    @cached_property
    def openai(self) -> OpenAIService:
        return OpenAIService(
            api_key=self.secrets.get(
                self.settings.openai_secret_arn,
                "api_key",
            ),
            embedding_model=self.settings.embedding_model,
            embedding_dimensions=self.settings.embedding_dimensions,
        )

    @cached_property
    def search(self) -> OpenSearchServerlessClient:
        return OpenSearchServerlessClient(
            endpoint=self.settings.opensearch_endpoint,
            region=self.settings.aws_region,
            index_name=self.settings.opensearch_index,
            dimensions=self.settings.embedding_dimensions,
            timeout_seconds=5.0,
            max_attempts=3,
        )

    @cached_property
    def retrieval(self) -> RetrievalService:
        return RetrievalService(openai=self.openai, search=self.search)

    @cached_property
    def email_sender(self) -> SesEmailService | None:
        if not self.settings.email_enabled:
            return None
        assert self.settings.ses_from_address is not None
        assert self.settings.application_base_url is not None
        return SesEmailService(
            region_name=self.settings.aws_region,
            from_address=self.settings.ses_from_address,
            application_base_url=self.settings.application_base_url,
        )

    @cached_property
    def questions(self) -> QuestionWorkflow:
        return QuestionWorkflow(
            repository=self.repository,
            email_sender=self.email_sender,
            reply_domain=self.settings.ses_reply_domain,
        )

    @cached_property
    def s3(self):
        return boto3.client("s3", region_name=self.settings.aws_region)
