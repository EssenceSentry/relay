from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from pydantic import TypeAdapter, ValidationError

from app.services import ServiceContainer
from knowledge_core.identity import email_name_tokens, normalize_email


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    email: str
    groups: frozenset[str]
    claims: dict[str, Any]

    @property
    def is_admin(self) -> bool:
        return "admins" in self.groups


def with_configured_admin(
    principal: Principal,
    configured_admin_emails: frozenset[str],
) -> Principal:
    """Apply durable email-configured admin access to a verified principal."""
    if principal.is_admin or principal.email not in configured_admin_emails:
        return principal
    return Principal(
        subject=principal.subject,
        email=principal.email,
        groups=principal.groups | {"admins"},
        claims=principal.claims,
    )


class CognitoVerifier:
    def __init__(
        self,
        *,
        region: str,
        user_pool_id: str,
        client_id: str,
        allowed_email_domains: frozenset[str],
    ) -> None:
        if not allowed_email_domains:
            raise ValueError("At least one login email domain is required")
        self._issuer = (
            f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        )
        self._client_id = client_id
        self._allowed_email_domains = allowed_email_domains
        self._jwk_client = PyJWKClient(f"{self._issuer}/.well-known/jwks.json")

    def verify(self, token: str) -> Principal:
        try:
            signing_key = self._jwk_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._client_id,
                issuer=self._issuer,
                options={
                    "require": ["exp", "iat", "sub", "aud"],
                },
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired Cognito token",
            ) from exc
        if claims.get("token_use") != "id":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Use the Cognito ID token for this API",
            )
        raw_email = str(claims.get("email") or "")
        if not raw_email:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="The authenticated user has no email claim",
            )
        email_verified = claims.get("email_verified")
        if not (
            email_verified is True
            or str(email_verified).strip().casefold() == "true"
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="The authenticated email has not been verified",
            )
        try:
            email = normalize_email(raw_email)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="The authenticated email address is invalid",
            ) from exc
        email_domain = email.rsplit("@", maxsplit=1)[1]
        if email_domain not in self._allowed_email_domains:
            allowed = ", ".join(
                f"@{domain}" for domain in sorted(self._allowed_email_domains)
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Sign-in requires a verified email from: {allowed}",
            )

        # TEMPORARY HACKATHON DEMO HACK:
        # The deployed demo adds gmail.com because Blend360 quarantines the
        # Cognito verification email. Production must remove that deployment
        # flag and use the planned Blend Microsoft SSO identity provider.
        raw_groups: object = claims.get("cognito:groups") or []
        groups: frozenset[str]
        try:
            groups = frozenset(
                _STRING_LIST_ADAPTER.validate_python(
                    raw_groups,
                    strict=True,
                )
            )
        except ValidationError:
            groups = frozenset()
        return Principal(
            subject=str(claims["sub"]),
            email=email,
            groups=groups,
            claims=dict(claims),
        )


_bearer = HTTPBearer(auto_error=False)
_STRING_LIST_ADAPTER = TypeAdapter(list[str])


def make_principal_dependency(
    container: ServiceContainer,
):
    if not container.settings.mcp_auth_enabled:
        raise RuntimeError(
            "Authentication is required; unauthenticated public mode was "
            "removed in API/MCP contract v1"
        )

    verifier = CognitoVerifier(
        region=container.settings.aws_region,
        user_pool_id=container.settings.user_pool_id,
        client_id=container.settings.user_pool_client_id,
        allowed_email_domains=(container.settings.allowed_login_email_domains),
    )

    def current_principal(
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Depends(_bearer),
        ],
    ) -> Principal:
        if credentials is None or credentials.scheme.casefold() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing bearer token",
            )
        principal = with_configured_admin(
            verifier.verify(credentials.credentials),
            container.settings.initial_admin_emails,
        )
        existing = container.repository.get_user_profile(principal.email)
        display_name = str(principal.claims.get("name") or "").strip()
        if not display_name:
            display_name = " ".join(
                token.title() for token in email_name_tokens(principal.email)
            )
        identity_source = (
            "MICROSOFT_SSO"
            if str(principal.claims.get("cognito:username") or "").startswith(
                "Microsoft_"
            )
            or bool(principal.claims.get("identities"))
            else str((existing or {}).get("identity_source") or "COGNITO")
        )
        if existing is None or any(
            (
                str(existing.get("subject") or "") != principal.subject,
                str(existing.get("display_name") or "") != display_name,
                str(existing.get("identity_source") or "") != identity_source,
            )
        ):
            container.repository.put_user_profile(
                subject=principal.subject,
                email=principal.email,
                display_name=display_name,
                identity_source=identity_source,
                email_verified=True,
            )
        if existing is None:
            container.matching.user_verified(principal.email)
        return principal

    return current_principal
