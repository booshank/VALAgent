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


def _tool_map(tools: list[BaseTool]) -> dict[str, BaseTool]:
    return {tool.name: tool for tool in tools}


async def _ainvoke_tool(tool: BaseTool, **kwargs: Any) -> str:
    result = await tool.ainvoke(kwargs)
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
    elif isinstance(payload, dict):
        rows = payload.get("rows") or []
        count = payload.get("row_count", len(rows))
    else:
        return f"{title}\n{raw[:2000]}"

    lines = [f"{title} ({count} rows)"]
    for row in rows[:limit]:
        if not isinstance(row, dict):
            lines.append(f"- {row}")
            continue
        preferred = [
            row.get("SupplierName") or row.get("ContractName") or row.get("ContractID"),
            row.get("TotalContractValue") or row.get("ContractValue"),
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
            f"Contract comparison failed: {payload.get('error')} "
            f"(A found={payload.get('found_a')}, B found={payload.get('found_b')})"
        )

    diffs = payload.get("differences") or []
    left_id = payload.get("left_contract_id")
    right_id = payload.get("right_contract_id")
    lines = [
        f"Contract comparison: {left_id} vs {right_id}",
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
        return f"No contract found for ref `{payload.get('contract_ref')}`."

    incomplete = payload.get("incomplete_contracts") or []
    lines = [
        "Missing contract information check",
        f"Evaluated: {payload.get('contracts_evaluated')}; "
        f"complete: {payload.get('complete_count')}; "
        f"incomplete: {payload.get('incomplete_count')}",
        "Required fields: " + ", ".join(payload.get("required_fields") or []),
    ]
    for row in incomplete[:limit]:
        lines.append(
            f"- {row.get('ContractID')} ({row.get('ContractName')}): "
            f"missing {', '.join(row.get('missing_fields') or [])}"
        )
    if len(incomplete) > limit:
        lines.append(f"... {len(incomplete) - limit} more incomplete contracts omitted")
    if not incomplete:
        lines.append("All evaluated contracts have the required fields populated.")
    lines.append("Source: Fabric SQL Gold (MCP check_missing_contract_fields)")
    return "\n".join(lines)


def _extract_contract_ids(text: str) -> list[str]:
    return list(dict.fromkeys(_CONTRACT_ID_RE.findall(text)))


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
    # Avoid generic document search when the user clearly asked for compare/missing analytics.
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
    sections: list[str] = []

    for name in selected:
        tool = tools.get(name)
        if tool is None:
            sections.append(f"Tool `{name}` is unavailable in the current MCP session.")
            continue
        try:
            if name == "get_expiring_contracts":
                raw = await _ainvoke_tool(tool, days_ahead=365, max_rows=25)
                sections.append(_summarize_sql_payload(raw, title="Expiring contracts"))
            elif name == "get_vendor_spend_summary":
                raw = await _ainvoke_tool(tool, max_rows=25)
                sections.append(_summarize_sql_payload(raw, title="Vendor spend summary"))
            elif name == "compare_contracts":
                if len(contract_ids) >= 2:
                    a, b = contract_ids[0], contract_ids[1]
                else:
                    # Deterministic staging default when IDs are omitted.
                    a, b = "CON-0001", "CON-0002"
                    sections.append(
                        "No two contract IDs detected in the prompt; "
                        f"defaulting comparison to {a} vs {b}."
                    )
                raw = await _ainvoke_tool(tool, contract_id_a=a, contract_id_b=b)
                sections.append(_summarize_compare_payload(raw))
            elif name == "check_missing_contract_fields":
                kwargs: dict[str, Any] = {"max_rows": 100}
                if contract_ids:
                    kwargs["contract_id"] = contract_ids[0]
                raw = await _ainvoke_tool(tool, **kwargs)
                sections.append(_summarize_missing_payload(raw))
            elif name == "search_cloud_blob_contracts":
                raw = await _ainvoke_tool(tool, query=user_text, top=20)
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
