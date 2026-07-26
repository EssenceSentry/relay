from __future__ import annotations

from typing import Any, cast

import boto3

from knowledge_core.dynamo import KnowledgeRepository
from knowledge_core.identity import email_name_tokens, normalize_email
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
    if str(attributes.get("email_verified") or "").casefold() != "true":
        raise ValueError("Cognito user email must be verified")
    subject = str(attributes.get("sub") or event.get("userName") or "").strip()
    if not subject:
        raise ValueError("Cognito user subject is missing")
    display_name = str(attributes.get("name") or "").strip()
    if not display_name:
        display_name = " ".join(
            token.title() for token in email_name_tokens(email)
        )
    username = str(event.get("userName") or "")
    identity_source = (
        "MICROSOFT_SSO" if username.startswith("Microsoft_") else "COGNITO"
    )
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
