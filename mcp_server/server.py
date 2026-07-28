"""
Data Retrieval Agent — FastMCP tool server.

Exposes Fabric SQL Gold Layer and Azure AI Search tools over stdio.
No orchestration, LLM calling, or routing logic lives in this package.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from azure_search import hybrid_semantic_search
from fabric_sql import execute_query

mcp = FastMCP(
    "val-fabric-data",
    instructions=(
        "Enterprise data retrieval tools for Microsoft Fabric SQL (Gold) "
        "and Azure AI Search. Use Fabric for relational/financial queries; "
        "use Azure AI Search for unstructured document context."
    ),
)


@mcp.tool()
def query_fabric_sql(sql: str, max_rows: int = 200) -> str:
    """
    Execute a read-only SQL query against the Microsoft Fabric SQL Gold Layer.

    Use for relational / financial intents: purchase orders, vendor spend metrics,
    dates, aggregations, and structured warehouse facts.

    Args:
        sql: A SELECT (or WITH ... SELECT) statement against Gold tables/views.
        max_rows: Maximum rows to return (default 200, hard-capped in executor).

    Returns:
        JSON string with columns, row_count, truncated flag, and rows.
    """
    result = execute_query(sql, max_rows=max_rows)
    return json.dumps(result, default=str)


@mcp.tool()
def search_azure_documents(
    query: str,
    top: int = 5,
    filter_expression: str | None = None,
) -> str:
    """
    Hybrid semantic search over enterprise documents in Azure AI Search.

    Use for unstructured deep document context: legal liabilities, contract
    clauses, raw PDF/text excerpts, and policy language.

    Always runs with query_type=\"semantic\" and hybrid vector+keyword retrieval.

    Args:
        query: Natural-language search text.
        top: Number of documents to return (default 5).
        filter_expression: Optional OData filter on index fields.

    Returns:
        JSON string with matched documents and semantic metadata.
    """
    result = hybrid_semantic_search(
        query,
        top=top,
        filter_expression=filter_expression,
    )
    return json.dumps(result, default=str)


@mcp.tool()
def fabric_health_check() -> str:
    """
    Verify Fabric SQL connectivity using Authentication=ActiveDirectoryDefault.

    Returns a small JSON status payload. Does not run business queries.
    """
    try:
        payload: dict[str, Any] = execute_query("SELECT 1 AS health_check", max_rows=1)
        return json.dumps({"status": "ok", "fabric": payload}, default=str)
    except Exception as exc:  # noqa: BLE001 — surface connection errors to the agent
        return json.dumps({"status": "error", "error": str(exc)})


if __name__ == "__main__":
    mcp.run(transport="stdio")
