from __future__ import annotations

import pytest

from knowledge_core.page_processing import (
    combine_page_markdown,
    should_process_by_page,
    wrap_page_markdown,
)


def test_only_documents_over_three_pages_are_split() -> None:
    assert should_process_by_page(1) is False
    assert should_process_by_page(3) is False
    assert should_process_by_page(4) is True
    with pytest.raises(ValueError, match="positive"):
        should_process_by_page(0)


def test_page_markdown_keeps_original_file_and_page_reference() -> None:
    page = wrap_page_markdown(
        "# Clean page\n\nProject result.",
        filename="dossier.pptx",
        bucket="documents",
        key="uploads/prj_1/doc_1/dossier.pptx",
        page_number=2,
        page_count=5,
    )

    assert page.startswith("## Page 2 of 5")
    assert "Original file: `dossier.pptx`" in page
    assert "s3://documents/uploads/prj_1/doc_1/dossier.pptx" in page


def test_page_markdown_is_concatenated_in_caller_supplied_order() -> None:
    combined = combine_page_markdown(
        ["page one", "page two", "page three", "page four"],
        filename="dossier.pdf",
        bucket="documents",
        key="uploads/prj_1/doc_1/dossier.pdf",
    )

    assert combined.startswith("# dossier.pdf")
    assert combined.index("page one") < combined.index("page four")
    assert combined.count("\n\n---\n\n") == 3
    assert "s3://documents/uploads/prj_1/doc_1/dossier.pdf" in combined
