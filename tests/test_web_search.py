from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.routes import build_api_router
from fastapi import FastAPI

from knowledge_core.models import GlobalSearchResponse, SearchHit
from test_support.http_client import make_test_client


class FakeRetrieval:
    def search_across_projects(
        self,
        *,
        query: str,
        top_k: int,
    ) -> GlobalSearchResponse:
        assert query == "snowflake migration"
        assert top_k == 20
        return GlobalSearchResponse(
            query=query,
            hits=[
                SearchHit(
                    index_id="idx_1",
                    project_id="prj_1",
                    document_id="doc_1",
                    document_name="Modernization overview.pptx",
                    source_type="UPLOADED",
                    text="Reduced operational overhead through a phased migration.",
                    page_number=4,
                    page_count=8,
                    rrf_score=0.03,
                )
            ],
        )


class FakeRepository:
    def list_projects(self) -> list[dict[str, Any]]:
        return [
            {
                "project_id": "prj_1",
                "name": "Snowflake modernization",
                "description": "Cloud data platform migration",
            }
        ]

    def get_document(
        self,
        *,
        project_id: str,
        document_id: str,
    ) -> dict[str, Any] | None:
        assert project_id == "prj_1"
        assert document_id == "doc_1"
        return {
            "project_id": project_id,
            "document_id": document_id,
            "enhanced_s3_key": "extracted/prj_1/doc_1/document.md",
        }


def test_web_search_returns_project_context_and_download_availability() -> None:
    container = SimpleNamespace(
        retrieval=FakeRetrieval(),
        repository=FakeRepository(),
    )
    app = FastAPI()
    app.include_router(
        build_api_router(
            container,  # pyright: ignore[reportArgumentType]
            lambda: None,
        )
    )

    response = make_test_client(app).post(
        "/api/search",
        json={"query": "snowflake migration", "top_k": 20},
    )

    assert response.status_code == 200
    assert response.json() == {
        "query": "snowflake migration",
        "hits": [
            {
                "project_id": "prj_1",
                "project_name": "Snowflake modernization",
                "project_description": "Cloud data platform migration",
                "document_id": "doc_1",
                "document_name": "Modernization overview.pptx",
                "source_type": "UPLOADED",
                "page_number": 4,
                "page_count": 8,
                "locator": None,
                "text_preview": (
                    "Reduced operational overhead through a phased migration."
                ),
                "text_truncated": False,
                "markdown_available": True,
            }
        ],
        "warnings": [],
    }
