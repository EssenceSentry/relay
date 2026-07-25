from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))
bootstrap = importlib.import_module("_bootstrap_aws")
ingest = importlib.import_module("ingest_local_documents")
status = importlib.import_module("ingestion_status")
configure_sso = importlib.import_module("configure_sso")


def test_load_stack_context_selects_single_stack(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs.json"
    outputs.write_text(
        json.dumps({"BlendKnowledge": {"UserPoolId": "us-east-1_test"}})
    )

    context = bootstrap.load_stack_context(outputs, None)

    assert context.stack_name == "BlendKnowledge"
    assert context.outputs["UserPoolId"] == "us-east-1_test"
    assert bootstrap.infer_region(context.outputs) == "us-east-1"


def test_select_files_is_reproducible_and_filters_size(
    tmp_path: Path,
) -> None:
    for name in ("a.pdf", "b.docx", "c.pptx", "ignored.exe"):
        (tmp_path / name).write_bytes(name.encode())
    (tmp_path / "empty.pdf").touch()

    files = ingest.eligible_files(
        tmp_path,
        extensions=ingest.parse_extensions("pdf,docx,pptx"),
    )
    first = ingest.select_files(files, count=2, seed=42)
    second = ingest.select_files(files, count=2, seed=42)

    assert [item.name for item in first] == [item.name for item in second]
    assert {item.name for item in files} == {"a.pdf", "b.docx", "c.pptx"}


class _Table:
    def __init__(self, existing: dict[str, Any] | None = None) -> None:
        self.existing = existing
        self.puts: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []

    def get_item(self, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        return {"Item": self.existing} if self.existing else {}

    def put_item(self, **kwargs: Any) -> None:
        self.puts.append(kwargs)

    def update_item(self, **kwargs: Any) -> None:
        self.updates.append(kwargs)


class _S3:
    def __init__(self) -> None:
        self.uploads: list[tuple[Any, ...]] = []

    def upload_file(self, *args: Any, **kwargs: Any) -> None:
        self.uploads.append((*args, kwargs))


def test_upload_one_provisions_record_before_s3_upload(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    path = source / "Test deck.pptx"
    path.write_bytes(b"presentation")
    table = _Table()
    s3 = _S3()

    result = ingest._upload_one(
        path=path,
        source=source,
        table=table,
        s3=s3,
        bucket="documents",
        project_id="prj_test",
        uploaded_by="bootstrap@example.com",
        retry_failed=False,
    )

    assert result["status"] == "uploaded"
    item = table.puts[0]["Item"]
    assert item["status"] == "UPLOADING"
    assert item["s3_key"].startswith(f"uploads/prj_test/{item['document_id']}/")
    extra_args = s3.uploads[0][3]["ExtraArgs"]
    assert extra_args["Metadata"]["project-id"] == "prj_test"
    assert extra_args["Metadata"]["document-id"] == item["document_id"]


def test_upload_one_skips_existing_document(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    path = source / "dossier.pdf"
    path.write_bytes(b"pdf")
    table = _Table(existing={"status": "READY"})
    s3 = _S3()

    result = ingest._upload_one(
        path=path,
        source=source,
        table=table,
        s3=s3,
        bucket="documents",
        project_id="prj_test",
        uploaded_by="bootstrap@example.com",
        retry_failed=False,
    )

    assert result["status"] == "skipped"
    assert result["existing_status"] == "READY"
    assert not table.puts
    assert not s3.uploads


def test_status_report_includes_failed_document_ids(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "project_id": "prj_test",
                "results": [
                    {
                        "document_id": "doc_ok",
                        "status": "uploaded",
                    },
                    {
                        "document_id": "doc_failed",
                        "status": "failed",
                    },
                ],
            }
        )
    )

    project_id, document_ids = status._load_report(report)

    assert project_id == "prj_test"
    assert document_ids == {"doc_ok", "doc_failed"}


def test_parse_extensions_rejects_unsupported_values() -> None:
    with pytest.raises(SystemExit, match="Unsupported extensions"):
        ingest.parse_extensions("pdf,xls")


def test_microsoft_sso_secret_payload_requires_tenant() -> None:
    with pytest.raises(SystemExit, match="tenant-id"):
        configure_sso._secret_payload(
            provider="microsoft",
            client_id="client",
            client_secret="secret",
            tenant_id=None,
        )


def test_microsoft_sso_secret_payload() -> None:
    payload = configure_sso._secret_payload(
        provider="microsoft",
        client_id="client",
        client_secret="secret",
        tenant_id="blend-tenant",
    )

    assert payload == {
        "tenant_id": "blend-tenant",
        "client_id": "client",
        "client_secret": "secret",
    }
