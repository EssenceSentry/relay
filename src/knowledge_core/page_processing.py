from __future__ import annotations

from pathlib import Path

PAGE_SPLIT_THRESHOLD = 3


def should_process_by_page(page_count: int) -> bool:
    if page_count <= 0:
        raise ValueError("page_count must be positive")
    return page_count > PAGE_SPLIT_THRESHOLD


def original_file_reference(
    *,
    filename: str,
    bucket: str,
    key: str,
) -> str:
    display_name = Path(filename).name or "document"
    return f"Original file: `{display_name}` (`s3://{bucket}/{key}`)"


def wrap_page_markdown(
    markdown: str,
    *,
    filename: str,
    bucket: str,
    key: str,
    page_number: int,
    page_count: int,
) -> str:
    if not 1 <= page_number <= page_count:
        raise ValueError("page_number must be within page_count")
    content = markdown.strip()
    if not content:
        raise ValueError("Page Markdown must not be empty")
    reference = original_file_reference(
        filename=filename,
        bucket=bucket,
        key=key,
    )
    return (
        f"## Page {page_number} of {page_count}\n\n"
        f"> {reference}; page {page_number} of {page_count}.\n\n"
        f"{content}"
    )


def combine_page_markdown(
    pages: list[str],
    *,
    filename: str,
    bucket: str,
    key: str,
) -> str:
    if not pages or any(not page.strip() for page in pages):
        raise ValueError("Every rendered page must have Markdown content")
    reference = original_file_reference(
        filename=filename,
        bucket=bucket,
        key=key,
    )
    return (
        f"# {Path(filename).name or 'Document'}\n\n"
        f"> {reference}.\n\n"
        + "\n\n---\n\n".join(page.strip() for page in pages)
    )
