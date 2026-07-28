from __future__ import annotations

import re
from typing import Any

from app.download_sessions import DownloadSessionStore


class FakeTable:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.get_calls = 0

    def put_item(self, *, Item: dict[str, Any], **kwargs: Any) -> None:
        del kwargs
        self.items[(str(Item["PK"]), str(Item["SK"]))] = Item

    def get_item(
        self,
        *,
        Key: dict[str, str],
        ConsistentRead: bool,
    ) -> dict[str, Any]:
        assert ConsistentRead is True
        self.get_calls += 1
        item = self.items.get((Key["PK"], Key["SK"]))
        return {"Item": item} if item is not None else {}

    def delete_item(self, *, Key: dict[str, str]) -> None:
        self.items.pop((Key["PK"], Key["SK"]), None)


def _store(
    table: FakeTable,
    clock: list[float],
) -> DownloadSessionStore:
    return DownloadSessionStore(
        "knowledge",
        region_name="us-east-1",
        table=table,  # pyright: ignore[reportArgumentType]
        now=lambda: clock[0],
    )


def test_download_session_uses_url_safe_token_hash_and_ttl() -> None:
    table = FakeTable()
    clock = [1_000.0]
    store = _store(table, clock)

    token = store.issue(
        bucket="documents",
        key="uploads/prj_1/doc_1/deck.pptx",
        filename="deck.pptx",
        content_type=(
            "application/vnd.openxmlformats-officedocument."
            "presentationml.presentation"
        ),
        expires_in_seconds=900,
    )

    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token)
    item = next(iter(table.items.values()))
    assert token not in str(item["PK"])
    assert item["PK"].startswith("DOWNLOAD#")
    assert item["expires_at"] == 1_900
    assert store.get(token) is not None


def test_download_session_rejects_malformed_and_expired_tokens() -> None:
    table = FakeTable()
    clock = [1_000.0]
    store = _store(table, clock)
    token = store.issue(
        bucket="documents",
        key="dossiers/prj_1/render/dossier.pdf",
        filename="dossier.pdf",
        content_type="application/pdf",
        expires_in_seconds=900,
    )

    assert store.get("has+unsafe/characters=") is None
    assert table.get_calls == 0

    clock[0] = 1_900.0
    assert store.get(token) is None
    assert table.items == {}
