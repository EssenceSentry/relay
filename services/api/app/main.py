from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import make_principal_dependency
from app.mcp_oauth import CognitoMcpOAuthProvider, build_mcp_auth_settings
from app.mcp_server import (
    build_mcp_asgi_app,
    build_mcp_server,
)
from app.routes import build_api_router
from app.services import ServiceContainer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

container = ServiceContainer()
oauth_provider = None
auth_settings = None
if container.settings.mcp_auth_enabled:
    oauth_provider = CognitoMcpOAuthProvider(
        store=container.oauth_store,
        settings=container.settings,
    )
    auth_settings = build_mcp_auth_settings(container.settings)
else:
    logging.getLogger(__name__).warning(
        "MCP authentication is disabled; all MCP tools are publicly accessible"
    )
mcp = build_mcp_server(
    container,
    oauth_provider=oauth_provider,
    auth_settings=auth_settings,
)
mcp_asgi = build_mcp_asgi_app(mcp)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    del app
    async with mcp.session_manager.run():
        yield


app = FastAPI(
    title="Blend Project Knowledge API",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id"],
)
principal_dependency = make_principal_dependency(container)
app.include_router(build_api_router(container, principal_dependency))


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}


app.mount("/", mcp_asgi)
