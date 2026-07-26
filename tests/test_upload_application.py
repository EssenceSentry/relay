from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from app.application import Conflict, InvalidOperation, KnowledgeApplication
from app.auth import Principal

from knowledge_core.models import UploadRequest


class FakeUploadRepository:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.create_calls = 0

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        if project_id != "prj_1":
            return None
        return {
            "project_id": project_id,
            "name": "Project One",
            "status": "ACTIVE",
        }

    def is_project_member(self, *, project_id: str, email: str) -> bool:
        return project_id == "prj_1" and email == "author@blend360.com"

    def get_document(
        self,
        *,
        project_id: str,
        document_id: str,
    ) -> dict[str, Any] | None:
        assert project_id == "prj_1"
        return self.documents.get(document_id)

    def create_document(self, **kwargs: Any) -> dict[str, Any]:
        self.create_calls += 1
        item = {
            **kwargs,
            "document_version": "1",
            "source_type": "UPLOADED",
            "status": str(kwargs["status"]),
        }
        self.documents[str(kwargs["document_id"])] = item
        return item


class FakeS3:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate_presigned_post(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "url": "https://upload.example.com/",
            "fields": {
                "key": kwargs["Key"],
                **kwargs["Fields"],
                "policy": "signed",
            },
        }


def _principal() -> Principal:
    return Principal(
        subject="user-1",
        email="author@blend360.com",
        groups=frozenset(),
        claims={},
    )


def _application() -> tuple[KnowledgeApplication, FakeUploadRepository, FakeS3]:
    repository = FakeUploadRepository()
    s3 = FakeS3()
    container = SimpleNamespace(
        repository=repository,
        s3=s3,
        settings=SimpleNamespace(
            document_bucket="documents",
            max_upload_bytes=25 * 1024 * 1024,
            application_base_url="https://knowledge.example.com",
        ),
    )
    return (
        KnowledgeApplication(container),  # pyright: ignore[reportArgumentType]
        repository,
        s3,
    )


def _request(
    *,
    filename: str = "Delivery plan.pdf",
    size_bytes: int = 1234,
) -> UploadRequest:
    return UploadRequest(
        filename=filename,
        content_type="application/pdf",
        size_bytes=size_bytes,
        request_id="upload-request-001",
    )


def test_prepare_upload_is_idempotent_and_returns_browser_fallback() -> None:
    application, repository, s3 = _application()

    first = application.prepare_document_upload(
        "prj_1",
        _request(),
        principal=_principal(),
        request_id="upload-request-001",
    )
    repository.documents[str(first.document["document_id"])]["status"] = "QUEUED"
    retry = application.prepare_document_upload(
        "prj_1",
        _request(),
        principal=_principal(),
        request_id="upload-request-001",
    )

    assert repository.create_calls == 1
    assert len(s3.calls) == 2
    assert first.document["document_id"] == retry.document["document_id"]
    assert first.upload_required is True
    assert retry.upload_required is False
    assert retry.document["status"] == "QUEUED"
    assert retry.fallback_url == (
        "https://knowledge.example.com/upload.html"
        "?upload_project_id=prj_1&upload_request_id=upload-request-001"
    )
    assert s3.calls[0]["Conditions"][-1] == [
        "content-length-range",
        1,
        2258,
    ]


def test_upload_request_id_cannot_be_reused_for_another_file() -> None:
    application, _, _ = _application()
    application.prepare_document_upload(
        "prj_1",
        _request(),
        principal=_principal(),
        request_id="upload-request-001",
    )

    with pytest.raises(Conflict, match="bound to another file"):
        application.prepare_document_upload(
            "prj_1",
            _request(filename="Different.pdf"),
            principal=_principal(),
            request_id="upload-request-001",
        )


def test_upload_rejects_unsupported_type_and_size_before_presigning() -> None:
    application, _, s3 = _application()

    with pytest.raises(InvalidOperation, match="Unsupported"):
        application.prepare_document_upload(
            "prj_1",
            _request(filename="archive.zip"),
            principal=_principal(),
            request_id="upload-request-unsupported",
        )
    with pytest.raises(InvalidOperation, match="upload limit"):
        application.prepare_document_upload(
            "prj_1",
            _request(size_bytes=26 * 1024 * 1024),
            principal=_principal(),
            request_id="upload-request-too-large",
        )

    assert s3.calls == []
