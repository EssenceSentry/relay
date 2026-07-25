from __future__ import annotations

from typing import Any

from knowledge_core.indexed_documents import build_indexed_document
from knowledge_core.indexing import DocumentIndexer


class FakeOpenAI:
    def __init__(self) -> None:
        self.inputs: list[str] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.inputs.extend(texts)
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeSearch:
    def __init__(self) -> None:
        self.ensure_calls = 0
        self.documents: list[dict[str, Any]] = []

    def ensure_index(self) -> None:
        self.ensure_calls += 1

    def bulk_index(self, documents: list[dict[str, Any]]) -> None:
        self.documents.extend(documents)


def test_indexer_embeds_and_indexes_page_documents_as_one_batch() -> None:
    documents = [
        build_indexed_document(
            text=f"# Page {page_number}",
            project_id="prj_1",
            document_id="doc_1",
            document_version="1",
            document_name="dossier.pdf",
            s3_bucket="bucket",
            s3_key="uploads/prj_1/doc_1/dossier.pdf",
            page_number=page_number,
            page_count=2,
            locator=f"page {page_number} of 2",
        )
        for page_number in (1, 2)
    ]
    openai = FakeOpenAI()
    search = FakeSearch()
    indexer = DocumentIndexer(
        openai=openai,  # type: ignore[arg-type]
        search=search,  # type: ignore[arg-type]
    )

    indexer.index_documents(documents)

    assert openai.inputs == [document.text for document in documents]
    assert search.ensure_calls == 1
    assert len(search.documents) == 2
    assert search.documents[0]["index_id"] == documents[0].index_id
    assert search.documents[1]["page_number"] == 2
    assert search.documents[0]["embedding"] == [0.1, 0.2, 0.3]
