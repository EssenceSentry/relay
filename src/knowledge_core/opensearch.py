from __future__ import annotations

import hashlib
import json
import random
import time
from collections.abc import Iterable, Mapping
from typing import Any, Protocol, TypeGuard, cast
from urllib.parse import quote, urljoin

import boto3
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

_RETRYABLE_STATUS = {403, 404, 408, 409, 429, 500, 502, 503, 504}


def _is_string_mapping(value: object) -> TypeGuard[dict[str, Any]]:
    return isinstance(value, dict)


def _is_mapping_list(value: object) -> TypeGuard[list[dict[str, Any]]]:
    if not isinstance(value, list):
        return False
    items = cast(list[object], value)
    return all(isinstance(item, dict) for item in items)


def _is_search_after(
    value: object,
) -> TypeGuard[list[str | int | float]]:
    if not isinstance(value, list):
        return False
    items = cast(list[object], value)
    return bool(items) and all(
        isinstance(item, str | int | float) for item in items
    )


class CredentialSession(Protocol):
    def get_credentials(self) -> Credentials | None: ...


def build_index_mapping(dimensions: int) -> dict[str, Any]:
    if dimensions <= 0:
        raise ValueError("dimensions must be positive")
    return {
        "settings": {"index": {"knn": True}},
        "mappings": {
            "dynamic": "strict",
            "properties": {
                "index_id": {"type": "keyword"},
                "project_id": {"type": "keyword"},
                "document_id": {"type": "keyword"},
                "document_version": {"type": "keyword"},
                "document_name": {
                    "type": "text",
                    "fields": {"keyword": {"type": "keyword"}},
                },
                "source_type": {"type": "keyword"},
                "text": {"type": "text"},
                "content_hash": {"type": "keyword"},
                "s3_bucket": {"type": "keyword"},
                "s3_key": {"type": "keyword"},
                "page_number": {"type": "integer"},
                "page_count": {"type": "integer"},
                "locator": {"type": "keyword"},
                "embedding": {
                    "type": "knn_vector",
                    "dimension": dimensions,
                    "space_type": "cosinesimil",
                    "method": {"name": "hnsw"},
                },
            },
        },
    }


