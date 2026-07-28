"""Azure AI Search hybrid semantic query execution."""

from __future__ import annotations

import logging
from typing import Any

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient

from config import get, require

logger = logging.getLogger(__name__)


def _client() -> SearchClient:
    endpoint = require("AZURE_SEARCH_ENDPOINT")
    api_key = require("AZURE_SEARCH_API_KEY")
    index_name = require("AZURE_SEARCH_INDEX_NAME")
    return SearchClient(
        endpoint=endpoint,
        index_name=index_name,
        credential=AzureKeyCredential(api_key),
    )


def _serialize_results(results: Any, query: str, semantic_config: str) -> dict[str, Any]:
    documents: list[dict[str, Any]] = []
    for doc in results:
        item = dict(doc)
        item.pop("contentVector", None)
        documents.append(item)
    return {
        "query": query,
        "query_type": "semantic",
        "semantic_configuration_name": semantic_config,
        "count": len(documents),
        "documents": documents,
    }


def hybrid_semantic_search(
    query: str,
    *,
    top: int = 5,
    filter_expression: str | None = None,
    select: list[str] | None = None,
) -> dict[str, Any]:
    """
    Run a hybrid semantic search (`query_type=\"semantic\"`) against Azure AI Search.

    Prefers keyword + vector hybrid retrieval; falls back to semantic keyword-only
    if the index has no vectorizable field configured.
    """
    if not query or not query.strip():
        raise ValueError("Search query must be a non-empty string")

    semantic_config = get("AZURE_SEARCH_SEMANTIC_CONFIG", "default")
    client = _client()

    base_kwargs: dict[str, Any] = {
        "search_text": query,
        "query_type": "semantic",
        "semantic_configuration_name": semantic_config,
        "top": top,
        "include_total_count": True,
    }
    if filter_expression:
        base_kwargs["filter"] = filter_expression
    if select:
        base_kwargs["select"] = select

    # Attempt hybrid (semantic + vectorizable text query).
    try:
        from azure.search.documents.models import VectorizableTextQuery

        hybrid_kwargs = {
            **base_kwargs,
            "vector_queries": [
                VectorizableTextQuery(
                    text=query,
                    k_nearest_neighbors=max(top, 5),
                    fields="contentVector",
                )
            ],
        }
        results = client.search(**hybrid_kwargs)
        payload = _serialize_results(results, query, semantic_config)
        payload["mode"] = "hybrid_semantic"
        return payload
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Hybrid vector query unavailable (%s); falling back to semantic keyword search",
            exc,
        )

    results = client.search(**base_kwargs)
    payload = _serialize_results(results, query, semantic_config)
    payload["mode"] = "semantic"
    return payload
