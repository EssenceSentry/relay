from __future__ import annotations

import time
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

import pytest
from app.auth import Principal
from app.document_downloads import (
    DocumentDownloadUnavailable,
    resolve_document_download,
)
from app.download_sessions import StoredDownloadSession
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


class FakeDownloadSessions:
    def __init__(self) -> None:
        self.sessions: dict[str, StoredDownloadSession] = {}

    def issue(
        self,
        *,
        bucket: str,
        key: str,
        filename: str,
        content_type: str,
        expires_in_seconds: int,
    ) -> str:
        token = chr(ord("A") + len(self.sessions)) * 43
        self.sessions[token] = StoredDownloadSession(
            bucket=bucket,
            key=key,
            filename=filename,
            content_type=content_type,
            expires_at=int(time.time()) + expires_in_seconds,
        )
        return token

    def get(self, token: str) -> StoredDownloadSession | None:
        return self.sessions.get(token)


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

    def get_project(self, project_id: str) -> dict[str, str] | None:
        if project_id != self.document["project_id"]:
            return None
        return {
            "project_id": project_id,
            "name": "Project one",
            "status": "ACTIVE",
        }


_PRINCIPAL = Principal(
    subject="user-1",
    email="reader@blend360.com",
    groups=frozenset(),
    claims={},
)


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


def test_resolves_original_with_source_filename(
    document: dict[str, Any],
) -> None:
    result = resolve_document_download(
        document=document,
        download_format="original",
    )

    assert result.filename == "Client résumé.pptx"
    assert result.download_format == "original"
    assert result.key == document["s3_key"]
    assert result.bucket == document["s3_bucket"]


def test_resolves_consolidated_markdown_with_readable_filename(
    document: dict[str, Any],
) -> None:
    result = resolve_document_download(
        document=document,
        download_format="markdown",
    )

    assert result.filename == "Client résumé.pptx.md"
    assert result.content_type == "text/markdown; charset=utf-8"
    assert result.download_format == "markdown"
    assert result.key == document["enhanced_s3_key"]


def test_markdown_download_requires_consolidated_output(
    document: dict[str, Any],
) -> None:
    document.pop("enhanced_s3_key")

    with pytest.raises(
        DocumentDownloadUnavailable,
        match="Consolidated Markdown is not available",
    ):
        resolve_document_download(
            document=document,
            download_format="markdown",
        )


def test_api_download_route_supports_both_representations(
    document: dict[str, Any],
) -> None:
    s3 = FakeS3()
    download_sessions = FakeDownloadSessions()
    container = SimpleNamespace(
        repository=FakeRepository(document),
        s3=s3,
        download_sessions=download_sessions,
        settings=SimpleNamespace(
            application_base_url="https://knowledge.example.com",
            document_bucket="documents",
        ),
    )
    app = FastAPI()
    app.include_router(
        build_api_router(
            container,  # pyright: ignore[reportArgumentType]
            lambda: _PRINCIPAL,
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
    assert original.json()["url"] == (
        "https://knowledge.example.com/api/downloads/" + "A" * 43
    )
    assert markdown.status_code == 200
    assert markdown.json()["download_format"] == "markdown"
    assert markdown.json()["filename"] == "Client résumé.pptx.md"
    assert markdown.json()["url"] == (
        "https://knowledge.example.com/api/downloads/" + "B" * 43
    )
    assert s3.calls == []

    original_url = str(original.json()["url"])
    redirected = client.get(
        urlsplit(original_url).path,
        follow_redirects=False,
    )

    assert redirected.status_code == 307
    assert redirected.headers["location"].startswith(
        "https://download.example/uploads/prj_1/doc_1/"
    )
    assert redirected.headers["cache-control"] == "no-store"
    assert redirected.headers["referrer-policy"] == "no-referrer"
    assert len(s3.calls) == 1
    assert (
        "filename*=UTF-8''Client%20r%C3%A9sum%C3%A9.pptx"
        in s3.calls[0]["params"]["ResponseContentDisposition"]
    )


def test_api_returns_conflict_when_markdown_is_not_ready(
    document: dict[str, Any],
) -> None:
    document.pop("enhanced_s3_key")
    container = SimpleNamespace(
        repository=FakeRepository(document),
        s3=FakeS3(),
        download_sessions=FakeDownloadSessions(),
        settings=SimpleNamespace(
            application_base_url="https://knowledge.example.com",
            document_bucket="documents",
        ),
    )
    app = FastAPI()
    app.include_router(
        build_api_router(
            container,  # pyright: ignore[reportArgumentType]
            lambda: _PRINCIPAL,
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


def test_public_download_route_rejects_unknown_token_without_presigning(
    document: dict[str, Any],
) -> None:
    s3 = FakeS3()
    container = SimpleNamespace(
        repository=FakeRepository(document),
        s3=s3,
        download_sessions=FakeDownloadSessions(),
        settings=SimpleNamespace(
            application_base_url="https://knowledge.example.com",
            document_bucket="documents",
        ),
    )
    app = FastAPI()
    app.include_router(
        build_api_router(
            container,  # pyright: ignore[reportArgumentType]
            lambda: _PRINCIPAL,
        )
    )

    response = make_test_client(app).get(
        "/api/downloads/not-a-valid-token",
        follow_redirects=False,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Download link not found or expired"
    assert s3.calls == []
