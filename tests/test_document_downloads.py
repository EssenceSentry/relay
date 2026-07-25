from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

import pytest
from app.document_downloads import (
    DocumentDownloadUnavailable,
    presign_document_download,
)
from app.routes import build_api_router
from fastapi import FastAPI

from test_support.http_client import make_test_client


class FakeS3:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate_presigned_url(
        self,
        ClientMethod: str,
        Params: Mapping[str, Any] | None = None,
        ExpiresIn: int = 3600,
        HttpMethod: str = "",
    ) -> str:
        del HttpMethod
        assert Params is not None
        self.calls.append(
            {
                "operation": ClientMethod,
                "params": Params,
                "expires": ExpiresIn,
            }
        )
        return f"https://download.example/{Params['Key']}"


class FakeRepository:
    def __init__(self, document: dict[str, Any]) -> None:
        self.document = document

    def get_document(
        self,
        *,
        project_id: str,
        document_id: str,
    ) -> dict[str, Any] | None:
        if (
            project_id == self.document["project_id"]
            and document_id == self.document["document_id"]
        ):
            return self.document
        return None


@pytest.fixture
def document() -> dict[str, Any]:
    return {
        "project_id": "prj_1",
        "document_id": "doc_1",
        "document_name": "Client résumé.pptx",
        "content_type": (
            "application/vnd.openxmlformats-officedocument."
            "presentationml.presentation"
        ),
        "s3_bucket": "documents",
        "s3_key": "uploads/prj_1/doc_1/Client-resume.pptx",
        "enhanced_s3_key": "extracted/prj_1/doc_1/document.md",
    }


def test_presigns_original_with_source_filename(
    document: dict[str, Any],
) -> None:
    s3 = FakeS3()

    result = presign_document_download(
        s3=s3,
        document=document,
        download_format="original",
    )

    assert result.filename == "Client résumé.pptx"
    assert result.download_format == "original"
    assert result.expires_in_seconds == 900
    assert s3.calls[0]["params"]["Key"] == document["s3_key"]
    assert (
        "filename*=UTF-8''Client%20r%C3%A9sum%C3%A9.pptx"
        in (s3.calls[0]["params"]["ResponseContentDisposition"])
    )


def test_presigns_consolidated_markdown_with_readable_filename(
    document: dict[str, Any],
) -> None:
    s3 = FakeS3()

    result = presign_document_download(
        s3=s3,
        document=document,
        download_format="markdown",
    )

    assert result.filename == "Client résumé.pptx.md"
    assert result.content_type == "text/markdown; charset=utf-8"
    assert result.download_format == "markdown"
    assert s3.calls[0]["params"]["Key"] == document["enhanced_s3_key"]


def test_markdown_download_requires_consolidated_output(
    document: dict[str, Any],
) -> None:
    document.pop("enhanced_s3_key")

    with pytest.raises(
        DocumentDownloadUnavailable,
        match="Consolidated Markdown is not available",
    ):
        presign_document_download(
            s3=FakeS3(),
            document=document,
            download_format="markdown",
        )


def test_api_download_route_supports_both_representations(
    document: dict[str, Any],
) -> None:
    s3 = FakeS3()
    container = SimpleNamespace(
        repository=FakeRepository(document),
        s3=s3,
    )
    app = FastAPI()
    app.include_router(
        build_api_router(
            container,  # pyright: ignore[reportArgumentType]
            lambda: None,
        )
    )
    client = make_test_client(app)

    original = client.get("/api/projects/prj_1/documents/doc_1/download-url")
    markdown = client.get(
        "/api/projects/prj_1/documents/doc_1/download-url",
        params={"download_format": "markdown"},
    )

    assert original.status_code == 200
    assert original.json()["download_format"] == "original"
    assert original.json()["filename"] == "Client résumé.pptx"
    assert markdown.status_code == 200
    assert markdown.json()["download_format"] == "markdown"
    assert markdown.json()["filename"] == "Client résumé.pptx.md"


def test_api_returns_conflict_when_markdown_is_not_ready(
    document: dict[str, Any],
) -> None:
    document.pop("enhanced_s3_key")
    container = SimpleNamespace(
        repository=FakeRepository(document),
        s3=FakeS3(),
    )
    app = FastAPI()
    app.include_router(
        build_api_router(
            container,  # pyright: ignore[reportArgumentType]
            lambda: None,
        )
    )

    response = make_test_client(app).get(
        "/api/projects/prj_1/documents/doc_1/download-url",
        params={"download_format": "markdown"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Consolidated Markdown is not available for this document yet."
    )
