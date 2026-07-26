from __future__ import annotations

import asyncio
import base64
import hashlib
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit

from app.auth import Principal
from app.mcp_oauth import (
    MCP_SCOPE,
    CognitoMcpOAuthProvider,
    build_mcp_auth_settings,
)
from app.mcp_server import build_mcp_asgi_app, build_mcp_server
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from mcp.server.auth.provider import (
    AuthorizationParams,
)
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl


class FakeOAuthStore:
    def __init__(self) -> None:
        self.clients: dict[str, dict[str, Any]] = {}
        self.logins: dict[str, dict[str, Any]] = {}
        self.codes: dict[str, dict[str, Any]] = {}
        self.access_tokens: dict[str, dict[str, Any]] = {}
        self.refresh_tokens: dict[str, dict[str, Any]] = {}

    def put_client(self, client_id: str, data: dict[str, Any]) -> None:
        self.clients[client_id] = data

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        return self.clients.get(client_id)

    def put_login(
        self,
        state: str,
        data: dict[str, Any],
        *,
        expires_at: int,
    ) -> None:
        self.logins[state] = {**data, "expires_at": expires_at}

    def consume_login(self, state: str) -> dict[str, Any] | None:
        return self.logins.pop(state, None)

    def put_authorization_code(
        self,
        code: str,
        data: dict[str, Any],
        *,
        expires_at: int,
    ) -> None:
        self.codes[code] = {**data, "expires_at": expires_at}

    def get_authorization_code(self, code: str) -> dict[str, Any] | None:
        return self.codes.get(code)

    def consume_authorization_code(
        self,
        code: str,
    ) -> dict[str, Any] | None:
        return self.codes.pop(code, None)

    def put_access_token(
        self,
        token: str,
        data: dict[str, Any],
        *,
        expires_at: int,
    ) -> None:
        self.access_tokens[token] = {**data, "expires_at": expires_at}

    def get_access_token(self, token: str) -> dict[str, Any] | None:
        return self.access_tokens.get(token)

    def delete_access_token(self, token: str) -> None:
        self.access_tokens.pop(token, None)

    def put_refresh_token(
        self,
        token: str,
        data: dict[str, Any],
        *,
        expires_at: int,
    ) -> None:
        self.refresh_tokens[token] = {**data, "expires_at": expires_at}

    def get_refresh_token(self, token: str) -> dict[str, Any] | None:
        return self.refresh_tokens.get(token)

    def consume_refresh_token(self, token: str) -> dict[str, Any] | None:
        return self.refresh_tokens.pop(token, None)

    def delete_refresh_token(self, token: str) -> None:
        self.refresh_tokens.pop(token, None)


@dataclass(frozen=True)
class OAuthSettings:
    aws_region: str = "us-east-1"
    user_pool_id: str = "us-east-1_example"
    mcp_cognito_client_id: str = "cognito-client"
    mcp_cognito_domain: str = "https://login.example.com"
    mcp_public_base_url: str = "https://d111111abcdef8.cloudfront.net"


def _settings() -> OAuthSettings:
    return OAuthSettings()


class StubOAuthProvider(CognitoMcpOAuthProvider):
    async def _exchange_cognito_code(
        self,
        *,
        code: str,
        code_verifier: str,
    ) -> Principal:
        assert code == "cognito-code"
        assert len(code_verifier) >= 43
        return Principal(
            subject="user-123",
            email="person@example.com",
            groups=frozenset(),
            claims={},
        )


def _provider(store: FakeOAuthStore) -> StubOAuthProvider:
    return StubOAuthProvider(
        store=store,  # type: ignore[arg-type]
        settings=_settings(),  # type: ignore[arg-type]
    )


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


async def _request(
    app: FastAPI,
    method: str,
    path: str,
    **kwargs: Any,
) -> Response:
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        return await client.request(method, path, **kwargs)


