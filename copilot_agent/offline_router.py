"""
Offline / firewall-bypass cognitive router.

Used when Azure OpenAI is unreachable (VNet/firewall 403) or when
USE_OFFLINE_MOCKS is enabled for local staging. Still routes through the same
MCP tools as the production LangChain agent — it only replaces the LLM hop.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.tools import BaseTool

from mcp_clients import bridge

logger = logging.getLogger(__name__)

_SPEND_RE = re.compile(
    r"\b(spend|vendor|supplier|cost|po\b|purchase\s*order|financial|aggregate|rollup)\b",
    re.I,
)
_EXPIRE_RE = re.compile(
    r"\b(expir\w*|renew\w*|upcoming|deadline|contract\s*dates?|end\s*date)\b",
    re.I,
)
_SEARCH_RE = re.compile(
    r"\b(legal|liabilit\w*|clause|pdf|document|policy|blob|unstructured|search|contract\s*text)\b",
    re.I,
)
_COMPARE_RE = re.compile(
    r"\b(compar\w*|diff(?:erence|s)?|versus|vs\.?)\b",
    re.I,
)
_MISSING_RE = re.compile(
    r"\b(missing|incomplete|blank|null|data\s*quality|completeness|required\s*field)\b",
    re.I,
)
_CONTRACT_ID_RE = re.compile(r"\b(?:CON|CNT)-\d+\b", re.I)
_ANNUAL_COST_RE = re.compile(
    r"\b(?:annual(?:\s*contract)?\s*(?:cost|value)|acv)\s*[:=]?\s*\$?([\d,]+(?:\.\d+)?)\b",
    re.I,
)
_CONTRACT_TYPE_RE = re.compile(
    r"\b(Software License|SaaS Subscription|Consulting Services|Support Agreement|"
    r"Managed Services|Cloud Subscription|Professional Services)\b",
    re.I,
)
_SUPPLIER_RE = re.compile(
    r"\b(Microsoft|Amazon AWS|Amazon|Google Cloud|Google|Oracle|SAP|IBM|Salesforce|"
    r"ServiceNow|Adobe|Cisco|VMware|Snowflake|Databricks|Accenture)\b",
    re.I,
)
_CONTRACT_NAME_RE = re.compile(
    r"(?:contract\s*name|named)\s*[:=]?\s*[\"']?([A-Za-z0-9][A-Za-z0-9 ._/&-]{3,})[\"']?",
    re.I,
)
_COMPARE_SPLIT_RE = re.compile(r"\b(?:vs\.?|versus|and|with|against)\b", re.I)


def _tool_map(tools: list[BaseTool]) -> dict[str, BaseTool]:
    return {tool.name: tool for tool in tools}


async def _ainvoke_tool(tool: BaseTool, **kwargs: Any) -> str:
    # Drop None values so MCP schemas don't receive explicit nulls unexpectedly.
    clean = {key: value for key, value in kwargs.items() if value is not None}
    result = await tool.ainvoke(clean)
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        texts: list[str] = []
        for item in result:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(str(item.get("text", "")))
            else:
                texts.append(json.dumps(item, default=str))
        return "\n".join(texts).strip()
    if isinstance(result, dict) and "text" in result:
        return str(result["text"])
    return json.dumps(result, default=str)


def _summarize_sql_payload(raw: str, *, title: str, limit: int = 5) -> str:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return f"{title}\n{raw[:2000]}"

    if isinstance(payload, list):
        rows = payload
        count = len(rows)
        criteria: dict[str, Any] = {}
    elif isinstance(payload, dict):
        rows = payload.get("rows") or []
        count = payload.get("row_count", len(rows))
        criteria = payload.get("criteria") or {}
    else:
        return f"{title}\n{raw[:2000]}"

    lines = [f"{title} ({count} rows)"]
    if criteria:
        lines.append(f"Filters: {criteria}")
    for row in rows[:limit]:
        if not isinstance(row, dict):
            lines.append(f"- {row}")
            continue
        preferred = [
            row.get("SupplierName") or row.get("ContractName") or row.get("ContractID"),
            row.get("ContractType"),
            row.get("TotalContractValue") or row.get("ContractValue"),
            row.get("AnnualContractValue") or row.get("TotalAnnualContractValue"),
            row.get("ExpirationDate") or row.get("Currency"),
        ]
        bits = [str(v) for v in preferred if v not in (None, "")]
        lines.append("- " + " | ".join(bits) if bits else f"- {row}")
    if count > limit:
        lines.append(f"... {count - limit} more rows omitted")
    lines.append("Source: Fabric SQL Gold (MCP)")
    return "\n".join(lines)


def _summarize_search_payload(raw: str, *, query: str, limit: int = 20) -> str:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return f"Search results for '{query}':\n{raw[:2000]}"

    docs = payload.get("documents") or []
    lines = [f"Document search for '{query}' ({len(docs)} hits)"]
    if payload.get("criteria"):
        lines.append(f"Filters: {payload.get('criteria')}")
    for doc in docs[:limit]:
        if not isinstance(doc, dict):
            lines.append(f"- {doc}")
            continue
        title = doc.get("title") or doc.get("contractId") or doc.get("id") or "document"
        snippet = doc.get("content") or doc.get("chunk") or ""
        snippet = str(snippet).replace("\n", " ")[:220]
        lines.append(f"- {title}: {snippet}")
    lines.append("Source: Azure AI Search (MCP)")
    return "\n".join(lines)


def _summarize_compare_payload(raw: str, limit: int = 20) -> str:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return f"Contract comparison:\n{raw[:2000]}"

    if payload.get("error"):
        return (
            f"Contract comparison failed: {payload.get('error')}\n"
            f"{json.dumps({k: payload.get(k) for k in ('left', 'right', 'left_criteria', 'right_criteria') if k in payload}, default=str)[:1200]}"
        )

    diffs = payload.get("differences") or []
    left_id = payload.get("left_contract_id")
    right_id = payload.get("right_contract_id")
    lines = [
        f"Contract comparison: {left_id} vs {right_id}",
        f"Names: {payload.get('left_contract_name')} vs {payload.get('right_contract_name')}",
        f"Suppliers: {payload.get('left_supplier_name')} vs {payload.get('right_supplier_name')}",
        f"Types: {payload.get('left_contract_type')} vs {payload.get('right_contract_type')}",
        f"Annual cost: {payload.get('left_annual_cost')} vs {payload.get('right_annual_cost')}",
        f"Fields compared: {payload.get('fields_compared')}; "
        f"matching: {payload.get('matching_field_count')}; "
        f"differences: {payload.get('difference_count')}",
    ]
    for item in diffs[:limit]:
        field = item.get("field")
        lines.append(
            f"- {field}: {item.get(str(left_id))} → {item.get(str(right_id))}"
        )
    if len(diffs) > limit:
        lines.append(f"... {len(diffs) - limit} more differences omitted")
    lines.append("Source: Fabric SQL Gold (MCP compare_contracts)")
    return "\n".join(lines)


def _summarize_missing_payload(raw: str, limit: int = 20) -> str:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return f"Missing-field check:\n{raw[:2000]}"

    if payload.get("not_found"):
        return (
            f"No contracts matched filters `{payload.get('criteria')}`."
        )

    incomplete = payload.get("incomplete_contracts") or []
    lines = [
        "Missing contract information check",
        f"Filters: {payload.get('criteria') or {}}",
        f"Evaluated: {payload.get('contracts_evaluated')}; "
        f"complete: {payload.get('complete_count')}; "
        f"incomplete: {payload.get('incomplete_count')}",
        "Required fields: " + ", ".join(payload.get("required_fields") or []),
    ]
    for row in incomplete[:limit]:
        lines.append(
            f"- {row.get('ContractID')} / {row.get('SupplierName')} / "
            f"{row.get('ContractName')}: missing {', '.join(row.get('missing_fields') or [])}"
        )
    if len(incomplete) > limit:
        lines.append(f"... {len(incomplete) - limit} more incomplete contracts omitted")
    if not incomplete:
        lines.append("All evaluated contracts have the required fields populated.")
    lines.append("Source: Fabric SQL Gold (MCP check_missing_contract_fields)")
    return "\n".join(lines)


def _extract_contract_ids(text: str) -> list[str]:
    return list(dict.fromkeys(_CONTRACT_ID_RE.findall(text)))


def _extract_suppliers(text: str) -> list[str]:
    return list(dict.fromkeys(m.group(0) for m in _SUPPLIER_RE.finditer(text)))


def _extract_contract_types(text: str) -> list[str]:
    return list(dict.fromkeys(m.group(1) for m in _CONTRACT_TYPE_RE.finditer(text)))


def _extract_annual_costs(text: str) -> list[float]:
    values: list[float] = []
    for match in _ANNUAL_COST_RE.finditer(text):
        try:
            values.append(float(match.group(1).replace(",", "")))
        except ValueError:
            continue
    return list(dict.fromkeys(values))


def _extract_contract_names(text: str) -> list[str]:
    names: list[str] = []
    for match in _CONTRACT_NAME_RE.finditer(text):
        name = match.group(1).strip().rstrip(".,;:")
        if name:
            names.append(name)
    # Also catch quoted names.
    for match in re.finditer(r"[\"']([^\"']{4,})[\"']", text):
        names.append(match.group(1).strip())
    return list(dict.fromkeys(names))


def _criteria_from_parts(
    *,
    contract_ref: str | None = None,
    supplier_name: str | None = None,
    contract_name: str | None = None,
    contract_type: str | None = None,
    annual_cost: float | None = None,
) -> dict[str, Any]:
    criteria: dict[str, Any] = {}
    if contract_ref:
        criteria["contract_ref"] = contract_ref
    if supplier_name:
        criteria["supplier_name"] = supplier_name
    if contract_name:
        criteria["contract_name"] = contract_name
    if contract_type:
        criteria["contract_type"] = contract_type
    if annual_cost is not None:
        criteria["annual_cost"] = annual_cost
    return criteria


def _split_compare_sides(text: str) -> tuple[str, str] | None:
    parts = [part.strip() for part in _COMPARE_SPLIT_RE.split(text) if part.strip()]
    # Prefer splits that look like "... compare X vs Y"
    if len(parts) >= 2:
        return parts[-2], parts[-1]
    return None


def _choose_tools(user_text: str) -> list[str]:
    text = user_text.strip()
    chosen: list[str] = []
    if _COMPARE_RE.search(text):
        chosen.append("compare_contracts")
    if _MISSING_RE.search(text):
        chosen.append("check_missing_contract_fields")
    if _EXPIRE_RE.search(text):
        chosen.append("get_expiring_contracts")
    if _SPEND_RE.search(text):
        chosen.append("get_vendor_spend_summary")
    if _SEARCH_RE.search(text) or (
        "contract" in text.lower()
        and "compare_contracts" not in chosen
        and "check_missing_contract_fields" not in chosen
        and "get_expiring_contracts" not in chosen
    ):
        chosen.append("search_cloud_blob_contracts")
    if not chosen:
        chosen = ["get_vendor_spend_summary", "search_cloud_blob_contracts"]
    return list(dict.fromkeys(chosen))


async def run_offline_turn(user_text: str) -> str:
    """Intent-route to MCP tools without calling Azure OpenAI."""
    tools = _tool_map(await bridge.get_tools())
    selected = _choose_tools(user_text)
    contract_ids = _extract_contract_ids(user_text)
    suppliers = _extract_suppliers(user_text)
    contract_types = _extract_contract_types(user_text)
    annual_costs = _extract_annual_costs(user_text)
    contract_names = _extract_contract_names(user_text)
    shared_filters = _criteria_from_parts(
        contract_ref=contract_ids[0] if len(contract_ids) == 1 else None,
        supplier_name=suppliers[0] if len(suppliers) == 1 else None,
        contract_name=contract_names[0] if len(contract_names) == 1 else None,
        contract_type=contract_types[0] if len(contract_types) == 1 else None,
        annual_cost=annual_costs[0] if len(annual_costs) == 1 else None,
    )
    sections: list[str] = []

    for name in selected:
        tool = tools.get(name)
        if tool is None:
            sections.append(f"Tool `{name}` is unavailable in the current MCP session.")
            continue
        try:
            if name == "get_expiring_contracts":
                raw = await _ainvoke_tool(
                    tool,
                    days_ahead=365,
                    max_rows=25,
                    **shared_filters,
                )
                sections.append(_summarize_sql_payload(raw, title="Expiring contracts"))
            elif name == "get_vendor_spend_summary":
                spend_filters = {
                    key: shared_filters[key]
                    for key in ("supplier_name", "contract_type", "annual_cost")
                    if key in shared_filters
                }
                raw = await _ainvoke_tool(tool, max_rows=25, **spend_filters)
                sections.append(_summarize_sql_payload(raw, title="Vendor spend summary"))
            elif name == "compare_contracts":
                left: dict[str, Any]
                right: dict[str, Any]
                if len(contract_ids) >= 2:
                    left = {"contract_ref_a": contract_ids[0]}
                    right = {"contract_ref_b": contract_ids[1]}
                elif len(suppliers) >= 2:
                    left = {"supplier_name_a": suppliers[0]}
                    right = {"supplier_name_b": suppliers[1]}
                elif len(contract_names) >= 2:
                    left = {"contract_name_a": contract_names[0]}
                    right = {"contract_name_b": contract_names[1]}
                elif len(contract_types) >= 2:
                    left = {"contract_type_a": contract_types[0]}
                    right = {"contract_type_b": contract_types[1]}
                elif len(annual_costs) >= 2:
                    left = {"annual_cost_a": annual_costs[0]}
                    right = {"annual_cost_b": annual_costs[1]}
                else:
                    sides = _split_compare_sides(user_text)
                    if sides:
                        left_suppliers = _extract_suppliers(sides[0])
                        right_suppliers = _extract_suppliers(sides[1])
                        left_ids = _extract_contract_ids(sides[0])
                        right_ids = _extract_contract_ids(sides[1])
                        left_names = _extract_contract_names(sides[0])
                        right_names = _extract_contract_names(sides[1])
                        left_types = _extract_contract_types(sides[0])
                        right_types = _extract_contract_types(sides[1])
                        left_costs = _extract_annual_costs(sides[0])
                        right_costs = _extract_annual_costs(sides[1])
                        left = {}
                        right = {}
                        if left_ids:
                            left["contract_ref_a"] = left_ids[0]
                        if right_ids:
                            right["contract_ref_b"] = right_ids[0]
                        if left_suppliers:
                            left["supplier_name_a"] = left_suppliers[0]
                        if right_suppliers:
                            right["supplier_name_b"] = right_suppliers[0]
                        if left_names:
                            left["contract_name_a"] = left_names[0]
                        if right_names:
                            right["contract_name_b"] = right_names[0]
                        if left_types:
                            left["contract_type_a"] = left_types[0]
                        if right_types:
                            right["contract_type_b"] = right_types[0]
                        if left_costs:
                            left["annual_cost_a"] = left_costs[0]
                        if right_costs:
                            right["annual_cost_b"] = right_costs[0]
                    else:
                        left, right = {}, {}

                if not left or not right:
                    left = {"contract_ref_a": "CON-0001"}
                    right = {"contract_ref_b": "CON-0002"}
                    sections.append(
                        "No two resolvable compare sides detected; "
                        "defaulting comparison to CON-0001 vs CON-0002."
                    )
                raw = await _ainvoke_tool(tool, **left, **right)
                sections.append(_summarize_compare_payload(raw))
            elif name == "check_missing_contract_fields":
                raw = await _ainvoke_tool(tool, max_rows=100, **shared_filters)
                sections.append(_summarize_missing_payload(raw))
            elif name == "search_cloud_blob_contracts":
                raw = await _ainvoke_tool(
                    tool,
                    query=user_text,
                    top=20,
                    **shared_filters,
                )
                sections.append(_summarize_search_payload(raw, query=user_text, limit=20))
            else:
                raw = await _ainvoke_tool(tool)
                sections.append(f"`{name}` result:\n{raw[:2000]}")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Offline router tool %s failed", name)
            sections.append(f"Tool `{name}` failed: {exc}")

    header = (
        "Offline cognitive router (Azure OpenAI bypassed due to "
        "USE_OFFLINE_MOCKS or network/firewall restrictions)."
    )
    return header + "\n\n" + "\n\n".join(sections)
