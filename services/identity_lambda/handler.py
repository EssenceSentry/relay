from __future__ import annotations

from typing import Any, cast

import boto3

from knowledge_core.dynamo import KnowledgeRepository
from knowledge_core.identity import (
    email_name_tokens,
    normalize_blend_email,
    normalize_email,
    uses_identity_provider,
)
from knowledge_core.notifications import MatchingPublisher
from knowledge_core.settings import IdentitySettings

_SETTINGS = IdentitySettings.from_env()
_REPOSITORY = KnowledgeRepository(
    _SETTINGS.table_name,
    region_name=_SETTINGS.aws_region,
)
_MATCHING = MatchingPublisher(
    queue_url=_SETTINGS.matching_queue_url,
    sqs_client=boto3.client("sqs", region_name=_SETTINGS.aws_region),
)
_COGNITO = boto3.client("cognito-idp", region_name=_SETTINGS.aws_region)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    del context
    request = cast(dict[str, Any], event.get("request") or {})
    attributes = cast(
        dict[str, Any],
        request.get("userAttributes") or {},
    )
    email = normalize_email(str(attributes.get("email") or ""))
    microsoft_identity = uses_identity_provider(attributes, "Microsoft")
    if microsoft_identity:
        # Entra's tenant-controlled preferred_username is mapped to email.
        # Cognito does not mark that mapped attribute as verified itself.
        normalize_blend_email(email)
    if str(attributes.get("email_verified") or "").casefold() != "true":
        if not microsoft_identity:
            raise ValueError("Cognito user email must be verified")
        user_pool_id = str(event.get("userPoolId") or "").strip()
        username = str(event.get("userName") or "").strip()
        if not user_pool_id or not username:
            raise ValueError("Cognito user pool ID and username are required")
        _COGNITO.admin_update_user_attributes(
            UserPoolId=user_pool_id,
            Username=username,
            UserAttributes=[{"Name": "email_verified", "Value": "true"}],
        )
        attributes["email_verified"] = "true"
    if str(event.get("triggerSource") or "").startswith("TokenGeneration_"):
        if microsoft_identity:
            response: dict[str, Any] = event.get("response") or {}
            event["response"] = response
            overrides: dict[str, Any] = (
                response.get("claimsOverrideDetails") or {}
            )
            response["claimsOverrideDetails"] = overrides
            claims: dict[str, Any] = (
                overrides.get("claimsToAddOrOverride") or {}
            )
            overrides["claimsToAddOrOverride"] = claims
            claims["email_verified"] = "true"
        return event
    subject = str(attributes.get("sub") or event.get("userName") or "").strip()
    if not subject:
        raise ValueError("Cognito user subject is missing")
    display_name = str(attributes.get("name") or "").strip()
    if not display_name:
        display_name = " ".join(
            token.title() for token in email_name_tokens(email)
        )
    identity_source = "MICROSOFT_SSO" if microsoft_identity else "COGNITO"
    _REPOSITORY.put_user_profile(
        subject=subject,
        email=email,
        display_name=display_name,
        identity_source=identity_source,
        email_verified=True,
    )
    if email in _SETTINGS.initial_admin_emails:
        user_pool_id = str(event.get("userPoolId") or "").strip()
        if not user_pool_id:
            raise ValueError("Cognito user pool ID is missing")
        _COGNITO.admin_add_user_to_group(
            UserPoolId=user_pool_id,
            Username=str(event.get("userName") or email),
            GroupName="admins",
        )
    _MATCHING.user_verified(email)
    return event
