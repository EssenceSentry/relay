from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol
from urllib.parse import quote

DownloadFormat = Literal["original", "markdown"]

_DOWNLOAD_EXPIRY_SECONDS = 900
_UNSAFE_HEADER_CHARACTERS = re.compile(r"[\x00-\x1f\x7f\"\\]+")


class DocumentDownloadUnavailable(ValueError):
    """Raised when the requested representation has not been generated."""


@dataclass(frozen=True)
class PresignedDocumentDownload:
    url: str
    filename: str
    content_type: str
    download_format: DownloadFormat
    expires_in_seconds: int


class S3Presigner(Protocol):
    def generate_presigned_url(
        self,
        ClientMethod: str,
        Params: Mapping[str, Any] = ...,
        ExpiresIn: int = 3600,
        HttpMethod: str = ...,
    ) -> str: ...


def presign_document_download(
    *,
    s3: S3Presigner,
    document: Mapping[str, Any],
    download_format: DownloadFormat,
) -> PresignedDocumentDownload:
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

    url = s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket,
            "Key": str(key),
            "ResponseContentDisposition": _content_disposition(filename),
            "ResponseContentType": content_type,
        },
        ExpiresIn=_DOWNLOAD_EXPIRY_SECONDS,
    )
    return PresignedDocumentDownload(
        url=url,
        filename=filename,
        content_type=content_type,
        download_format=download_format,
        expires_in_seconds=_DOWNLOAD_EXPIRY_SECONDS,
    )


def _content_disposition(filename: str) -> str:
    cleaned = _UNSAFE_HEADER_CHARACTERS.sub("_", filename).strip() or "document"
    ascii_fallback = cleaned.encode("ascii", "ignore").decode("ascii").strip()
    ascii_fallback = ascii_fallback or "document"
    return (
        f'attachment; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{quote(cleaned)}"
    )
