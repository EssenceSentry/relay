from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app.application import Conflict, KnowledgeApplication
from app.auth import Principal
from app.download_sessions import StoredDownloadSession
from botocore.exceptions import ClientError

from knowledge_core.dossier_rendering import RenderedDossierBytes
from knowledge_core.models import DossierRenderRequest

_FIXTURE = Path(__file__).parent / "fixtures" / "dossiers" / "chewy-nlp-seo.md"


def fixture_markdown() -> str:
    return _FIXTURE.read_text(encoding="utf-8")


class FakeRepository:
    def get_project(self, project_id: str) -> dict[str, Any] | None:
        if project_id != "prj_1":
            return None
        return {
            "project_id": project_id,
            "name": "Project One",
            "status": "ACTIVE",
        }


class FakeRenderer:
    def __init__(self) -> None:
        self.calls = 0

    def render(
        self,
        markdown: str,
        *,
        filename_stem: str | None = None,
    ) -> RenderedDossierBytes:
        self.calls += 1
        return RenderedDossierBytes(
            markdown=markdown.encode(),
            latex=b"latex",
            docx=b"docx",
            pdf=b"%PDF-1.7\n",
            source_sha256="unused-by-application",
            filename_stem=filename_stem or "dossier",
        )


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, Any]] = {}

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        del Bucket
        if Key not in self.objects:
            raise ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}},
                "HeadObject",
            )
        return {"Metadata": self.objects[Key]["Metadata"]}

    def put_object(self, *, Key: str, **kwargs: Any) -> dict[str, str]:
        self.objects[Key] = kwargs
        return {"ETag": "test"}

    def generate_presigned_url(
        self,
        operation: str,
        *,
        Params: dict[str, Any],
        ExpiresIn: int,
    ) -> str:
        assert operation == "get_object"
        return f"https://downloads.example/{Params['Key']}?ttl={ExpiresIn}"


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
            expires_at=expires_in_seconds,
        )
        return token


def _application() -> tuple[KnowledgeApplication, FakeRenderer, FakeS3]:
    renderer = FakeRenderer()
    s3 = FakeS3()
    container = SimpleNamespace(
        repository=FakeRepository(),
        dossier_renderer=renderer,
        s3=s3,
        download_sessions=FakeDownloadSessions(),
        settings=SimpleNamespace(
            document_bucket="documents",
            application_base_url="https://knowledge.example.com",
        ),
    )
    return (
        KnowledgeApplication(container),  # pyright: ignore[reportArgumentType]
        renderer,
        s3,
    )


def _principal() -> Principal:
    return Principal(
        subject="sub_1",
        email="reader@gmail.com",
        groups=frozenset(),
        claims={"authentication_mode": "cognito"},
    )


def test_render_is_private_persisted_and_idempotent() -> None:
    application, renderer, s3 = _application()
    body = DossierRenderRequest(markdown=fixture_markdown())

    first = application.render_project_dossier(
        "prj_1",
        body,
        principal=_principal(),
        request_id="stable-request",
    )
    repeated = application.render_project_dossier(
        "prj_1",
        body,
        principal=_principal(),
        request_id="stable-request",
    )

    assert renderer.calls == 1
    assert len(s3.objects) == 4
    assert first.render_id == repeated.render_id
    assert repeated.reused_existing_render is True
    assert first.docx_url.startswith(
        "https://knowledge.example.com/api/downloads/"
    )
    assert first.pdf_url.startswith(
        "https://knowledge.example.com/api/downloads/"
    )


def test_render_request_id_cannot_be_reused_for_other_markdown() -> None:
    application, _, _ = _application()
    markdown = fixture_markdown()
    body = DossierRenderRequest(markdown=markdown)
    application.render_project_dossier(
        "prj_1",
        body,
        principal=_principal(),
        request_id="stable-request",
    )

    changed = DossierRenderRequest(
        markdown=markdown.replace("Chewy NLP", "Changed NLP", 1)
    )
    with pytest.raises(Conflict, match="different Markdown"):
        application.render_project_dossier(
            "prj_1",
            changed,
            principal=_principal(),
            request_id="stable-request",
        )
