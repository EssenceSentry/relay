from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import quote

DownloadFormat = Literal["original", "markdown"]

DOWNLOAD_EXPIRY_SECONDS = 900
_UNSAFE_HEADER_CHARACTERS = re.compile(r"[\x00-\x1f\x7f\"\\]+")


class DocumentDownloadUnavailable(ValueError):
    """Raised when the requested representation has not been generated."""


@dataclass(frozen=True)
class DocumentDownloadTarget:
    bucket: str
    key: str
    filename: str
    content_type: str
    download_format: DownloadFormat


@dataclass(frozen=True)
class DocumentDownloadSession:
    url: str
    filename: str
    content_type: str
    download_format: DownloadFormat
    expires_in_seconds: int


def resolve_document_download(
    *,
    document: Mapping[str, Any],
    download_format: DownloadFormat,
) -> DocumentDownloadTarget:
    document_name = str(document["document_name"])
    bucket = str(document["s3_bucket"])

    if download_format == "markdown":
        key = document.get("enhanced_s3_key")
        if not key:
            raise DocumentDownloadUnavailable(
                "Consolidated Markdown is not available for this document yet."
            )
        filename = f"{document_name}.md"
        content_type = "text/markdown; charset=utf-8"
    else:
        key = document["s3_key"]
        filename = document_name
        content_type = str(
            document.get("content_type") or "application/octet-stream"
        )

    return DocumentDownloadTarget(
        bucket=bucket,
        key=str(key),
        filename=filename,
        content_type=content_type,
        download_format=download_format,
    )


def content_disposition(filename: str) -> str:
    cleaned = _UNSAFE_HEADER_CHARACTERS.sub("_", filename).strip() or "document"
    ascii_fallback = cleaned.encode("ascii", "ignore").decode("ascii").strip()
    ascii_fallback = ascii_fallback or "document"
    return (
        f'attachment; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{quote(cleaned)}"
    )
