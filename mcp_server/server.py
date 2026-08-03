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
    compare_many_contract_rows,
    filter_contracts,
    normalize_contract_profile,
    normalize_contract_search_row,
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
            PaymentTermsDays,
            RateCardOnFile,
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


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _build_side_criteria_list(
    *,
    contract_refs: str | None = None,
    supplier_names: str | None = None,
    contract_names: str | None = None,
    contract_types: str | None = None,
    annual_costs: str | None = None,
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
) -> list[dict[str, Any]]:
    """
    Build 2..N lookup criteria.

    Prefer explicit multi CSV lists when provided; otherwise fall back to legacy
    pairwise *_a / *_b arguments.
    """
    refs = _split_csv(contract_refs)
    suppliers = _split_csv(supplier_names)
    names = _split_csv(contract_names)
    types = _split_csv(contract_types)
    costs_raw = _split_csv(annual_costs)
    costs: list[float] = []
    for item in costs_raw:
        try:
            costs.append(float(item.replace(",", "").replace("$", "")))
        except ValueError:
            continue

    multi_len = max(len(refs), len(suppliers), len(names), len(types), len(costs), 0)
    sides: list[dict[str, Any]] = []
    if multi_len >= 2:
        for idx in range(multi_len):
            side = build_criteria(
                contract_ref=refs[idx] if idx < len(refs) else None,
                supplier_name=suppliers[idx] if idx < len(suppliers) else None,
                contract_name=names[idx] if idx < len(names) else None,
                contract_type=types[idx] if idx < len(types) else None,
                annual_cost=costs[idx] if idx < len(costs) else None,
            )
            if side:
                sides.append(side)
        return sides

    left = build_criteria(
        contract_ref=contract_ref_a,
        supplier_name=supplier_name_a,
        contract_name=contract_name_a,
        contract_type=contract_type_a,
        annual_cost=annual_cost_a,
    )
    right = build_criteria(
        contract_ref=contract_ref_b,
        supplier_name=supplier_name_b,
        contract_name=contract_name_b,
        contract_type=contract_type_b,
        annual_cost=annual_cost_b,
    )
    return [side for side in (left, right) if side]


