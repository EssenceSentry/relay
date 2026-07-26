from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

import requests
from botocore.credentials import Credentials

from knowledge_core.opensearch import (
    OpenSearchServerlessClient,
    build_index_mapping,
)


def test_index_mapping_contains_text_and_vector_fields() -> None:
    mapping = build_index_mapping(1536)
    properties = mapping["mappings"]["properties"]

    assert mapping["settings"]["index"]["knn"] is True
    assert properties["index_id"]["type"] == "keyword"
    assert properties["text"]["type"] == "text"
    assert properties["project_id"]["type"] == "keyword"
    assert properties["page_number"]["type"] == "integer"
    assert properties["page_count"]["type"] == "integer"
    assert properties["locator"]["type"] == "keyword"
    assert properties["embedding"]["dimension"] == 1536
    assert properties["embedding"]["space_type"] == "cosinesimil"
    assert properties["embedding"]["method"] == {"name": "hnsw"}


def test_signed_headers_include_the_serverless_payload_hash() -> None:
    credentials = Credentials("access-key", "secret-key", "session-token")
    client = OpenSearchServerlessClient(
        endpoint="https://example.invalid",
        region="us-east-1",
        index_name="documents",
        dimensions=3,
        aws_session=AnySession(credentials),
    )
    body = b'{"title":"example"}'

    headers = client._signed_headers(  # pyright: ignore[reportPrivateUsage]
        method="PUT",
        url="https://example.invalid/documents",
        body=body,
        content_type="application/json",
    )

    expected_hash = hashlib.sha256(body).hexdigest()
    assert headers["x-amz-content-sha256"] == expected_hash
    assert "x-amz-content-sha256" in headers["Authorization"]


class AnySession:
    def __init__(self, credentials: Credentials) -> None:
        self._credentials = credentials

    def get_credentials(self) -> Credentials:
        return self._credentials


class CapturingClient(OpenSearchServerlessClient):
    def __init__(self) -> None:
        super().__init__(
            endpoint="https://example.invalid",
            region="us-east-1",
            index_name="documents",
            dimensions=3,
        )
        self.body: dict[str, Any] | None = None

    def _search(self, body: Mapping[str, Any]) -> list[dict[str, Any]]:
        self.body = dict(body)
        return []


def test_vector_search_applies_project_filter() -> None:
    client = CapturingClient()

    client.vector_search(project_id="prj_1", embedding=[0.1, 0.2, 0.3], size=7)

    assert client.body is not None
    knn = client.body["query"]["knn"]["embedding"]
    assert knn["k"] == 7
    assert knn["filter"] == {"term": {"project_id": "prj_1"}}


def test_lexical_search_boosts_source_text_and_filters_project() -> None:
    client = CapturingClient()

    client.lexical_search(
        project_id="prj_1",
        query="snowflake migration",
        size=9,
    )

    assert client.body is not None
    query = client.body["query"]["bool"]
    assert query["filter"] == [{"term": {"project_id": "prj_1"}}]
    assert query["must"][0]["multi_match"]["fields"] == [
        "text^4",
        "document_name^1.5",
    ]


def test_global_lexical_search_omits_project_filter() -> None:
    client = CapturingClient()

    client.lexical_search(
        project_id=None,
        query="customer analytics",
        size=12,
    )

    assert client.body is not None
    query = client.body["query"]["bool"]
    assert "filter" not in query


def test_global_vector_search_omits_project_filter() -> None:
    client = CapturingClient()

    client.vector_search(
        project_id=None,
        embedding=[0.1, 0.2, 0.3],
        size=12,
    )

    assert client.body is not None
    knn = client.body["query"]["knn"]["embedding"]
    assert "filter" not in knn


class DeleteCapturingClient(CapturingClient):
    def __init__(self) -> None:
        super().__init__()
        self.deleted_ids: list[str] = []

    def get_indexed_documents(
        self,
        *,
        project_id: str,
        document_id: str,
        size: int = 10,
    ) -> list[dict[str, Any]]:
        assert project_id == "prj_1"
        assert document_id == "doc_1"
        assert size == 1000
        return [{"_id": "idx_1"}, {"index_id": "idx_2"}]

    def bulk_delete(
        self,
        document_ids: Any,
        *,
        refresh: bool = False,
        batch_size: int = 200,
    ) -> None:
        assert refresh is False
        assert batch_size == 200
        self.deleted_ids = list(document_ids)


def test_delete_document_uses_supported_bulk_deletes() -> None:
    client = DeleteCapturingClient()

    client.delete_document(project_id="prj_1", document_id="doc_1")

    assert client.deleted_ids == ["idx_1", "idx_2"]


class PaginatedClient(OpenSearchServerlessClient):
    def __init__(self) -> None:
        super().__init__(
            endpoint="https://example.invalid",
            region="us-east-1",
            index_name="documents",
            dimensions=3,
        )
        self.bodies: list[Mapping[str, Any]] = []

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, Any] | None = None,
        raw_body: bytes | None = None,
        content_type: str = "application/json",
        acceptable: set[int] | None = None,
    ) -> requests.Response:
        del method, path, raw_body, content_type, acceptable
        assert json_body is not None
        self.bodies.append(json_body)
        page = len(self.bodies)
        hits = (
            [
                {
                    "_id": "idx_1",
                    "_source": {
                        "index_id": "idx_1",
                        "project_id": "prj_1",
                        "embedding": [0.1, 0.2, 0.3],
                    },
                    "sort": ["idx_1"],
                },
                {
                    "_id": "idx_2",
                    "_source": {
                        "index_id": "idx_2",
                        "project_id": "prj_1",
                        "embedding": [0.4, 0.5, 0.6],
                    },
                    "sort": ["idx_2"],
                },
            ]
            if page == 1
            else [
                {
                    "_id": "idx_3",
                    "_source": {
                        "index_id": "idx_3",
                        "project_id": "prj_1",
                        "embedding": [0.7, 0.8, 0.9],
                    },
                    "sort": ["idx_3"],
                }
            ]
        )
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({"hits": {"hits": hits}}).encode()
        return response


def test_get_project_documents_paginates_and_keeps_embeddings() -> None:
    client = PaginatedClient()

    documents = client.get_project_documents(
        project_id="prj_1",
        include_embedding=True,
        page_size=2,
    )

    assert [document["index_id"] for document in documents] == [
        "idx_1",
        "idx_2",
        "idx_3",
    ]
    assert documents[0]["embedding"] == [0.1, 0.2, 0.3]
    assert client.bodies[0]["_source"] == {"includes": ["*"]}
    assert client.bodies[1]["search_after"] == ["idx_2"]
