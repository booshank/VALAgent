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


def _md_cell(value: Any) -> str:
    text = "—" if value is None or value == "" else str(value)
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _as_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").replace("$", ""))
    except ValueError:
        return None


def _lifecycle_days(effective: Any, expiration: Any) -> float | None:
    from datetime import datetime

    try:
        start = datetime.fromisoformat(str(effective)[:10])
        end = datetime.fromisoformat(str(expiration)[:10])
        return float((end - start).days)
    except Exception:  # noqa: BLE001
        return None


def _diff_value(diffs: list[dict[str, Any]], field: str, left_id: str, right_id: str) -> tuple[Any, Any]:
    for item in diffs:
        if item.get("field") == field:
            return item.get(str(left_id)), item.get(str(right_id))
    return None, None


def _build_compare_recommendation(
    payload: dict[str, Any],
    *,
    risk_notes: list[str] | None = None,
) -> str:
    """Strategic advisor recommendation from quantitative + risk evidence."""
    left_id = str(payload.get("left_contract_id") or "Left")
    right_id = str(payload.get("right_contract_id") or "Right")
    left_name = payload.get("left_contract_name") or left_id
    right_name = payload.get("right_contract_name") or right_id
    left_supplier = payload.get("left_supplier_name") or "Left supplier"
    right_supplier = payload.get("right_supplier_name") or "Right supplier"
    diffs = payload.get("differences") or []

    left_annual = _as_number(payload.get("left_annual_cost"))
    right_annual = _as_number(payload.get("right_annual_cost"))
    left_value, right_value = _diff_value(diffs, "ContractValue", left_id, right_id)
    left_value_n = _as_number(left_value)
    right_value_n = _as_number(right_value)
    left_eff, right_eff = _diff_value(diffs, "EffectiveDate", left_id, right_id)
    left_exp, right_exp = _diff_value(diffs, "ExpirationDate", left_id, right_id)
    # Fall back to matching equal dates when field not in differences.
    if left_eff is None:
        left_eff = right_eff = None
    left_life = _lifecycle_days(left_eff, left_exp) if left_eff and left_exp else None
    right_life = _lifecycle_days(right_eff, right_exp) if right_eff and right_exp else None
    left_status, right_status = _diff_value(diffs, "ContractStatus", left_id, right_id)
    left_auto, right_auto = _diff_value(diffs, "AutoRenewalFlag", left_id, right_id)

    left_score = 0
    right_score = 0
    justifications: list[str] = []

    # QUANTITATIVE COMPARISON
    if left_annual is not None and right_annual is not None and left_annual != right_annual:
        if left_annual < right_annual:
            left_score += 2
            justifications.append(
                f"Lower annual cost on {left_id} ({left_annual} vs {right_annual}) — Fabric SQL."
            )
        else:
            right_score += 2
            justifications.append(
                f"Lower annual cost on {right_id} ({right_annual} vs {left_annual}) — Fabric SQL."
            )
    if left_value_n is not None and right_value_n is not None and left_value_n != right_value_n:
        if left_value_n < right_value_n:
            left_score += 1
            justifications.append(
                f"Lower total contract value on {left_id} ({left_value_n} vs {right_value_n}) — Fabric SQL."
            )
        else:
            right_score += 1
            justifications.append(
                f"Lower total contract value on {right_id} ({right_value_n} vs {left_value_n}) — Fabric SQL."
            )
    if left_life is not None and right_life is not None and left_life != right_life:
        # Prefer longer committed lifecycle when both are active commercial terms.
        if left_life > right_life:
            left_score += 1
            justifications.append(
                f"Longer lifecycle on {left_id} ({int(left_life)} vs {int(right_life)} days) — Fabric SQL."
            )
        else:
            right_score += 1
            justifications.append(
                f"Longer lifecycle on {right_id} ({int(right_life)} vs {int(left_life)} days) — Fabric SQL."
            )

    for label, status, auto, bump_left in (
        (left_id, left_status, left_auto, True),
        (right_id, right_status, right_auto, False),
    ):
        status_l = str(status or "").lower()
        if status_l == "active":
            if bump_left:
                left_score += 1
            else:
                right_score += 1
            justifications.append(f"{label} is Active — lower operational discontinuity risk (Fabric SQL).")
        elif status_l in {"expired", "terminated"}:
            if bump_left:
                left_score -= 1
            else:
                right_score -= 1
            justifications.append(f"{label} status is {status} — elevated continuity risk (Fabric SQL).")
        if auto is True:
            justifications.append(
                f"{label} has AutoRenewal enabled — review exit timing / notice risk (Fabric SQL)."
            )

    # RISK & LIABILITY ASSESSMENT notes from Azure AI Search (when provided)
    risk_notes = risk_notes or []
    for note in risk_notes:
        justifications.append(note)
        note_l = note.lower()
        # Lightweight directional scoring from clause language.
        favors_left = left_id.lower() in note_l or str(left_supplier).lower() in note_l
        favors_right = right_id.lower() in note_l or str(right_supplier).lower() in note_l
        positive = any(
            token in note_l
            for token in ("indemnif", "favorable", "lower liability", "termination for convenience")
        )
        negative = any(
            token in note_l
            for token in ("unlimited liability", "broad liability", "lock-in", "auto-renew penalty")
        )
        if favors_left and positive:
            left_score += 1
        if favors_right and positive:
            right_score += 1
        if favors_left and negative:
            left_score -= 1
        if favors_right and negative:
            right_score -= 1

    if left_score > right_score:
        winner_id, winner_name, winner_supplier = left_id, left_name, left_supplier
    elif right_score > left_score:
        winner_id, winner_name, winner_supplier = right_id, right_name, right_supplier
    else:
        winner_id, winner_name, winner_supplier = left_id, left_name, left_supplier
        justifications.append(
            "Scores were close; defaulting to the left contract pending stronger clause evidence "
            "from Azure AI Search."
        )

    if not justifications:
        justifications.append(
            "Insufficient differentiating quantitative/risk signal; recommendation is provisional."
        )

    lines = [
        "",
        "## Recommendation",
        "",
        f"**Select {winner_id} ({winner_name} / {winner_supplier}) as structurally superior / lower risk.**",
        "",
        "Business justifications:",
    ]
    for item in justifications[:8]:
        lines.append(f"- {item}")
    return "\n".join(lines)