class OpenSearchServerlessClient:
    def __init__(
        self,
        *,
        endpoint: str,
        region: str,
        index_name: str,
        dimensions: int,
        timeout_seconds: float = 22.0,
        max_attempts: int = 6,
        aws_session: CredentialSession | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/") + "/"
        self._region = region
        self._index_name = index_name
        self._dimensions = dimensions
        self._timeout = timeout_seconds
        self._max_attempts = max_attempts
        self._aws_session = aws_session or boto3.Session(region_name=region)
        self._index_ready = False

    @property
    def index_name(self) -> str:
        return self._index_name

    def ensure_index(self) -> None:
        if self._index_ready:
            return
        path = quote(self._index_name, safe="")
        response = self.request("HEAD", path, acceptable={200, 404})
        if response.status_code == 200:
            self._ensure_page_mapping(path)
            self._index_ready = True
            return
        create = self.request(
            "PUT",
            path,
            json_body=build_index_mapping(self._dimensions),
            acceptable={200, 201, 400},
        )
        if create.status_code == 400:
            payload = _safe_json(create)
            error_type = (
                payload.get("error", {}).get("type")
                if isinstance(payload.get("error"), dict)
                else None
            )
            if error_type not in {
                "resource_already_exists_exception",
                "index_already_exists_exception",
            }:
                create.raise_for_status()
        self._ensure_page_mapping(path)
        self._index_ready = True

    def _ensure_page_mapping(self, path: str) -> None:
        self.request(
            "PUT",
            f"{path}/_mapping",
            json_body={
                "properties": {
                    "page_number": {"type": "integer"},
                    "page_count": {"type": "integer"},
                    "locator": {"type": "keyword"},
                }
            },
        )

    def bulk_index(
        self,
        documents: Iterable[Mapping[str, Any]],
        *,
        refresh: bool = False,
        batch_size: int = 64,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")

        batch: list[Mapping[str, Any]] = []
        for document in documents:
            batch.append(document)
            if len(batch) >= batch_size:
                self._bulk_index_batch(batch, refresh=refresh)
                batch.clear()
        if batch:
            self._bulk_index_batch(batch, refresh=refresh)

    def _bulk_index_batch(
        self,
        documents: list[Mapping[str, Any]],
        *,
        refresh: bool,
    ) -> None:
        lines: list[str] = []
        for document in documents:
            index_id = str(document["index_id"])
            lines.append(
                json.dumps(
                    {
                        "index": {
                            "_index": self._index_name,
                            "_id": index_id,
                        }
                    },
                    separators=(",", ":"),
                )
            )
            lines.append(
                json.dumps(document, ensure_ascii=False, separators=(",", ":"))
            )

        payload = self._send_bulk(lines, refresh=refresh)
        self._raise_bulk_failures(payload, operation="index")

    def bulk_delete(
        self,
        document_ids: Iterable[str],
        *,
        refresh: bool = False,
        batch_size: int = 200,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")

        lines: list[str] = []
        actions = 0
        for document_id in document_ids:
            lines.append(
                json.dumps(
                    {
                        "delete": {
                            "_index": self._index_name,
                            "_id": document_id,
                        }
                    },
                    separators=(",", ":"),
                )
            )
            actions += 1
            if actions >= batch_size:
                payload = self._send_bulk(lines, refresh=refresh)
                self._raise_bulk_failures(
                    payload,
                    operation="delete",
                    ignored_statuses={404},
                )
                lines.clear()
                actions = 0
        if lines:
            payload = self._send_bulk(lines, refresh=refresh)
            self._raise_bulk_failures(
                payload,
                operation="delete",
                ignored_statuses={404},
            )

    def _send_bulk(
        self,
        lines: list[str],
        *,
        refresh: bool,
    ) -> dict[str, Any]:
        body = ("\n".join(lines) + "\n").encode("utf-8")
        suffix = "_bulk?refresh=true" if refresh else "_bulk"
        response = self.request(
            "POST",
            suffix,
            raw_body=body,
            content_type="application/x-ndjson",
        )
        return _safe_json(response)

    @staticmethod
    def _raise_bulk_failures(
        payload: Mapping[str, Any],
        *,
        operation: str,
        ignored_statuses: set[int] | None = None,
    ) -> None:
        if not payload.get("errors"):
            return
        ignored = ignored_statuses or set()
        failures: list[Mapping[str, Any]] = []
        for item in payload.get("items", []):
            result = item.get(operation, {})
            if result.get("error") and result.get("status") not in ignored:
                failures.append(result)
                if len(failures) == 5:
                    break
        if failures:
            raise RuntimeError(
                f"OpenSearch bulk {operation} operation failed: {failures}"
            )

    def lexical_search(
        self,
        *,
        project_id: str | None,
        query: str,
        size: int,
    ) -> list[dict[str, Any]]:
        bool_query: dict[str, Any] = {
            "must": [
                {
                    "multi_match": {
                        "query": query,
                        "fields": [
                            "text^4",
                            "document_name^1.5",
                        ],
                        "type": "best_fields",
                        "operator": "or",
                    }
                }
            ]
        }
        if project_id is not None:
            bool_query["filter"] = [{"term": {"project_id": project_id}}]
        body = {
            "size": size,
            "_source": {"excludes": ["embedding"]},
            "query": {"bool": bool_query},
        }
        return self._search(body)

    def vector_search(
        self,
        *,
        project_id: str | None,
        embedding: list[float],
        size: int,
    ) -> list[dict[str, Any]]:
        vector_query: dict[str, Any] = {
            "vector": embedding,
            "k": size,
        }
        if project_id is not None:
            vector_query["filter"] = {"term": {"project_id": project_id}}
        body = {
            "size": size,
            "_source": {"excludes": ["embedding"]},
            "query": {"knn": {"embedding": vector_query}},
        }
        return self._search(body)

    def get_indexed_documents(
        self,
        *,
        project_id: str,
        document_id: str,
        size: int = 10,
    ) -> list[dict[str, Any]]:
        body = {
            "size": size,
            "_source": {"excludes": ["embedding"]},
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"project_id": project_id}},
                        {"term": {"document_id": document_id}},
                    ]
                }
            },
        }
        documents = self._search(body)
        return sorted(
            documents,
            key=lambda document: (
                int(document.get("page_number") or 0),
                str(document.get("index_id") or document.get("_id") or ""),
            ),
        )

    def get_indexed_document(
        self,
        *,
        project_id: str,
        document_id: str,
    ) -> dict[str, Any] | None:
        documents = self.get_indexed_documents(
            project_id=project_id,
            document_id=document_id,
            size=1,
        )
        return documents[0] if documents else None

    def get_project_documents(
        self,
        *,
        project_id: str,
        include_embedding: bool = False,
        page_size: int = 500,
    ) -> list[dict[str, Any]]:
        if page_size <= 0 or page_size > 1000:
            raise ValueError("page_size must be between 1 and 1000")
        path = f"{quote(self._index_name, safe='')}/_search"
        search_after: list[str | int | float] | None = None
        documents: list[dict[str, Any]] = []
        while True:
            body: dict[str, Any] = {
                "size": page_size,
                "query": {"term": {"project_id": project_id}},
                "sort": [{"index_id": {"order": "asc"}}],
            }
            if include_embedding:
                body["_source"] = {"includes": ["*"]}
            else:
                body["_source"] = {"excludes": ["embedding"]}
            if search_after is not None:
                body["search_after"] = search_after
            response = self.request("POST", path, json_body=body)
            payload = _safe_json(response)
            raw_hit_group = payload.get("hits")
            if not _is_string_mapping(raw_hit_group):
                raise RuntimeError("OpenSearch returned invalid search hits")
            raw_hits = raw_hit_group.get("hits")
            if not _is_mapping_list(raw_hits):
                raise RuntimeError("OpenSearch returned invalid search hits")
            for raw_hit in raw_hits:
                raw_source = raw_hit.get("_source")
                if not _is_string_mapping(raw_source):
                    raise RuntimeError("OpenSearch returned an invalid hit")
                source = dict(raw_source)
                source["_id"] = raw_hit.get("_id")
                documents.append(source)
            if len(raw_hits) < page_size:
                break
            last_hit = raw_hits[-1]
            raw_sort = last_hit.get("sort")
            if not _is_search_after(raw_sort):
                raise RuntimeError(
                    "OpenSearch pagination response has no sort value"
                )
            search_after = raw_sort
        return documents

    def delete_document(self, *, project_id: str, document_id: str) -> None:
        # OpenSearch Serverless does not support _delete_by_query. Resolve the
        # deterministic index IDs and remove them with the supported bulk API.
        documents = self.get_indexed_documents(
            project_id=project_id,
            document_id=document_id,
            size=1000,
        )
        self.bulk_delete(
            str(document.get("_id") or document["index_id"])
            for document in documents
        )

    def _search(self, body: Mapping[str, Any]) -> list[dict[str, Any]]:
        path = f"{quote(self._index_name, safe='')}/_search"
        response = self.request("POST", path, json_body=body)
        payload = _safe_json(response)
        hits = payload.get("hits", {}).get("hits", [])
        results: list[dict[str, Any]] = []
        for item in hits:
            source = dict(item.get("_source") or {})
            source["_score"] = item.get("_score")
            source["_id"] = item.get("_id")
            results.append(source)
        return results

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
        if json_body is not None and raw_body is not None:
            raise ValueError("Specify either json_body or raw_body, not both")
        body = raw_body
        if json_body is not None:
            body = json.dumps(json_body, separators=(",", ":")).encode("utf-8")

        url = urljoin(self._endpoint, path.lstrip("/"))
        expected = acceptable or {200, 201}
        last_response: requests.Response | None = None
        last_error: Exception | None = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                headers = self._signed_headers(
                    method=method,
                    url=url,
                    body=body,
                    content_type=content_type,
                )
                response = requests.request(
                    method,
                    url,
                    data=body,
                    headers=headers,
                    timeout=self._timeout,
                )
                last_response = response
                if response.status_code in expected:
                    return response
                if (
                    response.status_code not in _RETRYABLE_STATUS
                    or attempt == self._max_attempts
                ):
                    response.raise_for_status()
            except requests.RequestException as exc:
                last_error = exc
                if attempt == self._max_attempts:
                    raise

            sleep = min(8.0, 0.35 * (2 ** (attempt - 1)))
            sleep *= 0.8 + random.random() * 0.4
            time.sleep(sleep)

        if last_response is not None:
            last_response.raise_for_status()
        raise RuntimeError("OpenSearch request failed") from last_error

    def _signed_headers(
        self,
        *,
        method: str,
        url: str,
        body: bytes | None,
        content_type: str,
    ) -> dict[str, str]:
        credentials = self._aws_session.get_credentials()
        if credentials is None:
            raise RuntimeError("No AWS credentials available for OpenSearch")
        frozen = credentials.get_frozen_credentials()
        payload = body or b""
        headers = {
            "content-type": content_type,
            "x-amz-content-sha256": hashlib.sha256(payload).hexdigest(),
        }
        request = AWSRequest(
            method=method,
            url=url,
            data=body,
            headers=headers,
        )
        SigV4Auth(frozen, "aoss", self._region).add_auth(request)
        return dict(request.headers.items())


def _safe_json(response: requests.Response) -> dict[str, Any]:
    try:
        payload: object = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"OpenSearch returned non-JSON response: {response.text[:500]}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError("OpenSearch returned an unexpected JSON value")
    return cast(dict[str, Any], payload)
