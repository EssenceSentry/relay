from __future__ import annotations

from collections.abc import Sequence

from knowledge_core.models import IndexedDocument
from knowledge_core.openai_api import OpenAIService
from knowledge_core.opensearch import OpenSearchServerlessClient


class DocumentIndexer:
    def __init__(
        self,
        *,
        openai: OpenAIService,
        search: OpenSearchServerlessClient,
    ) -> None:
        self._openai = openai
        self._search = search

    def index_document(self, document: IndexedDocument) -> None:
        self.index_documents([document])

    def index_documents(
        self,
        documents: Sequence[IndexedDocument],
    ) -> None:
        if not documents:
            return
        self._search.ensure_index()
        embeddings = self._openai.embed_texts(
            [document.text for document in documents]
        )
        indexed = [
            document.model_copy(update={"embedding": embedding})
            for document, embedding in zip(
                documents,
                embeddings,
                strict=True,
            )
        ]
        self._search.bulk_index(
            [document.search_document() for document in indexed]
        )