def _summarize_compare_payload(
    raw: str,
    limit: int = 50,
    *,
    risk_notes: list[str] | None = None,
) -> str:
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
    matching = payload.get("matching_fields") or []
    left_id = payload.get("left_contract_id")
    right_id = payload.get("right_contract_id")
    left_label = _md_cell(left_id)
    right_label = _md_cell(right_id)

    lines = [
        f"### Contract comparison: {left_label} vs {right_label}",
        "",
        "#### Quantitative snapshot (Fabric SQL)",
        "",
        "| Attribute | Left | Right |",
        "| --- | --- | --- |",
        f"| Contract ID | {left_label} | {right_label} |",
        f"| Contract Number | {_md_cell(payload.get('left_contract_number'))} | {_md_cell(payload.get('right_contract_number'))} |",
        f"| Contract Name | {_md_cell(payload.get('left_contract_name'))} | {_md_cell(payload.get('right_contract_name'))} |",
        f"| Supplier | {_md_cell(payload.get('left_supplier_name'))} | {_md_cell(payload.get('right_supplier_name'))} |",
        f"| Contract Type | {_md_cell(payload.get('left_contract_type'))} | {_md_cell(payload.get('right_contract_type'))} |",
        f"| Annual Cost | {_md_cell(payload.get('left_annual_cost'))} | {_md_cell(payload.get('right_annual_cost'))} |",
        f"| Fields compared | {payload.get('fields_compared')} | |",
        f"| Matching fields | {payload.get('matching_field_count')} | |",
        f"| Differences | {payload.get('difference_count')} | |",
        "",
        "#### Field differences",
        "",
        f"| Field | {left_label} | {right_label} |",
        "| --- | --- | --- |",
    ]
    for item in diffs[:limit]:
        field = _md_cell(item.get("field"))
        left_val = _md_cell(item.get(str(left_id)))
        right_val = _md_cell(item.get(str(right_id)))
        lines.append(f"| {field} | {left_val} | {right_val} |")
    if not diffs:
        lines.append("| — | No differences | No differences |")
    if len(diffs) > limit:
        lines.append(f"| … | {len(diffs) - limit} more differences omitted | |")

    if matching:
        lines.extend(
            [
                "",
                "#### Matching fields",
                "",
                "| Field | Status |",
                "| --- | --- |",
            ]
        )
        for field in matching[:limit]:
            lines.append(f"| {_md_cell(field)} | Match |")
        if len(matching) > limit:
            lines.append(f"| … | {len(matching) - limit} more matching fields omitted |")

    if risk_notes:
        lines.extend(["", "#### Risk & liability signals (Azure AI Search)", ""])
        for note in risk_notes[:6]:
            lines.append(f"- {note}")

    lines.extend(["", "Source: Fabric SQL Gold (MCP `compare_contracts`)"])
    lines.append(_build_compare_recommendation(payload, risk_notes=risk_notes))
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
    # Compare prompts often mix labeled + bare amounts:
    # "compare annual cost 41666.67 vs 50000"
    if re.search(r"\b(annual|cost|acv|value)\b", text, re.I):
        for match in re.finditer(r"\b(\d{4,}(?:\.\d+)?)\b", text):
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

                # Enrich compare with spend + clause search (orchestrator layer only).
                risk_notes: list[str] = []
                try:
                    compare_payload = json.loads(raw)
                except json.JSONDecodeError:
                    compare_payload = {}
                left_supplier = compare_payload.get("left_supplier_name")
                right_supplier = compare_payload.get("right_supplier_name")
                spend_tool = tools.get("get_vendor_spend_summary")
                search_tool = tools.get("search_cloud_blob_contracts")
                if spend_tool and left_supplier:
                    spend_raw = await _ainvoke_tool(
                        spend_tool, max_rows=5, supplier_name=str(left_supplier)
                    )
                    risk_notes.append(
                        f"Historical spend context for {left_supplier} retrieved via "
                        f"get_vendor_spend_summary (Fabric SQL)."
                    )
                    del spend_raw
                if spend_tool and right_supplier:
                    spend_raw = await _ainvoke_tool(
                        spend_tool, max_rows=5, supplier_name=str(right_supplier)
                    )
                    risk_notes.append(
                        f"Historical spend context for {right_supplier} retrieved via "
                        f"get_vendor_spend_summary (Fabric SQL)."
                    )
                    del spend_raw
                if search_tool:
                    for label, supplier in (
                        (compare_payload.get("left_contract_id"), left_supplier),
                        (compare_payload.get("right_contract_id"), right_supplier),
                    ):
                        if not supplier:
                            continue
                        query = (
                            f"{supplier} liability indemnification termination notice "
                            f"cap limitation of liability"
                        )
                        search_raw = await _ainvoke_tool(
                            search_tool,
                            query=query,
                            top=3,
                            supplier_name=str(supplier),
                        )
                        try:
                            search_payload = json.loads(search_raw)
                            docs = search_payload.get("documents") or []
                            if docs:
                                snippet = str(
                                    docs[0].get("content") or docs[0].get("title") or ""
                                ).replace("\n", " ")[:180]
                                risk_notes.append(
                                    f"{label}/{supplier} clause scan: {snippet} "
                                    "(Azure AI Search)."
                                )
                            else:
                                risk_notes.append(
                                    f"{label}/{supplier}: no liability/termination clauses "
                                    "returned by Azure AI Search; legal risk remains unverified."
                                )
                        except json.JSONDecodeError:
                            risk_notes.append(
                                f"{label}/{supplier}: clause search returned non-JSON payload."
                            )

                sections.append(
                    _summarize_compare_payload(raw, risk_notes=risk_notes)
                )
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
