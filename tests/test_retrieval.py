from __future__ import annotations

import pytest

from knowledge_core.retrieval import RetrievalService, reciprocal_rank_fusion


def hit(
    index_id: str,
    score: float,
    text: str | None = None,
) -> dict[str, object]:
    return {
        "index_id": index_id,
        "project_id": "prj_1",
        "document_id": "doc_1",
        "document_name": "source.md",
        "text": text or index_id,
        "_score": score,
    }


def test_rrf_rewards_cross_channel_agreement_and_preserves_raw_scores() -> None:
    lexical = [hit("a", 12.5), hit("b", 8.0)]
    vector = [hit("b", 0.91), hit("c", 0.84)]

    result = reciprocal_rank_fusion(lexical, vector, rank_constant=60)

    assert [item.index_id for item in result] == ["b", "a", "c"]
    assert result[0].bm25_rank == 2
    assert result[0].vector_rank == 1
    assert result[0].bm25_score == 8.0
    assert result[0].vector_score == 0.91
    assert result[0].rrf_score == pytest.approx(1 / 62 + 1 / 61)


def test_rrf_rejects_non_positive_rank_constant() -> None:
    with pytest.raises(ValueError, match="positive"):
        reciprocal_rank_fusion([], [], rank_constant=0)


class FakeOpenAI:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [[0.1, 0.2, 0.3]]


class FakeSearch:
    def __init__(self) -> None:
        self.ensure_calls = 0
        self.lexical_args: dict[str, object] | None = None
        self.vector_args: dict[str, object] | None = None

    def ensure_index(self) -> None:
        self.ensure_calls += 1

    def lexical_search(
        self,
        *,
        project_id: str | None,
        query: str,
        size: int,
    ) -> list[dict[str, object]]:
        self.lexical_args = {
            "project_id": project_id,
            "query": query,
            "size": size,
        }
        return [
            global_hit("p1-page-1", "prj_1", "doc_1", 12),
            global_hit("p1-page-2", "prj_1", "doc_1", 10),
            global_hit("p2-page-1", "prj_2", "doc_2", 8),
        ]

    def vector_search(
        self,
        *,
        project_id: str | None,
        embedding: list[float],
        size: int,
    ) -> list[dict[str, object]]:
        self.vector_args = {
            "project_id": project_id,
            "embedding": embedding,
            "size": size,
        }
        return [
            global_hit("p1-page-2", "prj_1", "doc_1", 0.95),
            global_hit("p3-page-1", "prj_3", "doc_3", 0.89),
        ]


def global_hit(
    index_id: str,
    project_id: str,
    document_id: str,
    score: float,
) -> dict[str, object]:
    return {
        "index_id": index_id,
        "project_id": project_id,
        "document_id": document_id,
        "document_name": f"{document_id}.md",
        "text": f"Evidence from {document_id}",
        "_score": score,
    }


def test_global_search_uses_hybrid_backend_and_deduplicates_documents() -> None:
    openai = FakeOpenAI()
    search = FakeSearch()
    retrieval = RetrievalService(
        openai=openai,  # type: ignore[arg-type]
        search=search,  # type: ignore[arg-type]
    )

    response = retrieval.search_across_projects(
        query="supply chain outcomes",
        top_k=2,
    )

    assert [hit.document_id for hit in response.hits] == ["doc_1", "doc_3"]
    assert openai.calls == [["supply chain outcomes"]]
    assert search.ensure_calls == 1
    assert search.lexical_args == {
        "project_id": None,
        "query": "supply chain outcomes",
        "size": 30,
    }
    assert search.vector_args == {
        "project_id": None,
        "embedding": [0.1, 0.2, 0.3],
        "size": 30,
    }
