from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from app.auth import make_principal_dependency
from app.routes import build_api_router
from fastapi import FastAPI, HTTPException

from test_support.http_client import make_test_client


def _container(*, auth_enabled: bool) -> Any:
    return SimpleNamespace(
        settings=SimpleNamespace(
            mcp_auth_enabled=auth_enabled,
            aws_region="us-east-1",
            user_pool_id="us-east-1_example",
            user_pool_client_id="client-id",
        )
    )


def test_public_mode_allows_requests_without_a_bearer_token() -> None:
    dependency = make_principal_dependency(_container(auth_enabled=False))

    principal = dependency(None)

    assert principal.subject == "public-hackathon-user"
    assert principal.email == "public@hackathon.local"
    assert principal.groups == frozenset()
    assert principal.claims == {"authentication_mode": "public"}


def test_authenticated_mode_still_requires_a_bearer_token() -> None:
    dependency = make_principal_dependency(_container(auth_enabled=True))

    with pytest.raises(HTTPException) as error:
        dependency(None)

    assert error.value.status_code == 401
    assert error.value.detail == "Missing bearer token"


def test_public_principal_is_resolved_as_a_route_dependency() -> None:
    container = _container(auth_enabled=False)
    app = FastAPI()
    app.include_router(
        build_api_router(
            container,
            make_principal_dependency(container),
        )
    )

    response = make_test_client(app).get("/api/me")

    assert response.status_code == 200
    assert response.json() == {
        "subject": "public-hackathon-user",
        "email": "public@hackathon.local",
        "groups": [],
        "is_admin": False,
    }
