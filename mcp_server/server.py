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
from contract_analytics import (  # noqa: E402
    DEFAULT_REQUIRED_FIELDS,
    build_criteria,
    check_missing_fields_in_rows,
    compare_contract_rows,
    filter_contracts,
    resolve_contract,
)
from fabric_sql import execute_query  # noqa: E402


def _load_vendor_contracts(max_rows: int = 500) -> list[dict[str, Any]]:
    """Fetch Gold vendor contracts for analytics tools."""
    sql = """
        SELECT
            ContractID,
            ContractNumber,
            ContractName,
            ContractType,
            AgreementType,
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
            ContractOwner,
            ParentContractID,
            ParentContractNumber,
            ContractVersion,
            SupplierRiskRating,
            NoticePeriodDays,
            ContractURL
        FROM Gold_Vendor_Contracts
    """
    payload = execute_query(sql, max_rows=max_rows)
    rows = payload.get("rows") or []
    return [row for row in rows if isinstance(row, dict)]


def _rows_payload(rows: list[dict[str, Any]], *, criteria: dict[str, Any] | None = None) -> dict[str, Any]:
    columns: list[str] = list(rows[0].keys()) if rows else []
    return {
        "columns": columns,
        "row_count": len(rows),
        "truncated": False,
        "criteria": criteria or {},
        "rows": rows,
    }


