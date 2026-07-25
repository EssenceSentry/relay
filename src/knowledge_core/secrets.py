from __future__ import annotations

import json
from threading import Lock
from typing import cast

import boto3
from mypy_boto3_secretsmanager import SecretsManagerClient


class SecretProvider:
    def __init__(self, region_name: str | None = None) -> None:
        self._client: SecretsManagerClient = boto3.client(
            "secretsmanager",
            region_name=region_name,
        )
        self._cache: dict[str, str] = {}
        self._lock = Lock()

    def get(
        self,
        secret_id: str,
        key: str | None = None,
        *,
        use_cache: bool = True,
    ) -> str:
        cache_key = f"{secret_id}#{key or ''}"
        if use_cache:
            with self._lock:
                cached = self._cache.get(cache_key)
                if cached is not None:
                    return cached

        response = self._client.get_secret_value(SecretId=secret_id)
        if "SecretString" not in response:
            raise RuntimeError(f"Secret {secret_id!r} has no SecretString")
        raw = response["SecretString"]

        value = self._extract(raw, key)
        if use_cache:
            with self._lock:
                self._cache[cache_key] = value
        return value

    @staticmethod
    def _extract(raw: str, key: str | None) -> str:
        if key is None:
            try:
                parsed: object = json.loads(raw)
            except json.JSONDecodeError:
                return raw
            if isinstance(parsed, str):
                return parsed
            raise RuntimeError(
                "Secret contains JSON; request a specific key instead"
            )

        try:
            parsed: object = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Secret is not JSON and cannot provide key {key!r}"
            ) from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Secret does not contain string key {key!r}")
        value = cast(dict[object, object], parsed).get(key)
        if not isinstance(value, str):
            raise RuntimeError(f"Secret does not contain string key {key!r}")
        return value