def test_oauth_discovery_and_mcp_challenge_are_exposed() -> None:
    store = FakeOAuthStore()
    provider = _provider(store)
    settings = build_mcp_auth_settings(_settings())  # type: ignore[arg-type]
    mcp = build_mcp_server(
        object(),  # type: ignore[arg-type]
        oauth_provider=provider,
        auth_settings=settings,
    )
    app = FastAPI()
    app.mount("/", build_mcp_asgi_app(mcp))

    authorization_metadata = asyncio.run(
        _request(
            app,
            "GET",
            "/.well-known/oauth-authorization-server",
        )
    )
    protected_resource = asyncio.run(
        _request(
            app,
            "GET",
            "/.well-known/oauth-protected-resource/mcp/",
        )
    )
    challenge = asyncio.run(_request(app, "POST", "/mcp/"))
    registration = asyncio.run(
        _request(
            app,
            "POST",
            "/register",
            json={
                "redirect_uris": ["https://client.example/callback"],
                "token_endpoint_auth_method": "client_secret_post",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "scope": MCP_SCOPE,
                "client_name": "Test client",
            },
        )
    )

    assert authorization_metadata.status_code == 200
    assert authorization_metadata.json()["registration_endpoint"].endswith(
        "/register"
    )
    assert authorization_metadata.json()[
        "code_challenge_methods_supported"
    ] == ["S256"]
    assert protected_resource.status_code == 200
    assert protected_resource.json()["resource"].endswith("/mcp/")
    assert challenge.status_code == 401
    assert (
        'resource_metadata="https://d111111abcdef8.cloudfront.net/'
        '.well-known/oauth-protected-resource/mcp/"'
        in challenge.headers["www-authenticate"]
    )
    assert registration.status_code == 201
    assert registration.json()["client_id"] in store.clients
    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    assert tools["search_project_knowledge"].meta == {
        "securitySchemes": [
            {
                "type": "oauth2",
                "scopes": [MCP_SCOPE],
            }
        ]
    }


def test_dynamic_registration_and_cognito_authorization_flow() -> None:
    store = FakeOAuthStore()
    provider = _provider(store)
    client = OAuthClientInformationFull(
        client_id="client-123",
        client_secret="client-secret",
        redirect_uris=[AnyUrl("https://client.example/callback")],
        token_endpoint_auth_method="client_secret_post",
        scope=MCP_SCOPE,
    )
    asyncio.run(provider.register_client(client))
    params = AuthorizationParams(
        state="client-state",
        scopes=[MCP_SCOPE],
        code_challenge="client-pkce-challenge",
        redirect_uri=AnyUrl("https://client.example/callback"),
        redirect_uri_provided_explicitly=True,
        resource="https://d111111abcdef8.cloudfront.net/mcp/",
    )

    cognito_url = asyncio.run(provider.authorize(client, params))
    broker_state = parse_qs(urlsplit(cognito_url).query)["state"][0]
    mcp = build_mcp_server(
        object(),  # type: ignore[arg-type]
        oauth_provider=provider,
        auth_settings=build_mcp_auth_settings(  # type: ignore[arg-type]
            _settings()
        ),
    )
    app = FastAPI()
    app.mount("/", build_mcp_asgi_app(mcp))
    callback = asyncio.run(
        _request(
            app,
            "GET",
            f"/oauth/callback?state={broker_state}&code=cognito-code",
        )
    )
    assert callback.status_code == 302
    client_redirect = callback.headers["location"]
    redirect_query = parse_qs(urlsplit(client_redirect).query)
    authorization_code_value = redirect_query["code"][0]
    authorization_code = asyncio.run(
        provider.load_authorization_code(
            client,
            authorization_code_value,
        )
    )

    assert redirect_query["state"] == ["client-state"]
    assert authorization_code is not None
    assert authorization_code.expires_at > time.time()
    tokens = asyncio.run(
        provider.exchange_authorization_code(client, authorization_code)
    )
    access = asyncio.run(provider.verify_token(tokens.access_token))
    refresh = asyncio.run(
        provider.load_refresh_token(client, str(tokens.refresh_token))
    )

    assert access is not None
    assert access.subject == "user-123"
    assert access.scopes == [MCP_SCOPE]
    assert refresh is not None
    refreshed = asyncio.run(
        provider.exchange_refresh_token(client, refresh, [MCP_SCOPE])
    )
    assert refreshed.access_token != tokens.access_token
    assert (
        asyncio.run(provider.load_refresh_token(client, refresh.token)) is None
    )


