from __future__ import annotations

import hashlib
import time
from decimal import Decimal
from typing import TYPE_CHECKING, Any, TypeGuard

import boto3

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import (
        DynamoDBServiceResource,
        Table,
    )


def _token_key(kind: str, token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"OAUTH#{kind}#{digest}"


def _client_key(client_id: str) -> str:
    return f"OAUTH#CLIENT#{client_id}"


def _is_record(value: object) -> TypeGuard[dict[str, Any]]:
    # Records in this table are created by this service with string keys.
    return isinstance(value, dict)


def _expiry(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, Decimal, str)):
        try:
            return int(value)
        except ValueError:
            return None
    return None


class McpOAuthStore:
    """Small DynamoDB-backed store for MCP OAuth clients and opaque tokens."""

    def __init__(self, table_name: str, region_name: str | None = None) -> None:
        resource: DynamoDBServiceResource = boto3.resource(
            "dynamodb",
            region_name=region_name,
        )
        self._table: Table = resource.Table(table_name)

    def _put(
        self,
        *,
        pk: str,
        entity_type: str,
        data: dict[str, Any],
        expires_at: int | None = None,
    ) -> None:
        item: dict[str, Any] = {
            "PK": pk,
            "SK": "META",
            "entity_type": entity_type,
            "data": data,
        }
        if expires_at is not None:
            item["expires_at"] = expires_at
        self._table.put_item(Item=item)

    def _get(self, pk: str) -> dict[str, Any] | None:
        response = self._table.get_item(
            Key={"PK": pk, "SK": "META"},
            ConsistentRead=True,
        )
        if "Item" not in response:
            return None
        item = response["Item"]
        expires_at = _expiry(item.get("expires_at"))
        if expires_at is not None and expires_at < int(time.time()):
            self._table.delete_item(Key={"PK": pk, "SK": "META"})
            return None
        stored_data = item.get("data")
        if not _is_record(stored_data):
            return None
        data = dict(stored_data)
        if expires_at is not None:
            data["expires_at"] = expires_at
        return data

    def _consume(self, pk: str) -> dict[str, Any] | None:
        response = self._table.delete_item(
            Key={"PK": pk, "SK": "META"},
            ReturnValues="ALL_OLD",
        )
        if "Attributes" not in response:
            return None
        item = response["Attributes"]
        expires_at = _expiry(item.get("expires_at"))
        if expires_at is not None and expires_at < int(time.time()):
            return None
        stored_data = item.get("data")
        if not _is_record(stored_data):
            return None
        data = dict(stored_data)
        if expires_at is not None:
            data["expires_at"] = expires_at
        return data

    def put_client(self, client_id: str, data: dict[str, Any]) -> None:
        self._put(
            pk=_client_key(client_id),
            entity_type="OAUTH_CLIENT",
            data=data,
        )

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        return self._get(_client_key(client_id))

    def put_login(
        self,
        state: str,
        data: dict[str, Any],
        *,
        expires_at: int,
    ) -> None:
        self._put(
            pk=_token_key("LOGIN", state),
            entity_type="OAUTH_LOGIN",
            data=data,
            expires_at=expires_at,
        )

    def consume_login(self, state: str) -> dict[str, Any] | None:
        return self._consume(_token_key("LOGIN", state))

    def put_authorization_code(
        self,
        code: str,
        data: dict[str, Any],
        *,
        expires_at: int,
    ) -> None:
        self._put(
            pk=_token_key("CODE", code),
            entity_type="OAUTH_CODE",
            data=data,
            expires_at=expires_at,
        )

    def get_authorization_code(self, code: str) -> dict[str, Any] | None:
        return self._get(_token_key("CODE", code))

    def consume_authorization_code(
        self,
        code: str,
    ) -> dict[str, Any] | None:
        return self._consume(_token_key("CODE", code))

    def put_access_token(
        self,
        token: str,
        data: dict[str, Any],
        *,
        expires_at: int,
    ) -> None:
        self._put(
            pk=_token_key("ACCESS", token),
            entity_type="OAUTH_ACCESS_TOKEN",
            data=data,
            expires_at=expires_at,
        )

    def get_access_token(self, token: str) -> dict[str, Any] | None:
        return self._get(_token_key("ACCESS", token))

    def delete_access_token(self, token: str) -> None:
        self._table.delete_item(
            Key={"PK": _token_key("ACCESS", token), "SK": "META"}
        )

    def put_refresh_token(
        self,
        token: str,
        data: dict[str, Any],
        *,
        expires_at: int,
    ) -> None:
        self._put(
            pk=_token_key("REFRESH", token),
            entity_type="OAUTH_REFRESH_TOKEN",
            data=data,
            expires_at=expires_at,
        )

    def get_refresh_token(self, token: str) -> dict[str, Any] | None:
        return self._get(_token_key("REFRESH", token))

    def consume_refresh_token(self, token: str) -> dict[str, Any] | None:
        return self._consume(_token_key("REFRESH", token))

    def delete_refresh_token(self, token: str) -> None:
        self._table.delete_item(
            Key={"PK": _token_key("REFRESH", token), "SK": "META"}
        )
