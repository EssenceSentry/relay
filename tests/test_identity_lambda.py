from __future__ import annotations

import json
import runpy
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import boto3
import pytest

from knowledge_core.dynamo import KnowledgeRepository
from knowledge_core.notifications import MatchingPublisher


@pytest.fixture
def identity_handler(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("TABLE_NAME", "test-table")
    monkeypatch.setenv("MATCHING_QUEUE_URL", "https://queue.example/test")
    monkeypatch.setenv("INITIAL_ADMIN_EMAILS", "")
    monkeypatch.setattr(boto3, "client", Mock(return_value=Mock()))
    monkeypatch.setattr(
        KnowledgeRepository, "__init__", Mock(return_value=None)
    )
    monkeypatch.setattr(MatchingPublisher, "__init__", Mock(return_value=None))
    namespace = runpy.run_path(
        str(
            Path(__file__).parents[1]
            / "services"
            / "identity_lambda"
            / "handler.py"
        )
    )
    handler = namespace["lambda_handler"]
    handler.__globals__["_REPOSITORY"] = Mock()
    handler.__globals__["_MATCHING"] = Mock()
    return handler.__globals__


def _event(
    *,
    trigger: str = "PostConfirmation_ConfirmSignUp",
    verified: bool = False,
    microsoft: bool = True,
    email: str = "person@blend360.com",
) -> dict[str, Any]:
    attributes = {
        "email": email,
        "email_verified": str(verified).lower(),
        "sub": "subject-1",
        "name": "Person",
    }
    if microsoft:
        attributes["identities"] = json.dumps(
            [{"providerName": "Microsoft", "providerType": "OIDC"}]
        )
    return {
        "triggerSource": trigger,
        "userPoolId": "us-east-1_test",
        "userName": "Microsoft_subject-1",
        "request": {"userAttributes": attributes},
        "response": {},
    }


def test_confirmed_microsoft_identity_verifies_mapped_email(
    identity_handler: dict[str, Any],
) -> None:
    event = _event()
    result = identity_handler["lambda_handler"](event, None)

    identity_handler[
        "_COGNITO"
    ].admin_update_user_attributes.assert_called_once_with(
        UserPoolId="us-east-1_test",
        Username="Microsoft_subject-1",
        UserAttributes=[{"Name": "email_verified", "Value": "true"}],
    )
    assert result["request"]["userAttributes"]["email_verified"] == "true"
    profile = identity_handler["_REPOSITORY"].put_user_profile.call_args.kwargs
    assert profile["identity_source"] == "MICROSOFT_SSO"
    assert profile["email_verified"] is True
    identity_handler["_MATCHING"].user_verified.assert_called_once_with(
        "person@blend360.com"
    )


@pytest.mark.parametrize(
    ("trigger", "verified"),
    [
        ("TokenGeneration_HostedAuth", False),
        ("TokenGeneration_RefreshTokens", True),
    ],
)
def test_sso_token_generation_verifies_email_without_replaying_signup(
    identity_handler: dict[str, Any], trigger: str, verified: bool
) -> None:
    event = _event(trigger=trigger, verified=verified)
    event["response"] = {
        "claimsOverrideDetails": {
            "claimsToAddOrOverride": {"existing": "preserved"}
        }
    }
    result = identity_handler["lambda_handler"](event, None)

    assert result["response"]["claimsOverrideDetails"][
        "claimsToAddOrOverride"
    ] == {"existing": "preserved", "email_verified": "true"}
    assert identity_handler[
        "_COGNITO"
    ].admin_update_user_attributes.call_count == (0 if verified else 1)
    identity_handler["_REPOSITORY"].put_user_profile.assert_not_called()
    identity_handler["_MATCHING"].user_verified.assert_not_called()


@pytest.mark.parametrize("microsoft", [False, True])
def test_email_verification_does_not_trust_username_or_other_domains(
    identity_handler: dict[str, Any], microsoft: bool
) -> None:
    event = _event(
        microsoft=microsoft,
        email="person@gmail.com" if microsoft else "person@blend360.com",
    )

    with pytest.raises(ValueError):
        identity_handler["lambda_handler"](event, None)

    identity_handler[
        "_COGNITO"
    ].admin_update_user_attributes.assert_not_called()
    identity_handler["_REPOSITORY"].put_user_profile.assert_not_called()


def test_native_verified_identity_keeps_existing_behavior(
    identity_handler: dict[str, Any],
) -> None:
    identity_handler["lambda_handler"](
        _event(microsoft=False, verified=True), None
    )

    identity_handler[
        "_COGNITO"
    ].admin_update_user_attributes.assert_not_called()
    profile = identity_handler["_REPOSITORY"].put_user_profile.call_args.kwargs
    assert profile["identity_source"] == "COGNITO"


@pytest.mark.parametrize(
    "response",
    [
        None,
        {"claimsOverrideDetails": None},
        {"claimsOverrideDetails": {"claimsToAddOrOverride": None}},
    ],
)
def test_token_generation_accepts_cognito_null_response_fields(
    identity_handler: dict[str, Any], response: Any
) -> None:
    event = _event(trigger="TokenGeneration_HostedAuth", verified=True)
    event["response"] = response

    result = identity_handler["lambda_handler"](event, None)

    assert result["response"]["claimsOverrideDetails"][
        "claimsToAddOrOverride"
    ] == {"email_verified": "true"}
