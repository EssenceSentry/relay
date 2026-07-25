from __future__ import annotations

import hashlib
import re
from pathlib import Path
from uuid import uuid4

_SAFE_COMPONENT = re.compile(r"[^a-zA-Z0-9._-]+")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def safe_filename(filename: str) -> str:
    name = Path(filename).name.strip()
    if not name:
        return "document"
    cleaned = _SAFE_COMPONENT.sub("-", name).strip(".-")
    return cleaned[:180] or "document"


def stable_index_id(
    *,
    project_id: str,
    document_id: str,
    document_version: str,
    text: str,
) -> str:
    payload = "\x1f".join(
        [
            project_id,
            document_id,
            document_version,
            hashlib.sha256(text.encode("utf-8")).hexdigest(),
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
    return f"idx_{digest}"


def stable_action_id(
    *,
    prefix: str,
    project_id: str,
    request_id: str,
) -> str:
    payload = "\x1f".join([prefix, project_id, request_id.strip()])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
    return f"{prefix}_{digest}"
