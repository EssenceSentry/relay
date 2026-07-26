from __future__ import annotations

import base64
import hashlib
import secrets
import time
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from fastapi import HTTPException
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    TokenError,
)
from mcp.server.auth.settings import (
    AuthSettings,
    ClientRegistrationOptions,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyHttpUrl, AnyUrl

from app.auth import CognitoVerifier, Principal
from app.mcp_oauth_store import McpOAuthStore

MCP_SCOPE = "knowledge:use"
_ACCESS_TOKEN_SECONDS = 60 * 60
_AUTHORIZATION_CODE_SECONDS = 5 * 60
_COGNITO_LOGIN_SECONDS = 10 * 60
_REFRESH_TOKEN_SECONDS = 7 * 24 * 60 * 60


class CognitoMcpSettings(Protocol):
    @property
    def aws_region(self) -> str: ...

    @property
    def user_pool_id(self) -> str: ...

    @property
    def mcp_cognito_client_id(self) -> str: ...

    @property
    def mcp_cognito_domain(self) -> str: ...

    @property
    def mcp_public_base_url(self) -> str: ...


class McpPublicSettings(Protocol):
    @property
    def mcp_public_base_url(self) -> str: ...


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _append_query(url: str, values: dict[str, str]) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(values)
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        )
    )


class CognitoMcpOAuthProvider:
    """MCP OAuth provider that delegates the interactive login to Cognito."""

    def __init__(
        self,
        *,
        store: McpOAuthStore,
        settings: CognitoMcpSettings,
    ) -> None:
        self._store = store
        self._issuer_url = f"{settings.mcp_public_base_url}/"
        self._resource_url = f"{settings.mcp_public_base_url}/mcp/"
        self._callback_url = f"{settings.mcp_public_base_url}/oauth/callback"
        self._cognito_domain = settings.mcp_cognito_domain.rstrip("/")
        self._cognito_client_id = settings.mcp_cognito_client_id
        self._cognito_verifier = CognitoVerifier(
            region=settings.aws_region,
            user_pool_id=settings.user_pool_id,
            client_id=settings.mcp_cognito_client_id,
        )

    async def get_client(
        self,
        client_id: str,
    ) -> OAuthClientInformationFull | None:
        data = self._store.get_client(client_id)
        if data is None:
            return None
        return OAuthClientInformationFull.model_validate(data)

    async def register_client(
        self,
        client_info: OAuthClientInformationFull,
    ) -> None:
        if not client_info.client_id:
            raise ValueError("Registered OAuth clients require a client_id")
        self._store.put_client(
            client_info.client_id,
            client_info.model_dump(mode="json", exclude_none=True),
        )

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        if not client.client_id:
            raise ValueError("OAuth client has no client_id")
        if params.resource and str(params.resource) != self._resource_url:
            from mcp.server.auth.provider import AuthorizeError

            raise AuthorizeError(
                "invalid_request",
                "The requested resource does not match this MCP server.",
            )

        now = int(time.time())
        broker_state = secrets.token_urlsafe(32)
        cognito_verifier = secrets.token_urlsafe(64)
        scopes = params.scopes or [MCP_SCOPE]
        self._store.put_login(
            broker_state,
            {
                "client_id": client.client_id,
                "client_state": params.state,
                "code_challenge": params.code_challenge,
                "redirect_uri": str(params.redirect_uri),
                "redirect_uri_provided_explicitly": (
                    params.redirect_uri_provided_explicitly
                ),
                "resource": str(params.resource or self._resource_url),
                "scopes": scopes,
                "cognito_code_verifier": cognito_verifier,
            },
            expires_at=now + _COGNITO_LOGIN_SECONDS,
        )
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._cognito_client_id,
                "redirect_uri": self._callback_url,
                "scope": "openid email profile",
                "state": broker_state,
                "code_challenge": _pkce_challenge(cognito_verifier),
                "code_challenge_method": "S256",
            }
        )
        return f"{self._cognito_domain}/oauth2/authorize?{query}"

    async def complete_cognito_authorization(
        self,
        *,
        state: str,
        code: str,
    ) -> str:
        pending = self._store.consume_login(state)
        if pending is None:
            raise ValueError("The login request is invalid or has expired.")
        try:
            principal = await self._exchange_cognito_code(
                code=code,
                code_verifier=str(pending["cognito_code_verifier"]),
            )
        except (HTTPException, httpx.HTTPError):
            values = {
                "error": "server_error",
                "error_description": "Cognito authorization failed.",
            }
            client_state = pending.get("client_state")
            if client_state:
                values["state"] = str(client_state)
            return _append_query(str(pending["redirect_uri"]), values)

        now = int(time.time())
        authorization_code = secrets.token_urlsafe(48)
        self._store.put_authorization_code(
            authorization_code,
            {
                "client_id": str(pending["client_id"]),
                "code_challenge": str(pending["code_challenge"]),
                "redirect_uri": str(pending["redirect_uri"]),
                "redirect_uri_provided_explicitly": bool(
                    pending["redirect_uri_provided_explicitly"]
                ),
                "resource": str(pending["resource"]),
                "scopes": list(pending["scopes"]),
                "subject": principal.subject,
                "email": principal.email,
                "groups": sorted(principal.groups),
            },
            expires_at=now + _AUTHORIZATION_CODE_SECONDS,
        )
        values = {"code": authorization_code}
        client_state = pending.get("client_state")
        if client_state:
            values["state"] = str(client_state)
        return _append_query(str(pending["redirect_uri"]), values)

    def reject_cognito_authorization(
        self,
        *,
        state: str,
        error_description: str,
    ) -> str:
        pending = self._store.consume_login(state)
        if pending is None:
            raise ValueError("The login request is invalid or has expired.")
        values = {
            "error": "access_denied",
            "error_description": error_description,
        }
        client_state = pending.get("client_state")
        if client_state:
            values["state"] = str(client_state)
        return _append_query(str(pending["redirect_uri"]), values)

    async def _exchange_cognito_code(
        self,
        *,
        code: str,
        code_verifier: str,
    ) -> Principal:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{self._cognito_domain}/oauth2/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": self._cognito_client_id,
                    "code": code,
                    "redirect_uri": self._callback_url,
                    "code_verifier": code_verifier,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        response.raise_for_status()
        id_token = str(response.json().get("id_token") or "")
        if not id_token:
            raise ValueError("Cognito did not return an ID token.")
        return self._cognito_verifier.verify(id_token)

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        data = self._store.get_authorization_code(authorization_code)
        if data is None or data.get("client_id") != client.client_id:
            return None
        return self._authorization_code(authorization_code, data)

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        data = self._store.consume_authorization_code(authorization_code.code)
        if data is None or data.get("client_id") != client.client_id:
            raise TokenError(
                "invalid_grant",
                "The authorization code was already used or has expired.",
            )
        return self._issue_token_pair(
            client_id=str(data["client_id"]),
            scopes=list(data["scopes"]),
            resource=str(data["resource"]),
            subject=str(data["subject"]),
            email=str(data["email"]),
            groups=list(data.get("groups") or []),
        )

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        data = self._store.get_refresh_token(refresh_token)
        if data is None or data.get("client_id") != client.client_id:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=str(data["client_id"]),
            scopes=list(data["scopes"]),
            expires_at=int(data["expires_at"]),
            subject=str(data["subject"]),
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        data = self._store.consume_refresh_token(refresh_token.token)
        if data is None or data.get("client_id") != client.client_id:
            raise TokenError(
                "invalid_grant",
                "The refresh token was already used or has expired.",
            )
        return self._issue_token_pair(
            client_id=str(data["client_id"]),
            scopes=scopes,
            resource=str(data["resource"]),
            subject=str(data["subject"]),
            email=str(data["email"]),
            groups=list(data.get("groups") or []),
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        return await self.verify_token(token)

    async def verify_token(self, token: str) -> AccessToken | None:
        data = self._store.get_access_token(token)
        if data is not None:
            return AccessToken(
                token=token,
                client_id=str(data["client_id"]),
                scopes=list(data["scopes"]),
                expires_at=int(data["expires_at"]),
                resource=str(data["resource"]),
                subject=str(data["subject"]),
                claims={
                    "iss": self._issuer_url,
                    "email": str(data["email"]),
                    "groups": list(data.get("groups") or []),
                },
            )
        return None

    async def revoke_token(
        self,
        token: AccessToken | RefreshToken,
    ) -> None:
        if isinstance(token, AccessToken):
            self._store.delete_access_token(token.token)
        else:
            self._store.delete_refresh_token(token.token)

    def _authorization_code(
        self,
        code: str,
        data: dict[str, Any],
    ) -> AuthorizationCode:
        return AuthorizationCode(
            code=code,
            scopes=list(data["scopes"]),
            expires_at=float(data["expires_at"]),
            client_id=str(data["client_id"]),
            code_challenge=str(data["code_challenge"]),
            redirect_uri=AnyUrl(str(data["redirect_uri"])),
            redirect_uri_provided_explicitly=bool(
                data["redirect_uri_provided_explicitly"]
            ),
            resource=str(data["resource"]),
            subject=str(data["subject"]),
        )

    def _issue_token_pair(
        self,
        *,
        client_id: str,
        scopes: list[str],
        resource: str,
        subject: str,
        email: str,
        groups: list[str],
    ) -> OAuthToken:
        now = int(time.time())
        access_token = secrets.token_urlsafe(48)
        refresh_token = secrets.token_urlsafe(48)
        access_expires_at = now + _ACCESS_TOKEN_SECONDS
        refresh_expires_at = now + _REFRESH_TOKEN_SECONDS
        common = {
            "client_id": client_id,
            "scopes": scopes,
            "resource": resource,
            "subject": subject,
            "email": email,
            "groups": groups,
        }
        self._store.put_access_token(
            access_token,
            {**common, "expires_at": access_expires_at},
            expires_at=access_expires_at,
        )
        self._store.put_refresh_token(
            refresh_token,
            {**common, "expires_at": refresh_expires_at},
            expires_at=refresh_expires_at,
        )
        return OAuthToken(
            access_token=access_token,
            expires_in=_ACCESS_TOKEN_SECONDS,
            refresh_token=refresh_token,
            scope=" ".join(scopes),
        )


def build_mcp_auth_settings(settings: McpPublicSettings) -> AuthSettings:
    base_url = settings.mcp_public_base_url.rstrip("/")
    return AuthSettings(
        issuer_url=AnyHttpUrl(f"{base_url}/"),
        service_documentation_url=AnyHttpUrl(f"{base_url}/"),
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=[MCP_SCOPE],
            default_scopes=[MCP_SCOPE],
        ),
        required_scopes=[MCP_SCOPE],
        resource_server_url=AnyHttpUrl(f"{base_url}/mcp/"),
    )
