from __future__ import annotations

from app.routes import build_api_router
from fastapi import FastAPI

from test_support.http_client import make_test_client


def test_public_browser_answer_routes_are_removed() -> None:
    app = FastAPI()
    app.include_router(
        build_api_router(
            object(),  # pyright: ignore[reportArgumentType]
            lambda: None,
        )
    )
    client = make_test_client(app)

    assert client.get("/api/public/question").status_code == 404
    assert (
        client.post("/api/public/question/answers", json={}).status_code == 404
    )
