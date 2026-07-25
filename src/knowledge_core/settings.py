from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean value, got {raw!r}")


def _common_values(common: CommonSettings) -> dict[str, Any]:
    return {
        field: getattr(common, field)
        for field in CommonSettings.__dataclass_fields__
    }


def _email_values() -> dict[str, Any]:
    enabled = env_bool("EMAIL_ENABLED", False)
    from_address = os.environ.get("SES_FROM_ADDRESS") or None
    reply_domain = os.environ.get("SES_REPLY_DOMAIN") or None
    application_base_url = os.environ.get("APPLICATION_BASE_URL") or None
    if enabled:
        for name, value in (
            ("SES_FROM_ADDRESS", from_address),
            ("SES_REPLY_DOMAIN", reply_domain),
            ("APPLICATION_BASE_URL", application_base_url),
        ):
            if not value:
                raise RuntimeError(
                    f"Missing required environment variable when email is enabled: {name}"
                )
    return {
        "email_enabled": enabled,
        "ses_from_address": from_address,
        "ses_reply_domain": reply_domain,
        "application_base_url": application_base_url,
    }


@dataclass(frozen=True, slots=True)
class CommonSettings:
    aws_region: str
    table_name: str
    document_bucket: str
    opensearch_endpoint: str
    opensearch_index: str
    openai_secret_arn: str
    embedding_model: str
    embedding_dimensions: int

    @classmethod
    def from_env(cls) -> CommonSettings:
        return cls(
            aws_region=os.environ.get("AWS_REGION", "us-east-1"),
            table_name=required_env("TABLE_NAME"),
            document_bucket=required_env("DOCUMENT_BUCKET"),
            opensearch_endpoint=required_env("OPENSEARCH_ENDPOINT"),
            opensearch_index=required_env("OPENSEARCH_INDEX"),
            openai_secret_arn=required_env("OPENAI_SECRET_ARN"),
            embedding_model=os.environ.get(
                "EMBEDDING_MODEL",
                "text-embedding-3-large",
            ),
            embedding_dimensions=int(
                os.environ.get("EMBEDDING_DIMENSIONS", "1536")
            ),
        )


@dataclass(frozen=True, slots=True)
class IngestionSettings(CommonSettings):
    document_processing_model: str
    ingestion_queue_url: str

    @classmethod
    def from_env(cls) -> IngestionSettings:
        common = CommonSettings.from_env()
        return cls(
            **_common_values(common),
            document_processing_model=os.environ.get(
                "DOCUMENT_PROCESSING_MODEL",
                "gpt-5.4-mini",
            ),
            ingestion_queue_url=required_env("INGESTION_QUEUE_URL"),
        )


@dataclass(frozen=True, slots=True)
class ApiSettings(CommonSettings):
    user_pool_id: str
    user_pool_client_id: str
    mcp_auth_enabled: bool
    mcp_cognito_client_id: str
    mcp_cognito_domain: str
    mcp_public_base_url: str
    max_upload_bytes: int
    email_enabled: bool
    ses_from_address: str | None
    ses_reply_domain: str | None
    application_base_url: str | None

    @classmethod
    def from_env(cls) -> ApiSettings:
        common = CommonSettings.from_env()
        return cls(
            **_common_values(common),
            user_pool_id=required_env("USER_POOL_ID"),
            user_pool_client_id=required_env("USER_POOL_CLIENT_ID"),
            mcp_auth_enabled=env_bool("MCP_AUTH_ENABLED", True),
            mcp_cognito_client_id=required_env("MCP_COGNITO_CLIENT_ID"),
            mcp_cognito_domain=required_env("MCP_COGNITO_DOMAIN").rstrip("/"),
            mcp_public_base_url=required_env("MCP_PUBLIC_BASE_URL").rstrip("/"),
            max_upload_bytes=int(
                os.environ.get("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024))
            ),
            **_email_values(),
        )


@dataclass(frozen=True, slots=True)
class ReviewSettings(CommonSettings):
    review_model: str
    email_enabled: bool
    ses_from_address: str | None
    ses_reply_domain: str | None
    application_base_url: str | None

    @classmethod
    def from_env(cls) -> ReviewSettings:
        common = CommonSettings.from_env()
        return cls(
            **_common_values(common),
            review_model=os.environ.get("REVIEW_MODEL", "gpt-5-mini"),
            **_email_values(),
        )


@dataclass(frozen=True, slots=True)
class InboundEmailSettings:
    aws_region: str
    table_name: str
    inbound_bucket: str
    inbound_prefix: str
    reply_domain: str
    max_answer_chars: int

    @classmethod
    def from_env(cls) -> InboundEmailSettings:
        return cls(
            aws_region=os.environ.get("AWS_REGION", "us-east-1"),
            table_name=required_env("TABLE_NAME"),
            inbound_bucket=required_env("INBOUND_EMAIL_BUCKET"),
            inbound_prefix=os.environ.get("INBOUND_EMAIL_PREFIX", "inbound/"),
            reply_domain=required_env("SES_REPLY_DOMAIN").casefold(),
            max_answer_chars=int(
                os.environ.get("MAX_EMAIL_ANSWER_CHARS", "20000")
            ),
        )