@mcp.tool()
def compare_contracts(
    contract_refs: str | None = None,
    supplier_names: str | None = None,
    contract_names: str | None = None,
    contract_types: str | None = None,
    annual_costs: str | None = None,
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
    Compare two or more vendor contracts field-by-field from the Fabric Gold layer.

    Prefer multi-contract CSV inputs (`contract_refs`, `supplier_names`, etc.) for
    N-way comparison. Legacy pairwise `*_a` / `*_b` arguments remain supported.

    Shared lookup dimensions: ContractID/Number, SupplierName, ContractName,
    ContractType, and/or AnnualContractValue.

    Args:
        contract_refs: Comma-separated ContractIDs/Numbers (2+), e.g. CON-0001,CON-0002,CON-0003.
        supplier_names: Comma-separated supplier names for N-way compare.
        contract_names: Comma-separated contract names for N-way compare.
        contract_types: Comma-separated contract types for N-way compare.
        annual_costs: Comma-separated annual costs for N-way compare.
        contract_ref_a: Legacy left ContractID or ContractNumber.
        contract_ref_b: Legacy right ContractID or ContractNumber.
        supplier_name_a: Legacy left supplier name.
        supplier_name_b: Legacy right supplier name.
        contract_name_a: Legacy left contract name fragment.
        contract_name_b: Legacy right contract name fragment.
        contract_type_a: Legacy left contract type.
        contract_type_b: Legacy right contract type.
        annual_cost_a: Legacy left annual contract value.
        annual_cost_b: Legacy right annual contract value.

    Returns:
        JSON string with N-way field matrix (and pairwise compatibility fields when N=2).
    """
    rows = _load_vendor_contracts(max_rows=500)
    side_criteria = _build_side_criteria_list(
        contract_refs=contract_refs,
        supplier_names=supplier_names,
        contract_names=contract_names,
        contract_types=contract_types,
        annual_costs=annual_costs,
        contract_ref_a=contract_ref_a,
        contract_ref_b=contract_ref_b,
        supplier_name_a=supplier_name_a,
        supplier_name_b=supplier_name_b,
        contract_name_a=contract_name_a,
        contract_name_b=contract_name_b,
        contract_type_a=contract_type_a,
        contract_type_b=contract_type_b,
        annual_cost_a=annual_cost_a,
        annual_cost_b=annual_cost_b,
    )
    if len(side_criteria) < 2:
        return json.dumps(
            {
                "error": "Provide at least two contract lookup sides for comparison",
                "side_criteria": side_criteria,
            },
            default=str,
        )

    resolved_rows: list[dict[str, Any]] = []
    resolved_meta: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for idx, criteria in enumerate(side_criteria):
        contract, err = _resolve_or_error(rows, criteria, side_label=f"side_{idx+1}")
        if err or contract is None:
            errors.append(err or {"error": f"side_{idx+1} unresolved", "criteria": criteria})
            continue
        resolved_rows.append(contract)
        resolved_meta.append({"side": f"side_{idx+1}", "criteria": criteria, "ContractID": contract.get("ContractID")})

    if len(resolved_rows) < 2:
        return json.dumps(
            {
                "error": "Could not resolve at least two contracts for comparison",
                "resolved": resolved_meta,
                "errors": errors,
            },
            default=str,
        )

    if len(resolved_rows) == 2:
        result = compare_contract_rows(
            resolved_rows[0],
            resolved_rows[1],
            left_id=str(resolved_rows[0].get("ContractID") or "left"),
            right_id=str(resolved_rows[1].get("ContractID") or "right"),
        )
    else:
        result = compare_many_contract_rows(resolved_rows)

    result["side_criteria"] = side_criteria
    result["resolved"] = resolved_meta
    if errors:
        result["resolution_warnings"] = errors
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
def search_contracts(
    vendor: str | None = None,
    business_unit: str | None = None,
    status: str | None = None,
    contract_type: str | None = None,
    max_rows: int = 50,
) -> str:
    """
    Structured search over contract metadata (Gold contracts), not document search.

    Filters optional vendor/business unit/status/type and returns a stable
    snake_case field set for demo-ready contract lists.

    Args:
        vendor: Optional supplier / vendor name filter.
        business_unit: Optional business unit filter.
        status: Optional contract status filter (e.g. Active).
        contract_type: Optional contract type filter.
        max_rows: Maximum rows to return (default 50).

    Returns:
        JSON string with criteria, row_count, and normalized contract rows.
    """
    rows = _load_vendor_contracts(max_rows=500)
    criteria = build_criteria(supplier_name=vendor, contract_type=contract_type)
    filtered = filter_contracts(rows, criteria)
    if business_unit and str(business_unit).strip():
        needle = str(business_unit).strip().lower()
        filtered = [
            row
            for row in filtered
            if needle in str(row.get("BusinessUnit") or "").lower()
        ]
    if status and str(status).strip():
        needle = str(status).strip().lower()
        filtered = [
            row
            for row in filtered
            if needle in str(row.get("ContractStatus") or "").lower()
        ]
    projected = [normalize_contract_search_row(row) for row in filtered[: max(1, int(max_rows))]]
    return json.dumps(
        {
            "tool": "search_contracts",
            "criteria": {
                "vendor": vendor,
                "business_unit": business_unit,
                "status": status,
                "contract_type": contract_type,
            },
            "row_count": len(projected),
            "rows": projected,
            "source": "synthetic_gold_contracts",
        },
        default=str,
    )


@mcp.tool()
def get_contract_profile(contract_id: str) -> str:
    """
    Return a full normalized profile for one contract by ContractID.

    Args:
        contract_id: Contract identifier (e.g. C-1001 or CON-0001).

    Returns:
        JSON string with one normalized profile including missing_fields.
    """
    if not contract_id or not str(contract_id).strip():
        return json.dumps(
            {"error": "contract_id is required", "tool": "get_contract_profile"},
            default=str,
        )
    rows = _load_vendor_contracts(max_rows=500)
    resolved = resolve_contract(
        rows, build_criteria(contract_ref=str(contract_id).strip())
    )
    contract = resolved.get("contract")
    if contract is None:
        return json.dumps(
            {
                "error": "Contract not found",
                "tool": "get_contract_profile",
                "contract_id": contract_id,
                "match_count": resolved.get("match_count", 0),
                "candidates": resolved.get("candidates", []),
            },
            default=str,
        )
    profile = normalize_contract_profile(contract)
    return json.dumps(
        {
            "tool": "get_contract_profile",
            "contract_id": profile.get("contract_id"),
            "profile": profile,
            "source": "synthetic_gold_contracts",
        },
        default=str,
    )


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
