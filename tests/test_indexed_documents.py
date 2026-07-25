from __future__ import annotations

import pytest

from knowledge_core.indexed_documents import build_indexed_document


def _document(*, text: str, version: str = "1"):
    return build_indexed_document(
        text=text,
        project_id="prj_1",
        document_id="doc_1",
        document_version=version,
        document_name="source.md",
        s3_bucket="bucket",
        s3_key="uploads/prj_1/doc_1/source.md",
    )


def test_build_indexed_document_preserves_complete_markdown() -> None:
    markdown = """
# Dossier

- Parent
  - Nested detail

| Metric | Value |
|---|---:|
| Growth | 12% |
"""

    document = _document(text=markdown)

    assert document.text == markdown.strip()
    assert document.index_id.startswith("idx_")


def test_index_id_is_stable_and_changes_with_document_version() -> None:
    first = _document(text="# Stable dossier")
    repeated = _document(text="# Stable dossier")
    changed = _document(text="# Stable dossier", version="2")

    assert first.index_id == repeated.index_id
    assert first.index_id != changed.index_id


def test_build_indexed_document_rejects_empty_text() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        _document(text=" \n ")


def test_build_indexed_document_keeps_page_and_original_file_metadata() -> None:
    document = build_indexed_document(
        text="# Page 4",
        project_id="prj_1",
        document_id="doc_1",
        document_version="1",
        document_name="source.pptx",
        s3_bucket="documents",
        s3_key="uploads/prj_1/doc_1/source.pptx",
        page_number=4,
        page_count=12,
        locator="page 4 of 12",
    )

    assert document.page_number == 4
    assert document.page_count == 12
    assert document.locator == "page 4 of 12"
    assert document.s3_key.endswith("/source.pptx")
