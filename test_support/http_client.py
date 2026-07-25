from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response


class HttpTestClient(Protocol):
    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Response: ...

    def post(
        self,
        url: str,
        *,
        json: object | None = None,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Response: ...


def make_test_client(app: FastAPI) -> HttpTestClient:
    return TestClient(app)
