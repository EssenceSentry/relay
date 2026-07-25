from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from pydantic import TypeAdapter, ValidationError

from app.services import ServiceContainer


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    email: str
    groups: frozenset[str]
    claims: dict[str, Any]

    @property
    def is_admin(self) -> bool:
        return "admins" in self.groups


class CognitoVerifier:
    def __init__(
        self,
        *,
        region: str,
        user_pool_id: str,
        client_id: str,
    ) -> None:
        self._issuer = (
            f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        )
        self._client_id = client_id
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
        email = str(claims.get("email") or "").strip().casefold()
        if not email:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="The authenticated user has no email claim",
            )
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
_PUBLIC_PRINCIPAL = Principal(
    subject="public-hackathon-user",
    email="public@hackathon.local",
    groups=frozenset(),
    claims={"authentication_mode": "public"},
)


def make_principal_dependency(
    container: ServiceContainer,
):
    if not container.settings.mcp_auth_enabled:

        def public_principal(
            credentials: Annotated[
                HTTPAuthorizationCredentials | None,
                Depends(_bearer),
            ],
        ) -> Principal:
            del credentials
            return _PUBLIC_PRINCIPAL

        return public_principal

    verifier = CognitoVerifier(
        region=container.settings.aws_region,
        user_pool_id=container.settings.user_pool_id,
        client_id=container.settings.user_pool_client_id,
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
        return verifier.verify(credentials.credentials)

    return current_principal
