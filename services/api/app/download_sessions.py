from __future__ import annotations

import hashlib
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import boto3

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import (
        DynamoDBServiceResource,
        Table,
    )

_DOWNLOAD_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


def _download_key(token: str) -> str:
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    return f"DOWNLOAD#{digest}"


def _expiry(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, Decimal, str)):
        try:
            return int(value)
        except ValueError:
            return None
    return None


@dataclass(frozen=True, slots=True)
class StoredDownloadSession:
    bucket: str
    key: str
    filename: str
    content_type: str
    expires_at: int


class DownloadSessionStore:
    """DynamoDB-backed capability links for private S3 downloads."""

    def __init__(
        self,
        table_name: str,
        region_name: str | None = None,
        *,
        table: Table | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        if table is None:
            resource: DynamoDBServiceResource = boto3.resource(
                "dynamodb",
                region_name=region_name,
            )
            table = resource.Table(table_name)
        self._table = table
        self._now = now

    def issue(
        self,
        *,
        bucket: str,
        key: str,
        filename: str,
        content_type: str,
        expires_in_seconds: int,
    ) -> str:
        if expires_in_seconds <= 0:
            raise ValueError("Download expiry must be positive")
        token = secrets.token_urlsafe(32)
        self._table.put_item(
            Item={
                "PK": _download_key(token),
                "SK": "META",
                "entity_type": "DOWNLOAD_SESSION",
                "bucket": bucket,
                "key": key,
                "filename": filename,
                "content_type": content_type,
                "expires_at": int(self._now()) + expires_in_seconds,
            },
            ConditionExpression="attribute_not_exists(PK)",
        )
        return token

    def get(self, token: str) -> StoredDownloadSession | None:
        if _DOWNLOAD_TOKEN_PATTERN.fullmatch(token) is None:
            return None
        key = {"PK": _download_key(token), "SK": "META"}
        response = self._table.get_item(Key=key, ConsistentRead=True)
        item = response.get("Item")
        if not item or item.get("entity_type") != "DOWNLOAD_SESSION":
            return None
        expires_at = _expiry(item.get("expires_at"))
        if expires_at is None or expires_at <= int(self._now()):
            self._table.delete_item(Key=key)
            return None
        values = {
            field: item.get(field)
            for field in ("bucket", "key", "filename", "content_type")
        }
        if not all(
            isinstance(value, str) and value for value in values.values()
        ):
            return None
        return StoredDownloadSession(
            bucket=str(values["bucket"]),
            key=str(values["key"]),
            filename=str(values["filename"]),
            content_type=str(values["content_type"]),
            expires_at=expires_at,
        )
