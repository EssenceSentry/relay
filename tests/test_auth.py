from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import app.auth as auth_module
import pytest
from app.auth import (
    CognitoVerifier,
    Principal,
    make_principal_dependency,
    with_configured_admin,
)
from fastapi import HTTPException
from jwt import PyJWKClient


class FakeSigningKey:
    key = "public-key"


class FakeSigningKeyClient(PyJWKClient):
    def __init__(self) -> None:
        pass

    def get_signing_key_from_jwt(self, token: str | bytes) -> Any:
        assert token == "valid-token"
        return FakeSigningKey()


def _container(*, auth_enabled: bool) -> Any:
    return SimpleNamespace(
        settings=SimpleNamespace(
            mcp_auth_enabled=auth_enabled,
            aws_region="us-east-1",
            user_pool_id="us-east-1_example",
            user_pool_client_id="client-id",
            allowed_login_email_domains=frozenset(
                {"blend360.com", "gmail.com"}
            ),
            initial_admin_emails=frozenset({"essence.sentry@gmail.com"}),
        )
    )


def test_public_mode_is_rejected_by_contract_v1() -> None:
    with pytest.raises(
        RuntimeError,
        match="Authentication is required",
    ):
        make_principal_dependency(_container(auth_enabled=False))


def test_authenticated_mode_still_requires_a_bearer_token() -> None:
    dependency = make_principal_dependency(_container(auth_enabled=True))

    with pytest.raises(HTTPException) as error:
        dependency(None)

    assert error.value.status_code == 401
    assert error.value.detail == "Missing bearer token"


def _verifier(monkeypatch: pytest.MonkeyPatch, claims: dict[str, Any]):
    verifier = CognitoVerifier(
        region="us-east-1",
        user_pool_id="us-east-1_example",
        client_id="client-id",
        allowed_email_domains=frozenset({"blend360.com", "gmail.com"}),
    )
    verifier._jwk_client = FakeSigningKeyClient()  # pyright: ignore[reportPrivateUsage]

    def decode(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        return claims

    monkeypatch.setattr(auth_module.jwt, "decode", decode)
    return verifier


def test_cognito_verifier_requires_verified_allowed_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unverified = _verifier(
        monkeypatch,
        {
            "sub": "user-1",
            "email": "person@blend360.com",
            "email_verified": False,
            "token_use": "id",
        },
    )
    with pytest.raises(HTTPException) as unverified_error:
        unverified.verify("valid-token")
    assert unverified_error.value.status_code == 403

    external = _verifier(
        monkeypatch,
        {
            "sub": "user-1",
            "email": "person@example.com",
            "email_verified": True,
            "token_use": "id",
        },
    )
    with pytest.raises(HTTPException) as external_error:
        external.verify("valid-token")
    assert external_error.value.status_code == 403


def test_cognito_verifier_accepts_verified_gmail_for_demo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = _verifier(
        monkeypatch,
        {
            "sub": "user-2",
            "email": "Essence_Sentry@Gmail.COM",
            "email_verified": True,
            "token_use": "id",
        },
    )

    principal = verifier.verify("valid-token")

    assert principal.email == "essence_sentry@gmail.com"
    assert not principal.is_admin


def test_cognito_verifier_returns_groups_and_normalized_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = _verifier(
        monkeypatch,
        {
            "sub": "user-1",
            "email": "Person@Blend360.COM",
            "email_verified": "true",
            "token_use": "id",
            "cognito:groups": ["admins"],
        },
    )

    principal = verifier.verify("valid-token")

    assert principal.email == "person@blend360.com"
    assert principal.is_admin


def test_configured_admin_email_repairs_a_stale_group_claim() -> None:
    principal = Principal(
        subject="user-2",
        email="essence.sentry@gmail.com",
        groups=frozenset(),
        claims={"token_source": "stale-oauth-record"},
    )

    effective = with_configured_admin(
        principal,
        frozenset({"essence.sentry@gmail.com"}),
    )

    assert effective.is_admin
    assert effective.groups == frozenset({"admins"})
    assert effective.claims == principal.claims
