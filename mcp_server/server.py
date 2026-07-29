"""
Data Retrieval Agent — FastMCP tool server.

Exposes Fabric SQL Gold Layer and Azure AI Search tools over stdio.
No orchestration, LLM calling, or routing logic lives in this package.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Offline mock interceptor (staging only)
# Activated solely by USE_OFFLINE_MOCKS. Production tool bodies below stay
# free of mock conditionals and always call real SQL / Azure SDK paths.
# ---------------------------------------------------------------------------
_OFFLINE_MOCKS_ENABLED = os.getenv("USE_OFFLINE_MOCKS", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
_FIXTURE_PATCHES: list[Any] = []


def _load_offline_fixtures() -> dict[str, Any]:
    fixture_path = Path(__file__).resolve().parent / "test_fixtures.json"
    with fixture_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("test_fixtures.json must be a JSON object of table/list payloads")
    return payload


def _install_offline_mock_interceptor() -> None:
    """Patch pyodbc / pandas / Azure SearchClient before production tools run."""
    fixtures = _load_offline_fixtures()
    table_fixtures = {
        name: rows
        for name, rows in fixtures.items()
        if name != "Azure_Search_Documents" and isinstance(rows, list)
    }
    search_documents = fixtures.get("Azure_Search_Documents") or []
    if not isinstance(search_documents, list):
        raise ValueError("Azure_Search_Documents fixture must be a list")

    def _resolve_table_rows(sql: str) -> list[dict[str, Any]]:
        normalized = " ".join((sql or "").split()).lower()
        # Prefer the longest matching table token so similar names don't collide.
        matches = [
            name
            for name in table_fixtures
            if name.lower() in normalized
        ]
        if matches:
            best = max(matches, key=len)
            return list(table_fixtures[best])
        if normalized.startswith("select 1") or "health_check" in normalized:
            return [{"health_check": 1}]
        return []

    def _mock_connect(*_args: Any, **_kwargs: Any) -> MagicMock:
        conn = MagicMock(name="OfflinePyodbcConnection")
        conn.__enter__.return_value = conn
        conn.__exit__.return_value = False
        conn.close.return_value = None
        return conn

    def _mock_read_sql(sql: str, con: Any = None, params: Any = None, **_kwargs: Any) -> pd.DataFrame:
        del con, params  # unused — offline path never hits a live cursor
        return pd.DataFrame(_resolve_table_rows(sql))

    class _OfflineSearchClient:
        """Drop-in stand-in for azure.search.documents.SearchClient."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            del args, kwargs

        def search(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
            del args
            docs = [dict(doc) for doc in search_documents]
            query = (kwargs.get("search_text") or "").strip().lower()
            top = kwargs.get("top")
            if query:
                filtered = [
                    doc
                    for doc in docs
                    if query in json.dumps(doc, default=str).lower()
                ]
                # Fall back to the full fixture set when the query is too narrow
                # for keyword matching against static staging documents.
                docs = filtered or docs
            if isinstance(top, int) and top >= 0:
                docs = docs[:top]
            return docs

    _FIXTURE_PATCHES.extend(
        [
            patch("pyodbc.connect", side_effect=_mock_connect),
            patch("pandas.read_sql", side_effect=_mock_read_sql),
            patch("azure.search.documents.SearchClient", _OfflineSearchClient),
        ]
    )
    for active_patch in _FIXTURE_PATCHES:
        active_patch.start()


if _OFFLINE_MOCKS_ENABLED:
    # Satisfy config.require() gates without real cloud credentials.
    os.environ.setdefault("FABRIC_SQL_SERVER", "offline.local")
    os.environ.setdefault("FABRIC_SQL_DATABASE", "gold_layer")
    os.environ.setdefault("AZURE_SEARCH_ENDPOINT", "https://offline.search.windows.net")
    os.environ.setdefault("AZURE_SEARCH_API_KEY", "offline-key")
    os.environ.setdefault("AZURE_SEARCH_INDEX_NAME", "documents")
    _install_offline_mock_interceptor()

# Import infrastructure modules AFTER optional patches so their bound drivers
# resolve to the offline stand-ins when USE_OFFLINE_MOCKS is enabled.
from azure_search import hybrid_semantic_search  # noqa: E402
from fabric_sql import execute_query  # noqa: E402

if _OFFLINE_MOCKS_ENABLED:
    # Avoid building a real Fabric ODBC connection string during offline staging.
    patch(
        "fabric_sql._connection_string",
        return_value=(
            "Driver={ODBC Driver 18 for SQL Server};"
            "Server=offline.local;"
            "Database=gold_layer;"
            "Encrypt=yes;"
            "TrustServerCertificate=no;"
            "Authentication=ActiveDirectoryDefault;"
        ),
    ).start()

mcp = FastMCP(
    "val-fabric-data",
    instructions=(
        "Enterprise data retrieval tools for Microsoft Fabric SQL (Gold) "
        "and Azure AI Search. Use Fabric for relational/financial queries; "
        "use Azure AI Search for unstructured document context."
    ),
)


@mcp.tool()
def get_expiring_contracts(days_ahead: int = 90, max_rows: int = 200) -> str:
    """
    Return vendor contracts approaching expiration from the Fabric Gold layer.

    Use for relational / financial intents involving contract renewal dates,
    upcoming expirations, and structured contract warehouse facts.

    Args:
        days_ahead: Lookahead window in days from today (default 90).
        max_rows: Maximum rows to return (default 200).

    Returns:
        JSON string with columns, row_count, truncated flag, and rows.
    """
    sql = f"""
        SELECT
            ContractID,
            ContractNumber,
            ContractName,
            ContractType,
            ContractStatus,
            SupplierID,
            SupplierName,
            ContractValue,
            AnnualContractValue,
            Currency,
            EffectiveDate,
            ExpirationDate,
            RenewalDate,
            AutoRenewalFlag,
            BusinessUnit,
            ContractOwner
        FROM Gold_Vendor_Contracts
        WHERE ExpirationDate IS NOT NULL
          AND CAST(ExpirationDate AS date) >= CAST(GETDATE() AS date)
          AND CAST(ExpirationDate AS date) <= DATEADD(day, {int(days_ahead)}, CAST(GETDATE() AS date))
        ORDER BY ExpirationDate ASC
    """
    result = execute_query(sql, max_rows=max_rows)
    return json.dumps(result, default=str)


@mcp.tool()
def get_vendor_spend_summary(max_rows: int = 200) -> str:
    """
    Return vendor spend rollups from the Fabric SQL Gold Layer.

    Use for relational / financial intents: supplier spend metrics, contract
    value aggregates, and structured warehouse facts.

    Args:
        max_rows: Maximum rows to return (default 200).

    Returns:
        JSON string with columns, row_count, truncated flag, and rows.
    """
    sql = """
        SELECT
            SupplierID,
            SupplierName,
            ContractCount,
            TotalContractValue,
            TotalAnnualContractValue,
            Currency,
            BusinessUnits
        FROM Gold_Vendor_Spend
        ORDER BY TotalContractValue DESC
    """
    result = execute_query(sql, max_rows=max_rows)
    return json.dumps(result, default=str)


@mcp.tool()
def search_cloud_blob_contracts(
    query: str,
    top: int = 5,
    filter_expression: str | None = None,
) -> str:
    """
    Hybrid semantic search over cloud-blob contract documents in Azure AI Search.

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