def _resolve_or_error(
    rows: list[dict[str, Any]],
    criteria: dict[str, Any],
    *,
    side_label: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    resolved = resolve_contract(rows, criteria)
    contract = resolved.get("contract")
    if contract is not None:
        return contract, None
    return None, {
        "error": f"Could not uniquely resolve {side_label} contract from criteria",
        "side": side_label,
        "criteria": criteria,
        "match_count": resolved.get("match_count", 0),
        "candidates": resolved.get("candidates", []),
        "ambiguous": resolved.get("ambiguous", False),
    }

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
def get_expiring_contracts(
    days_ahead: int = 90,
    max_rows: int = 200,
    contract_ref: str | None = None,
    supplier_name: str | None = None,
    contract_name: str | None = None,
    contract_type: str | None = None,
    annual_cost: float | None = None,
) -> str:
    """
    Return vendor contracts approaching expiration from the Fabric Gold layer.

    Optional shared lookup filters narrow results by ContractID/Number,
    SupplierName, ContractName, ContractType, or AnnualContractValue.

    Args:
        days_ahead: Lookahead window in days from today (default 90).
        max_rows: Maximum rows to return (default 200).
        contract_ref: Optional ContractID or ContractNumber filter.
        supplier_name: Optional supplier name filter (e.g. Microsoft).
        contract_name: Optional contract name filter.
        contract_type: Optional contract type filter (e.g. SaaS Subscription).
        annual_cost: Optional annual contract value filter.

    Returns:
        JSON string with columns, row_count, criteria, and rows.
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
    rows = [row for row in (result.get("rows") or []) if isinstance(row, dict)]
    criteria = build_criteria(
        contract_ref=contract_ref,
        supplier_name=supplier_name,
        contract_name=contract_name,
        contract_type=contract_type,
        annual_cost=annual_cost,
    )
    if criteria:
        rows = filter_contracts(rows, criteria)
    payload = _rows_payload(rows, criteria=criteria)
    return json.dumps(payload, default=str)


@mcp.tool()
def get_vendor_spend_summary(
    max_rows: int = 200,
    supplier_name: str | None = None,
    contract_type: str | None = None,
    annual_cost: float | None = None,
) -> str:
    """
    Return vendor spend rollups from the Fabric SQL Gold Layer.

    Optional filters use the same lookup dimensions as contract analytics:
    SupplierName, ContractType (via contract rollups), and annual cost.

    Args:
        max_rows: Maximum rows to return (default 200).
        supplier_name: Optional supplier name filter.
        contract_type: Optional contract type filter applied via contract rows.
        annual_cost: Optional annual-cost filter applied via contract rows.

    Returns:
        JSON string with columns, row_count, criteria, and rows.
    """
    criteria = build_criteria(
        supplier_name=supplier_name,
        contract_type=contract_type,
        annual_cost=annual_cost,
    )

    # When type/cost filters are present, derive spend from filtered contracts.
    if criteria.get("contract_type") or criteria.get("annual_cost"):
        contracts = filter_contracts(_load_vendor_contracts(max_rows=500), criteria)
        rolled: dict[str, dict[str, Any]] = {}
        for row in contracts:
            key = str(row.get("SupplierID") or row.get("SupplierName") or "UNKNOWN")
            bucket = rolled.setdefault(
                key,
                {
                    "SupplierID": row.get("SupplierID"),
                    "SupplierName": row.get("SupplierName"),
                    "ContractCount": 0,
                    "TotalContractValue": 0.0,
                    "TotalAnnualContractValue": 0.0,
                    "Currency": row.get("Currency"),
                    "BusinessUnits": [],
                },
            )
            bucket["ContractCount"] += 1
            bucket["TotalContractValue"] += float(row.get("ContractValue") or 0)
            bucket["TotalAnnualContractValue"] += float(row.get("AnnualContractValue") or 0)
            bu = row.get("BusinessUnit")
            if bu and bu not in bucket["BusinessUnits"]:
                bucket["BusinessUnits"].append(bu)
        rows = sorted(
            rolled.values(),
            key=lambda item: float(item.get("TotalContractValue") or 0),
            reverse=True,
        )[:max_rows]
        return json.dumps(_rows_payload(rows, criteria=criteria), default=str)

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
    rows = [row for row in (result.get("rows") or []) if isinstance(row, dict)]
    if criteria.get("supplier_name"):
        rows = [
            row
            for row in rows
            if str(criteria["supplier_name"]).lower() in str(row.get("SupplierName") or "").lower()
        ]
    return json.dumps(_rows_payload(rows, criteria=criteria), default=str)


@mcp.tool()
def compare_contracts(
    contract_ref_a: str | None = None,
    contract_ref_b: str | None = None,
    supplier_name_a: str | None = None,
    supplier_name_b: str | None = None,
    contract_name_a: str | None = None,
    contract_name_b: str | None = None,
    contract_type_a: str | None = None,
    contract_type_b: str | None = None,
    annual_cost_a: float | None = None,
    annual_cost_b: float | None = None,
) -> str:
    """
    Compare two vendor contracts field-by-field from the Fabric Gold layer.

    Resolve each side with the shared lookup dimensions: ContractID/Number,
    SupplierName, ContractName, ContractType, and/or AnnualContractValue.

    Args:
        contract_ref_a: Left ContractID or ContractNumber.
        contract_ref_b: Right ContractID or ContractNumber.
        supplier_name_a: Left supplier name (e.g. Microsoft).
        supplier_name_b: Right supplier name (e.g. Oracle).
        contract_name_a: Left contract name fragment.
        contract_name_b: Right contract name fragment.
        contract_type_a: Left contract type.
        contract_type_b: Right contract type.
        annual_cost_a: Left annual contract value.
        annual_cost_b: Right annual contract value.

    Returns:
        JSON string with matching fields and a differences list.
    """
    rows = _load_vendor_contracts(max_rows=500)
    left_criteria = build_criteria(
        contract_ref=contract_ref_a,
        supplier_name=supplier_name_a,
        contract_name=contract_name_a,
        contract_type=contract_type_a,
        annual_cost=annual_cost_a,
    )
    right_criteria = build_criteria(
        contract_ref=contract_ref_b,
        supplier_name=supplier_name_b,
        contract_name=contract_name_b,
        contract_type=contract_type_b,
        annual_cost=annual_cost_b,
    )
    if not left_criteria or not right_criteria:
        return json.dumps(
            {
                "error": "Both sides require at least one lookup criterion",
                "left_criteria": left_criteria,
                "right_criteria": right_criteria,
            },
            default=str,
        )

    left, left_err = _resolve_or_error(rows, left_criteria, side_label="left")
    right, right_err = _resolve_or_error(rows, right_criteria, side_label="right")
    if left_err or right_err:
        return json.dumps(
            {
                "error": "One or both contracts could not be uniquely resolved",
                "left": left_err or {"resolved": left.get("ContractID") if left else None},
                "right": right_err or {"resolved": right.get("ContractID") if right else None},
            },
            default=str,
        )
    assert left is not None and right is not None
    result = compare_contract_rows(
        left,
        right,
        left_id=str(left.get("ContractID") or "left"),
        right_id=str(right.get("ContractID") or "right"),
    )
    result["left_criteria"] = left_criteria
    result["right_criteria"] = right_criteria
    return json.dumps(result, default=str)


@mcp.tool()
def check_missing_contract_fields(
    contract_ref: str | None = None,
    supplier_name: str | None = None,
    contract_name: str | None = None,
    contract_type: str | None = None,
    annual_cost: float | None = None,
    max_rows: int = 200,
) -> str:
    """
    Check vendor contracts for missing or blank required commercial fields.

    Optional shared lookup filters narrow the scan by ContractID/Number,
    SupplierName, ContractName, ContractType, or AnnualContractValue.

    Args:
        contract_ref: Optional ContractID or ContractNumber.
        supplier_name: Optional supplier name filter.
        contract_name: Optional contract name filter.
        contract_type: Optional contract type filter.
        annual_cost: Optional annual contract value filter.
        max_rows: Maximum contracts loaded before filtering (default 200).

    Returns:
        JSON string with incomplete contracts and their missing_fields lists.
    """
    rows = _load_vendor_contracts(max_rows=max_rows)
    criteria = build_criteria(
        contract_ref=contract_ref,
        supplier_name=supplier_name,
        contract_name=contract_name,
        contract_type=contract_type,
        annual_cost=annual_cost,
    )
    result = check_missing_fields_in_rows(
        rows,
        required_fields=list(DEFAULT_REQUIRED_FIELDS),
        criteria=criteria,
    )
    return json.dumps(result, default=str)


@mcp.tool()
def search_cloud_blob_contracts(
    query: str,
    top: int = 20,
    filter_expression: str | None = None,
    supplier_name: str | None = None,
    contract_name: str | None = None,
    contract_type: str | None = None,
    annual_cost: float | None = None,
    contract_ref: str | None = None,
) -> str:
    """
    Hybrid semantic search over cloud-blob contract documents in Azure AI Search.

    Optional shared lookup filters further narrow returned documents by
    supplier/name/type/annual cost/contract ref metadata when present.

    Args:
        query: Natural-language search text.
        top: Number of documents to return (default 20).
        filter_expression: Optional OData filter on index fields.
        supplier_name: Optional supplier name metadata filter.
        contract_name: Optional contract/title metadata filter.
        contract_type: Optional contract type metadata filter.
        annual_cost: Optional annual cost metadata filter.
        contract_ref: Optional contract id metadata filter.

    Returns:
        JSON string with matched documents and semantic metadata.
    """
    result = hybrid_semantic_search(
        query,
        top=max(top * 3, top),
        filter_expression=filter_expression,
    )
    docs = [doc for doc in (result.get("documents") or []) if isinstance(doc, dict)]
    criteria = build_criteria(
        contract_ref=contract_ref,
        supplier_name=supplier_name,
        contract_name=contract_name,
        contract_type=contract_type,
        annual_cost=annual_cost,
    )
    if criteria:
        # Map search docs onto the shared contract filter shape.
        projected = [
            {
                "ContractID": doc.get("contractId") or doc.get("id"),
                "ContractNumber": doc.get("contractNumber"),
                "ContractName": doc.get("title") or doc.get("contractName"),
                "ContractType": doc.get("contractType"),
                "SupplierName": doc.get("supplierName"),
                "AnnualContractValue": doc.get("annualContractValue") or doc.get("annual_cost"),
                "_doc": doc,
            }
            for doc in docs
        ]
        kept = filter_contracts(projected, criteria)
        docs = [item["_doc"] for item in kept]
    docs = docs[:top]
    result["documents"] = docs
    result["count"] = len(docs)
    result["criteria"] = criteria
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
