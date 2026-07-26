from __future__ import annotations

SUPPORTED_DOCUMENT_SUFFIXES = frozenset(
    {
        ".pdf",
        ".doc",
        ".docx",
        ".pptx",
        ".txt",
        ".md",
        ".csv",
        ".json",
    }
)


def document_suffix(filename: str) -> str:
    dot = filename.rfind(".")
    return filename[dot:].casefold() if dot >= 0 else ""
