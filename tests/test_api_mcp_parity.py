from __future__ import annotations

import asyncio

from app.mcp_server import build_mcp_server
from app.routes import build_api_router
from fastapi.routing import APIRoute

from tests.test_mcp_server import EXPECTED_V1_TOOLS


def test_authenticated_api_and_mcp_have_explicit_operation_parity() -> None:
    router = build_api_router(
        object(),  # pyright: ignore[reportArgumentType]
        lambda: None,
    )
    api_operations = {
        route.name
        for route in router.routes
        if isinstance(route, APIRoute) and route.include_in_schema
    }
    mcp_operations = {
        tool.name
        for tool in asyncio.run(
            build_mcp_server(
                object(),  # type: ignore[arg-type]
            ).list_tools()
        )
    }

    assert api_operations == EXPECTED_V1_TOOLS
    assert mcp_operations == EXPECTED_V1_TOOLS
