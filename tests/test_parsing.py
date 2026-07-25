from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from knowledge_core.parsing import UnsupportedDocumentError, parse_document


def test_plain_text_parser() -> None:
    sections = parse_document(b"Hello\n\nworld", "notes.txt")

    assert len(sections) == 1
    assert sections[0].text == "Hello\n\nworld"
    assert sections[0].locator == "document"


def test_json_parser_pretty_prints_data() -> None:
    sections = parse_document(
        json.dumps({"customer": "Blend"}).encode(), "facts.json"
    )

    assert '"customer": "Blend"' in sections[0].text


def test_legacy_doc_parser_preserves_body_and_textboxes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed = SimpleNamespace(
        body_text="# Case study\n\nExtracted body",
        textboxes=["Callout text", ""],
    )

    def parse_doc(data: bytes) -> SimpleNamespace | None:
        return parsed if data == b"legacy-doc" else None

    fake_unword = SimpleNamespace(parse_doc=parse_doc)
    monkeypatch.setitem(sys.modules, "unword", fake_unword)

    sections = parse_document(b"legacy-doc", "case-study.DOC")

    assert [section.text for section in sections] == [
        "# Case study\n\nExtracted body",
        "Callout text",
    ]
    assert sections[0].locator == "document"
    assert sections[1].locator == "text box 1"


def test_unsupported_extension_is_explicit() -> None:
    with pytest.raises(UnsupportedDocumentError, match="Unsupported"):
        parse_document(b"x", "archive.zip")
