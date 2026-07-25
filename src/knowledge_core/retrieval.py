from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from knowledge_core.models import (
    GlobalSearchResponse,
    SearchHit,
    SearchResponse,
)
from knowledge_core.openai_api import OpenAIService
from knowledge_core.opensearch import OpenSearchServerlessClient


def reciprocal_rank_fusion(
    lexical_hits: list[dict[str, Any]],
    vector_hits: list[dict[str, Any]],
    *,
    rank_constant: int = 60,
) -> list[SearchHit]:
    if rank_constant <= 0:
        raise ValueError("rank_constant must be positive")

    merged: dict[str, dict[str, Any]] = {}

    def add(
        hits: list[dict[str, Any]],
        *,
        channel: str,
    ) -> None:
        for rank, raw in enumerate(hits, start=1):
            index_id = str(raw.get("index_id") or raw.get("_id") or "")
            if not index_id:
                continue
            entry = merged.setdefault(
                index_id,
                {
                    **raw,
                    "index_id": index_id,
                    "rrf_score": 0.0,
                    "bm25_score": None,
                    "vector_score": None,
                    "bm25_rank": None,
                    "vector_rank": None,
                },
            )
            entry["rrf_score"] += 1.0 / (rank_constant + rank)
            entry[f"{channel}_rank"] = rank
            entry[f"{channel}_score"] = raw.get("_score")

    add(lexical_hits, channel="bm25")
    add(vector_hits, channel="vector")

    def score_or_negative_infinity(item: dict[str, Any], key: str) -> float:
        value = item.get(key)
        return float(value) if value is not None else float("-inf")

    ranked = sorted(
        merged.values(),
        key=lambda item: (
            item["rrf_score"],
            score_or_negative_infinity(item, "vector_score"),
            score_or_negative_infinity(item, "bm25_score"),
        ),
        reverse=True,
    )
    return [SearchHit.model_validate(item) for item in ranked]


class RetrievalService:
    def __init__(
        self,
        *,
        openai: OpenAIService,
        search: OpenSearchServerlessClient,
        candidate_count: int = 30,
    ) -> None:
        self._openai = openai
        self._search = search
        self._candidate_count = candidate_count

    def search(
        self,
        *,
        project_id: str,
        query: str,
        top_k: int = 8,
    ) -> SearchResponse:
        candidate_count = max(top_k, self._candidate_count)
        fused, warnings = self._hybrid_search(
            project_id=project_id,
            query=query,
            candidate_count=candidate_count,
        )
        return SearchResponse(
            project_id=project_id,
            query=query,
            hits=fused[:top_k],
            warnings=warnings,
        )

    def search_across_projects(
        self,
        *,
        query: str,
        top_k: int = 20,
    ) -> GlobalSearchResponse:
        candidate_count = max(top_k * 4, self._candidate_count)
        fused, warnings = self._hybrid_search(
            project_id=None,
            query=query,
            candidate_count=candidate_count,
        )
        unique_documents: list[SearchHit] = []
        seen_documents: set[tuple[str, str]] = set()
        for hit in fused:
            key = (hit.project_id, hit.document_id)
            if key in seen_documents:
                continue
            seen_documents.add(key)
            unique_documents.append(hit)
            if len(unique_documents) == top_k:
                break
        return GlobalSearchResponse(
            query=query,
            hits=unique_documents,
            warnings=warnings,
        )

    def _hybrid_search(
        self,
        *,
        project_id: str | None,
        query: str,
        candidate_count: int,
    ) -> tuple[list[SearchHit], list[str]]:
        self._search.ensure_index()
        warnings: list[str] = []
        lexical_hits: list[dict[str, Any]] = []
        vector_hits: list[dict[str, Any]] = []

        def vector_channel() -> list[dict[str, Any]]:
            embedding = self._openai.embed_texts([query])[0]
            return self._search.vector_search(
                project_id=project_id,
                embedding=embedding,
                size=candidate_count,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            lexical_future = executor.submit(
                self._search.lexical_search,
                project_id=project_id,
                query=query,
                size=candidate_count,
            )
            vector_future = executor.submit(vector_channel)

            try:
                lexical_hits = lexical_future.result()
            except Exception as exc:
                warnings.append(
                    f"BM25 channel failed: {type(exc).__name__}: {exc}"
                )

            try:
                vector_hits = vector_future.result()
            except Exception as exc:
                warnings.append(
                    f"Vector channel failed: {type(exc).__name__}: {exc}"
                )

        return reciprocal_rank_fusion(lexical_hits, vector_hits), warnings