def test_http_oauth_flow_issues_an_access_token() -> None:
    store = FakeOAuthStore()
    provider = _provider(store)
    mcp = build_mcp_server(
        object(),  # type: ignore[arg-type]
        oauth_provider=provider,
        auth_settings=build_mcp_auth_settings(  # type: ignore[arg-type]
            _settings()
        ),
    )
    app = FastAPI()
    app.mount("/", build_mcp_asgi_app(mcp))
    registration = asyncio.run(
        _request(
            app,
            "POST",
            "/register",
            json={
                "redirect_uris": ["https://client.example/callback"],
                "token_endpoint_auth_method": "client_secret_post",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "scope": MCP_SCOPE,
                "client_name": "Test client",
            },
        )
    ).json()
    verifier = "a" * 64
    authorization = asyncio.run(
        _request(
            app,
            "GET",
            "/authorize",
            params={
                "response_type": "code",
                "client_id": registration["client_id"],
                "redirect_uri": "https://client.example/callback",
                "scope": MCP_SCOPE,
                "state": "client-state",
                "resource": ("https://d111111abcdef8.cloudfront.net/mcp/"),
                "code_challenge": _challenge(verifier),
                "code_challenge_method": "S256",
            },
        )
    )
    broker_state = parse_qs(urlsplit(authorization.headers["location"]).query)[
        "state"
    ][0]
    callback = asyncio.run(
        _request(
            app,
            "GET",
            f"/oauth/callback?state={broker_state}&code=cognito-code",
        )
    )
    authorization_code = parse_qs(urlsplit(callback.headers["location"]).query)[
        "code"
    ][0]
    token = asyncio.run(
        _request(
            app,
            "POST",
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": registration["client_id"],
                "client_secret": registration["client_secret"],
                "code": authorization_code,
                "redirect_uri": "https://client.example/callback",
                "code_verifier": verifier,
                "resource": ("https://d111111abcdef8.cloudfront.net/mcp/"),
            },
        )
    )

    assert authorization.status_code == 302
    assert callback.status_code == 302
    assert token.status_code == 200
    access = asyncio.run(provider.verify_token(token.json()["access_token"]))
    assert access is not None
    assert access.subject == "user-123"


def test_cognito_cancel_returns_to_the_mcp_client() -> None:
    store = FakeOAuthStore()
    provider = _provider(store)
    client = OAuthClientInformationFull(
        client_id="client-123",
        client_secret="client-secret",
        redirect_uris=[AnyUrl("https://client.example/callback")],
        token_endpoint_auth_method="client_secret_post",
        scope=MCP_SCOPE,
    )
    params = AuthorizationParams(
        state="client-state",
        scopes=[MCP_SCOPE],
        code_challenge="client-pkce-challenge",
        redirect_uri=AnyUrl("https://client.example/callback"),
        redirect_uri_provided_explicitly=True,
        resource="https://d111111abcdef8.cloudfront.net/mcp/",
    )
    cognito_url = asyncio.run(provider.authorize(client, params))
    broker_state = parse_qs(urlsplit(cognito_url).query)["state"][0]
    mcp = build_mcp_server(
        object(),  # type: ignore[arg-type]
        oauth_provider=provider,
        auth_settings=build_mcp_auth_settings(  # type: ignore[arg-type]
            _settings()
        ),
    )
    app = FastAPI()
    app.mount("/", build_mcp_asgi_app(mcp))

    callback = asyncio.run(
        _request(
            app,
            "GET",
            (
                f"/oauth/callback?state={broker_state}"
                "&error=access_denied&error_description=Cancelled"
            ),
        )
    )

    assert callback.status_code == 302
    query = parse_qs(urlsplit(callback.headers["location"]).query)
    assert query["error"] == ["access_denied"]
    assert query["state"] == ["client-state"]
