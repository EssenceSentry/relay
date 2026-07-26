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
project_mapping = importlib.import_module("_project_mapping")
reassign = importlib.import_module("reassign_documents")
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

    selections = status._load_report(report)

    assert selections == {"prj_test": {"doc_ok", "doc_failed"}}


def test_status_report_supports_multiple_projects(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "project_id": "prj_one",
                        "document_id": "doc_one",
                    },
                    {
                        "project_id": "prj_two",
                        "document_id": "doc_two",
                    },
                ]
            }
        )
    )

    selections = status._load_report(report)

    assert selections == {
        "prj_one": {"doc_one"},
        "prj_two": {"doc_two"},
    }


def test_project_mapping_resolves_relative_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    nested = source / "nested"
    nested.mkdir(parents=True)
    first = source / "first.pdf"
    second = nested / "second.pptx"
    first.write_bytes(b"pdf")
    second.write_bytes(b"deck")
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(
        json.dumps(
            {
                "P1": {"title": "First project", "files": ["first.pdf"]},
                "P2": {
                    "title": "Second project",
                    "files": ["nested/second.pptx"],
                },
            }
        )
    )

    groups = project_mapping.load_project_mapping(mapping_path)
    resolved = project_mapping.resolve_mapped_files(
        source=source,
        available_files=[first, second],
        groups=groups,
    )

    assert resolved[first].key == "P1"
    assert resolved[second].key == "P2"


def test_project_mapping_rejects_duplicate_assignments(tmp_path: Path) -> None:
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(
        json.dumps(
            {
                "P1": {"title": "First", "files": ["same.pdf"]},
                "P2": {"title": "Second", "files": ["same.pdf"]},
            }
        )
    )

    with pytest.raises(ValueError, match="assigned to both"):
        project_mapping.load_project_mapping(mapping_path)


def test_reassignment_loads_document_reference(tmp_path: Path) -> None:
    markdown_dir = tmp_path / "markdown"
    markdown_dir.mkdir()
    markdown = markdown_dir / "source.pptx.md"
    markdown.write_text(
        "> Original file: `source.pptx` "
        "(`s3://documents/uploads/prj_source/doc_123/source.pptx`).\n\n"
        "# Project\n"
    )
    group = project_mapping.ProjectFileGroup(
        key="P1",
        title="Project one",
        files=(markdown.name,),
    )

    mapped = reassign.load_mapped_markdown(
        groups=(group,),
        markdown_dir=markdown_dir,
    )
    assignments = reassign.resolve_assignments(
        mapped_markdown=mapped,
        documents={
            "doc_123": {
                "document_id": "doc_123",
                "document_name": "source.pptx",
                "s3_bucket": "documents",
                "s3_key": "uploads/prj_source/doc_123/source.pptx",
            }
        },
        source_project_id="prj_source",
    )

    assert len(assignments) == 1
    assert assignments[0].document_id == "doc_123"
    assert assignments[0].s3_bucket == "documents"
    assert assignments[0].s3_key.endswith("/source.pptx")


def test_reassignment_falls_back_to_document_name(tmp_path: Path) -> None:
    markdown_dir = tmp_path / "markdown"
    markdown_dir.mkdir()
    markdown = markdown_dir / "source.pptx.md"
    markdown.write_text("# Project\n")
    group = project_mapping.ProjectFileGroup(
        key="P1",
        title="Project one",
        files=(markdown.name,),
    )

    mapped = reassign.load_mapped_markdown(
        groups=(group,),
        markdown_dir=markdown_dir,
    )
    assignments = reassign.resolve_assignments(
        mapped_markdown=mapped,
        documents={
            "doc_123": {
                "document_id": "doc_123",
                "document_name": "source.pptx",
                "s3_bucket": "documents",
                "s3_key": "uploads/prj_source/doc_123/source.pptx",
            }
        },
        source_project_id="prj_source",
    )

    assert assignments[0].document_id == "doc_123"


class _QueryTable:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents

    def query(self, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        return {"Items": self.documents}


def test_reassignment_can_resolve_documents_already_moved() -> None:
    target = {
        "document_id": "doc_target",
        "document_name": "target.pdf",
        "s3_bucket": "documents",
        "s3_key": "uploads/prj_source/doc_target/target.pdf",
    }

    candidates = reassign._candidate_documents(
        _QueryTable([target]),
        source_documents={},
        existing_projects={
            "P1": {
                "project_id": "prj_target",
            }
        },
    )

    assert candidates == {"doc_target": target}


def test_reassignment_deletes_stale_source_search_entries(
    tmp_path: Path,
) -> None:
    group = project_mapping.ProjectFileGroup(
        key="P1",
        title="Project one",
        files=("source.pdf.md",),
    )
    assignment = reassign.DocumentAssignment(
        group=group,
        markdown_name="source.pdf.md",
        markdown_path=tmp_path / "source.pdf.md",
        document_id="doc_123",
        s3_bucket="documents",
        s3_key="uploads/prj_source/doc_123/source.pdf",
    )

    index_ids = reassign._mapped_source_index_ids(
        [
            {
                "_id": "actual-index-id",
                "index_id": "stored-index-id",
                "document_id": "doc_123",
            },
            {
                "_id": "unrelated-index-id",
                "index_id": "unrelated-index-id",
                "document_id": "doc_other",
            },
        ],
        assignments=(assignment,),
    )

    assert index_ids == ["actual-index-id"]


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
