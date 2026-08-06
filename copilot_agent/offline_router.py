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

logger = logging.getLogger(__name__)

INVOICE_OOS_MESSAGE = (
    "Invoice/spend data is not part of this synthetic contract intelligence POC. "
    "This requires a separate data-linkage POC."
)

# Legacy offline-router hallucination / stale-runtime message. Never surface this.
_DEFAULT_COMPARE_HALLUCINATION_RE = re.compile(
    r"No two resolvable compare sides detected;\s*"
    r"defaulting comparison to CON-0001 vs CON-0002\.?",
    re.I,
)

# Hard out-of-scope guard for invoice / actual-payment systems (before tool selection).
# SAP/Oracle alone are valid vendor names; only refuse when paired with invoice/payment/ERP cues.
_INVOICE_OOS_RE = re.compile(
    r"("
    r"\binvoices?\b|"
    r"\binvoice\s*match\w*|"
    r"\bactual\s+spend\b|"
    r"\bpayment\s+data\b|"
    r"\bpaid\s+amounts?\b|"
    r"\bpayment\s+history\b|"
    r"\binvoice\s+spend\b|"
    r"\bjde\b|"
    r"\bnetsuite\b|"
    r"\b(?:sap|oracle)\b.{0,40}\b(?:invoice|payment|erp|ap\b|accounts?\s+payable)\b|"
    r"\b(?:invoice|payment|erp|ap\b|accounts?\s+payable)\b.{0,40}\b(?:sap|oracle)\b"
    r")",
    re.I,
)
_SPEND_RE = re.compile(
    r"\b(vendor\s+spend|supplier\s+spend|contract\s+value\s+rollup|po\b|purchase\s*order|"
    r"financial\s+aggregate|spend\s+summary|spend\s+rollup)\b",
    re.I,
)
_EXPIRE_RE = re.compile(
    r"\b(expir\w*|upcoming|deadline|contract\s*dates?|end\s*date|need(?:s)?\s+action|"
    r"next\s+\d+\s+days)\b",
    re.I,
)
_DOC_SEARCH_RE = re.compile(
    r"\b(legal|liabilit\w*|clause|pdf|document|policy|blob|unstructured|contract\s*text)\b",
    re.I,
)
_STRUCTURED_SEARCH_RE = re.compile(
    r"\b(show\s+contracts?|list\s+contracts?|find\s+contracts?|search\s+contracts?|"
    r"contracts?\s+for)\b",
    re.I,
)
_OVERLAP_RE = re.compile(
    r"\b(overlap\w*|overlapping\s+contracts?|concurrent\s+contracts?)\b",
    re.I,
)
_RISK_RE = re.compile(
    r"\b(unusual\s+payment\s+terms?|high\s+rates?|rate\s+card|contract\s+risk|"
    r"explain\s+risk|risk\s+review|high\s+supplier\s+risk)\b",
    re.I,
)
_PROFILE_RE = re.compile(
    r"\b(details?\s+for\s+contract|contract\s+profile|show\s+details?|full\s+profile)\b",
    re.I,
)
_COMPARE_RE = re.compile(
    r"\b(compar\w*|diff(?:erence|s)?|versus|vs\.?)\b",
    re.I,
)
_MISSING_RE = re.compile(
    r"\b(missing|incomplete|blank|null|data\s*quality|completeness|required\s*field|"
    r"red[\s-]?flag|compliance|audit|indemnif\w*|liabilit\w*|sla|"
    r"missing\s+renewal)\b",
    re.I,
)
_EXPOSURE_RE = re.compile(
    r"\b(exposure|penalty|penalties|financial\s*risk|what\s*if|breach|damages)\b",
    re.I,
)
_RENEWAL_RE = re.compile(
    r"\b(renew\w*|renegotiat\w*|terminat\w*|auto[\s-]?renew|strategy\s*sheet)\b",
    re.I,
)
_CONTRACT_ID_RE = re.compile(r"\b(?:CON|CNT|C)-\d+\b", re.I)
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
    r"\b("
    r"AlphaTech(?:\s+Services)?|"
    r"Accenture(?:\s+UK)?|"
    r"Amazon(?:\s+AWS)?|AWS|"
    r"Microsoft|"
    r"Google(?:\s+Cloud)?|"
    r"Oracle|SAP|IBM|Salesforce|ServiceNow|Adobe|Cisco|VMware|Snowflake|Databricks|Dell"
    r")\b",
    re.I,
)
_CONTRACT_NAME_RE = re.compile(
    r"(?:contract\s*name|named)\s*[:=]?\s*[\"']?([A-Za-z0-9][A-Za-z0-9 ._/&-]{3,})[\"']?",
    re.I,
)
_COMPARE_SPLIT_RE = re.compile(
    r"\s*(?:,|/|\||\bvs\.?\b|\bversus\b|\bagainst\b|\bwith\b|\band\b)\s*",
    re.I,
)
_COMPARE_ALL_RE = re.compile(
    r"\b(all|every|each)\b.{0,40}\bcontracts?\b|\bcontracts?\b.{0,20}\b(all|every)\b",
    re.I,
)
_COMPARE_LIMIT_RE = re.compile(
    r"\b(?:first|top|next)\s+(\d+)\b|"
    r"\b(\d+)\s+(?:contracts?|agreements?)\b|"
    r"\b(\d+)\s*[- ]\s*way\b",
    re.I,
)
_MEMORY_RECALL_RE = re.compile(
    r"\b("
    r"previous\s+search(?:es)?|prior\s+search(?:es)?|last\s+search|"
    r"old\s+conversation(?:s)?|previous\s+conversation(?:s)?|"
    r"what\s+did\s+i\s+(?:ask|search)|recall|remember|"
    r"search\s+history|conversation\s+history|persona\s+memory"
    r")\b",
    re.I,
)


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
    """Strategic advisor recommendation from quantitative + risk evidence (2..N)."""
    contracts = payload.get("contracts") or []
    if len(contracts) >= 2:
        return _build_multi_compare_recommendation(payload, risk_notes=risk_notes)

    # Legacy pairwise payload shape
    left_id = str(payload.get("left_contract_id") or "Left")
    right_id = str(payload.get("right_contract_id") or "Right")
    synthetic = {
        "contracts": [
            {
                "ContractID": left_id,
                "ContractName": payload.get("left_contract_name") or left_id,
                "SupplierName": payload.get("left_supplier_name") or "Left supplier",
                "ContractStatus": None,
                "ContractValue": None,
                "AnnualContractValue": payload.get("left_annual_cost"),
                "EffectiveDate": None,
                "ExpirationDate": None,
                "AutoRenewalFlag": None,
            },
            {
                "ContractID": right_id,
                "ContractName": payload.get("right_contract_name") or right_id,
                "SupplierName": payload.get("right_supplier_name") or "Right supplier",
                "ContractStatus": None,
                "ContractValue": None,
                "AnnualContractValue": payload.get("right_annual_cost"),
                "EffectiveDate": None,
                "ExpirationDate": None,
                "AutoRenewalFlag": None,
            },
        ]
    }
    # Fill status/value/dates from differences when present.
    diffs = payload.get("differences") or []
    for item in diffs:
        field = item.get("field")
        if field in {
            "ContractStatus",
            "ContractValue",
            "EffectiveDate",
            "ExpirationDate",
            "AutoRenewalFlag",
            "AnnualContractValue",
        }:
            synthetic["contracts"][0][field] = item.get(left_id)
            synthetic["contracts"][1][field] = item.get(right_id)
    return _build_multi_compare_recommendation(synthetic, risk_notes=risk_notes)


def _build_multi_compare_recommendation(
    payload: dict[str, Any],
    *,
    risk_notes: list[str] | None = None,
) -> str:
    contracts = list(payload.get("contracts") or [])
    if len(contracts) < 2:
        return "\n## Recommendation\n\nUnable to recommend — fewer than two contracts resolved."

    scored: list[dict[str, Any]] = []
    justifications: list[str] = []
    annuals = [
        (_as_number(row.get("AnnualContractValue")), str(row.get("ContractID")))
        for row in contracts
    ]
    annuals_valid = [(val, cid) for val, cid in annuals if val is not None]
    if annuals_valid:
        best_annual = min(annuals_valid, key=lambda item: item[0])
        justifications.append(
            f"Lowest annual cost is {best_annual[1]} at {best_annual[0]} — Fabric SQL."
        )

    values = [
        (_as_number(row.get("ContractValue")), str(row.get("ContractID")))
        for row in contracts
    ]
    values_valid = [(val, cid) for val, cid in values if val is not None]
    if values_valid:
        best_value = min(values_valid, key=lambda item: item[0])
        justifications.append(
            f"Lowest total contract value is {best_value[1]} at {best_value[0]} — Fabric SQL."
        )

    for row in contracts:
        cid = str(row.get("ContractID"))
        score = 0
        annual = _as_number(row.get("AnnualContractValue"))
        total = _as_number(row.get("ContractValue"))
        life = _lifecycle_days(row.get("EffectiveDate"), row.get("ExpirationDate"))
        status = str(row.get("ContractStatus") or "").lower()
        auto = row.get("AutoRenewalFlag")

        if annuals_valid and annual is not None:
            min_annual = min(val for val, _ in annuals_valid)
            max_annual = max(val for val, _ in annuals_valid)
            if max_annual != min_annual:
                # Lower cost => higher score
                score += 2.0 * (1.0 - ((annual - min_annual) / (max_annual - min_annual)))
        if values_valid and total is not None:
            min_total = min(val for val, _ in values_valid)
            max_total = max(val for val, _ in values_valid)
            if max_total != min_total:
                score += 1.0 * (1.0 - ((total - min_total) / (max_total - min_total)))
        if life is not None:
            score += min(life / 3650.0, 1.0)  # longer lifecycle modest bonus
        if status == "active":
            score += 1.0
            justifications.append(f"{cid} is Active — lower discontinuity risk (Fabric SQL).")
        elif status in {"expired", "terminated"}:
            score -= 1.0
            justifications.append(f"{cid} status is {row.get('ContractStatus')} — elevated continuity risk (Fabric SQL).")
        if auto is True:
            justifications.append(
                f"{cid} has AutoRenewal enabled — review exit timing / notice risk (Fabric SQL)."
            )

        note_blob = " ".join(risk_notes or []).lower()
        supplier = str(row.get("SupplierName") or "").lower()
        if cid.lower() in note_blob or (supplier and supplier in note_blob):
            if any(token in note_blob for token in ("indemnif", "favorable", "lower liability")):
                score += 0.5
            if any(token in note_blob for token in ("unlimited liability", "lock-in")):
                score -= 0.5

        scored.append(
            {
                "ContractID": cid,
                "ContractName": row.get("ContractName"),
                "SupplierName": row.get("SupplierName"),
                "score": score,
            }
        )

    ranked = sorted(scored, key=lambda item: item["score"], reverse=True)
    winner = ranked[0]
    for note in risk_notes or []:
        justifications.append(note)
    if not justifications:
        justifications.append(
            "Insufficient differentiating quantitative/risk signal; recommendation is provisional."
        )

    ranking_lines = [
        f"- {idx+1}. {item['ContractID']} ({item.get('ContractName')} / {item.get('SupplierName')}) — score {item['score']:.2f}"
        for idx, item in enumerate(ranked)
    ]
    lines = [
        "",
        "## Recommendation",
        "",
        f"**Select {winner['ContractID']} ({winner.get('ContractName')} / {winner.get('SupplierName')}) as structurally superior / lower risk among {len(ranked)} contracts.**",
        "",
        "Ranking:",
        *ranking_lines,
        "",
        "Business justifications:",
    ]
    # de-dupe justifications while preserving order
    seen: set[str] = set()
    for item in justifications:
        if item in seen:
            continue
        seen.add(item)
        lines.append(f"- {item}")
        if len(seen) >= 10:
            break
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
        # Missing-contract path: return only the not-available message.
        if payload.get("error") == "contract_not_present":
            message = str(payload.get("message") or "").strip()
            if message:
                return message
            missing = payload.get("missing") or []
            if missing:
                return f"No such contract is available for {', '.join(str(m) for m in missing)}."
            return "No such contract is available."
        return (
            f"Contract comparison failed: {payload.get('error')}\n"
            f"{json.dumps({k: payload.get(k) for k in ('side_criteria', 'resolved', 'errors', 'left', 'right') if k in payload}, default=str)[:1500]}"
        )

    contracts = payload.get("contracts") or []
    # Normalize pairwise payloads into contracts list for tabular rendering.
    if len(contracts) < 2 and payload.get("left_contract_id") and payload.get("right_contract_id"):
        contracts = [
            {
                "ContractID": payload.get("left_contract_id"),
                "ContractNumber": payload.get("left_contract_number"),
                "ContractName": payload.get("left_contract_name"),
                "ContractType": payload.get("left_contract_type"),
                "SupplierName": payload.get("left_supplier_name"),
                "AnnualContractValue": payload.get("left_annual_cost"),
            },
            {
                "ContractID": payload.get("right_contract_id"),
                "ContractNumber": payload.get("right_contract_number"),
                "ContractName": payload.get("right_contract_name"),
                "ContractType": payload.get("right_contract_type"),
                "SupplierName": payload.get("right_supplier_name"),
                "AnnualContractValue": payload.get("right_annual_cost"),
            },
        ]
        # Prefer full matrix from pairwise result when available.
        if payload.get("field_matrix"):
            pass
        payload = {**payload, "contracts": contracts}

    if len(contracts) < 2:
        return "Contract comparison failed: fewer than two contracts resolved."

    ids = [str(row.get("ContractID")) for row in contracts]
    header_cols = " | ".join(_md_cell(cid) for cid in ids)

    lines = [
        f"### Contract comparison ({len(contracts)}-way)",
        "",
        "#### Quantitative snapshot (Fabric SQL)",
        "",
        f"| Attribute | {header_cols} |",
        "| --- | " + " | ".join(["---"] * len(ids)) + " |",
        "| Contract Number | "
        + " | ".join(_md_cell(row.get("ContractNumber")) for row in contracts)
        + " |",
        "| Contract Name | "
        + " | ".join(_md_cell(row.get("ContractName")) for row in contracts)
        + " |",
        "| Supplier | "
        + " | ".join(_md_cell(row.get("SupplierName")) for row in contracts)
        + " |",
        "| Contract Type | "
        + " | ".join(_md_cell(row.get("ContractType")) for row in contracts)
        + " |",
        "| Status | "
        + " | ".join(_md_cell(row.get("ContractStatus")) for row in contracts)
        + " |",
        "| Annual Cost | "
        + " | ".join(_md_cell(row.get("AnnualContractValue")) for row in contracts)
        + " |",
        "| Total Value | "
        + " | ".join(_md_cell(row.get("ContractValue")) for row in contracts)
        + " |",
        "",
        (
            f"Fields compared: {payload.get('fields_compared')} · "
            f"Matching: {payload.get('matching_field_count')} · "
            f"Differing: {payload.get('difference_count')}"
        ),
        "",
        "#### Field matrix (differences first)",
        "",
        f"| Field | {header_cols} | Match? |",
        "| --- | " + " | ".join(["---"] * len(ids)) + " | --- |",
    ]

    matrix = payload.get("field_matrix") or []
    if not matrix and payload.get("differences"):
        # Build a mini-matrix from pairwise differences + matching fields.
        left_id = str(payload.get("left_contract_id"))
        right_id = str(payload.get("right_contract_id"))
        for item in payload.get("differences") or []:
            matrix.append(
                {
                    "field": item.get("field"),
                    "all_match": False,
                    "values": {
                        left_id: item.get(left_id),
                        right_id: item.get(right_id),
                    },
                }
            )
        for field in payload.get("matching_fields") or []:
            matrix.append(
                {
                    "field": field,
                    "all_match": True,
                    "values": {left_id: "∅", right_id: "∅"},
                }
            )

    # Show differing fields first for readability.
    ordered_matrix = sorted(matrix, key=lambda row: (bool(row.get("all_match")), str(row.get("field"))))
    shown = 0
    for row in ordered_matrix:
        if shown >= limit:
            break
        field = _md_cell(row.get("field"))
        values = row.get("values") or {}
        cells = " | ".join(_md_cell(values.get(cid)) for cid in ids)
        match_flag = "Yes" if row.get("all_match") else "No"
        # Skip sparse matching-only noise when many contracts; keep some matches.
        if row.get("all_match") and shown > max(10, limit // 3):
            continue
        lines.append(f"| {field} | {cells} | {match_flag} |")
        shown += 1
    if len(ordered_matrix) > shown:
        lines.append(
            f"| … | {' | '.join(['…'] * len(ids))} | {len(ordered_matrix) - shown} more rows omitted |"
        )

    if risk_notes:
        lines.extend(["", "#### Risk & liability signals (Azure AI Search)", ""])
        for note in risk_notes[:8]:
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


def _split_compare_targets(text: str) -> list[str]:
    """
    Split a compare prompt into N target segments.

    Examples:
      "compare CON-0005 vs CON-0010 vs CON-0020"
      "compare AWS, Microsoft, and Cisco"
      "compare CON-0001, CON-0002 and CON-0003"
    """
    cleaned = re.sub(
        r"^\s*(please\s+)?(compar\w*|diff(?:erence|s)?)\s+(of\s+|the\s+)?",
        "",
        text.strip(),
        flags=re.I,
    )
    cleaned = re.sub(
        r"^\s*(contracts?|agreements?|vendors?|suppliers?)\s+",
        "",
        cleaned,
        flags=re.I,
    )
    parts = [part.strip(" .;:") for part in _COMPARE_SPLIT_RE.split(cleaned) if part and part.strip(" .;:")]
    # Drop residual connector-only / compare-only tokens.
    filtered = [
        part
        for part in parts
        if part and not re.fullmatch(r"(compar\w*|contracts?|agreements?|vendors?|suppliers?)", part, re.I)
    ]
    return filtered


def _split_compare_sides(text: str) -> tuple[str, str] | None:
    """Backward-compatible pairwise split (first/last of N targets)."""
    parts = _split_compare_targets(text)
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return None


def _requested_compare_limit(text: str, *, default: int = 5, absolute_max: int = 12) -> int:
    match = _COMPARE_LIMIT_RE.search(text or "")
    if match:
        raw = next((g for g in match.groups() if g), None)
        if raw:
            try:
                return max(2, min(int(raw), absolute_max))
            except ValueError:
                pass
    if _COMPARE_ALL_RE.search(text or ""):
        return absolute_max
    return default


def _normalize_supplier_token(name: str) -> str:
    token = (name or "").strip()
    lowered = token.lower()
    if lowered in {"amazon", "amazon aws", "aws"}:
        return "AWS"
    if lowered in {"google cloud", "google"}:
        return "Google Cloud" if "cloud" in lowered else "Google"
    if lowered in {"alphatech", "alphatech services"}:
        return "AlphaTech Services"
    if lowered == "accenture uk":
        return "Accenture UK"
    return token


def _build_compare_kwargs_from_text(
    user_text: str,
    *,
    contract_ids: list[str],
    suppliers: list[str],
    contract_names: list[str],
    contract_types: list[str],
    annual_costs: list[float],
) -> dict[str, Any]:
    """Resolve compare tool kwargs for pairwise or N-way prompts."""
    if len(contract_ids) >= 2:
        return {"contract_refs": ",".join(contract_ids)}
    if len(suppliers) >= 2:
        return {"supplier_names": ",".join(_normalize_supplier_token(s) for s in suppliers)}
    if len(contract_names) >= 2:
        return {"contract_names": ",".join(contract_names)}
    if len(contract_types) >= 2:
        return {"contract_types": ",".join(contract_types)}
    if len(annual_costs) >= 2:
        return {"annual_costs": ",".join(str(v) for v in annual_costs)}

    targets = _split_compare_targets(user_text)
    multi_side = len(targets) >= 2
    if multi_side:
        refs: list[str] = []
        names: list[str] = []
        cnames: list[str] = []
        ctypes: list[str] = []
        costs: list[float] = []
        for part in targets:
            part_ids = _extract_contract_ids(part)
            part_suppliers = [_normalize_supplier_token(s) for s in _extract_suppliers(part)]
            part_names = _extract_contract_names(part)
            part_types = _extract_contract_types(part)
            part_costs = _extract_annual_costs(part)
            if part_ids:
                refs.extend(part_ids)
            elif part_suppliers:
                names.extend(part_suppliers)
            elif part_names:
                cnames.extend(part_names)
            elif part_types:
                ctypes.extend(part_types)
            elif part_costs:
                costs.extend(part_costs)
            else:
                # Bare token: contract id, else treat as supplier label for compare sides.
                # (Unknown vendors must not collapse into single-supplier catalog expansion.)
                token = part.strip().strip("\"'")
                token = re.sub(
                    r"^(contracts?|agreements?|vendors?|suppliers?)\s+",
                    "",
                    token,
                    flags=re.I,
                ).strip()
                if _CONTRACT_ID_RE.fullmatch(token):
                    refs.append(token)
                elif token:
                    names.append(_normalize_supplier_token(token))
        refs = list(dict.fromkeys(refs))
        names = list(dict.fromkeys(names))
        cnames = list(dict.fromkeys(cnames))
        ctypes = list(dict.fromkeys(ctypes))
        costs = list(dict.fromkeys(costs))
        if len(refs) >= 2:
            return {"contract_refs": ",".join(refs)}
        if len(names) >= 2:
            return {"supplier_names": ",".join(names)}
        # Mixed known supplier + unknown vendor → keep both as supplier sides.
        if len(names) >= 1 and len(cnames) >= 1:
            mixed = list(dict.fromkeys([*names, *cnames]))
            if len(mixed) >= 2:
                return {"supplier_names": ",".join(mixed)}
        if len(cnames) >= 2:
            return {"contract_names": ",".join(cnames)}
        if len(ctypes) >= 2:
            return {"contract_types": ",".join(ctypes)}
        if len(costs) >= 2:
            return {"annual_costs": ",".join(str(v) for v in costs)}
        # Explicit multi-side compare that we could not fully classify: do not
        # fall through to single-supplier / catalog expansion (that produced
        # the old CON-0001 vs CON-0002 defaulting behavior).
        if names:
            return {"supplier_names": ",".join(names)}
        if cnames:
            return {"contract_names": ",".join(cnames)}
        if refs:
            return {"contract_refs": ",".join(refs)}
        return {}

    # Single-supplier / "all contracts" expansion is handled by the caller via MCP.
    # Only when the user did not name two distinct compare sides.
    if len(suppliers) == 1 and not multi_side:
        return {
            "supplier_names": _normalize_supplier_token(suppliers[0]),
            "expand_matches": True,
            "max_contracts": _requested_compare_limit(user_text),
        }
    if _COMPARE_ALL_RE.search(user_text) and not multi_side:
        return {
            "expand_matches": True,
            "max_contracts": _requested_compare_limit(user_text),
        }
    return {}


def _lifecycle_red_flag_audit(missing_raw: str, search_raw: str | None = None) -> str:
    findings: list[str] = []
    try:
        missing = json.loads(missing_raw)
    except json.JSONDecodeError:
        missing = {}
    for row in (missing.get("incomplete_contracts") or [])[:8]:
        gaps = ", ".join(row.get("missing_fields") or []) or "unspecified gaps"
        findings.append(
            f"| High | {row.get('ContractID')} / {row.get('SupplierName')} | "
            f"Missing required commercial fields: {gaps} | Fabric SQL |"
        )
    clause_hits = 0
    if search_raw:
        try:
            search = json.loads(search_raw)
            docs = search.get("documents") or []
            clause_hits = len(docs)
            if clause_hits == 0:
                findings.append(
                    "| High | Clause corpus | No liability/indemnification/SLA snippets returned | Azure AI Search |"
                )
            else:
                findings.append(
                    f"| Medium | Clause corpus | {clause_hits} document hits for liability/SLA language — review for one-sided indemnification or weak SLAs | Azure AI Search |"
                )
        except json.JSONDecodeError:
            findings.append(
                "| Medium | Clause corpus | Search payload unreadable; treat legal risk as unverified | Azure AI Search |"
            )

    if not findings:
        findings.append(
            "| Low | Scan | No incomplete-field or clause gaps detected in current tool output | Orchestrator |"
        )

    counter_lines = [
        "",
        "## Dynamic Counter-Clause Drafting",
        "",
        "Proposed fallback language (draft — Legal review required):",
        "",
        "1. **Limitation of Liability** — Cap each party's aggregate liability at 12 months of fees "
        "paid under the agreement, excluding fraud, gross negligence, IP infringement, and "
        "confidentiality breaches.",
        "2. **Mutual Indemnification** — Each party indemnifies the other for third-party claims "
        "arising from its negligence, willful misconduct, or violation of law; vendor additionally "
        "indemnifies for IP infringement claims tied to delivered services.",
        "3. **SLA Credits** — Define measurable uptime (≥99.9%) with service credits up to 10% of "
        "monthly fees; credits are the exclusive remedy for SLA failure unless chronic breach.",
        "4. **Termination for Convenience** — Allow customer termination with 30 days' notice and "
        "payment only for services rendered through the effective termination date.",
        "",
        "Action: route High findings to Legal within 5 business days; do not execute renewals until "
        "fallback language is negotiated or risk is formally accepted.",
    ]

    return "\n".join(
        [
            "## Red-Flag Compliance Audit",
            "",
            "| Severity | Subject | Finding | Source |",
            "| --- | --- | --- | --- |",
            *findings,
            "",
            "Actionable next steps:",
            "- Quarantine High-severity agreements from auto-renew until Legal signs off.",
            "- Open a vendor remediation ticket for each missing liability/SLA control.",
            "- Re-scan with `search_cloud_blob_contracts` after amendment upload.",
            *counter_lines,
        ]
    )


def _lifecycle_financial_exposure(
    spend_raw: str | None,
    expiring_raw: str | None = None,
    search_note: str | None = None,
) -> str:
    annual = None
    supplier = None
    try:
        spend = json.loads(spend_raw or "{}")
        rows = spend.get("rows") or []
        if rows:
            annual = rows[0].get("TotalAnnualContractValue") or rows[0].get("AnnualContractValue")
            supplier = rows[0].get("SupplierName")
    except json.JSONDecodeError:
        spend = {}

    remaining_years = 1.0
    try:
        expiring = json.loads(expiring_raw or "{}")
        erows = expiring.get("rows") or []
        if erows and erows[0].get("ExpirationDate") and erows[0].get("EffectiveDate"):
            life = _lifecycle_days(erows[0].get("EffectiveDate"), erows[0].get("ExpirationDate"))
            if life and life > 0:
                remaining_years = max(life / 365.0, 0.25)
    except Exception:  # noqa: BLE001
        pass

    annual_n = _as_number(annual) or 0.0
    low = annual_n * 0.1 * remaining_years
    base = annual_n * 0.25 * remaining_years
    high = annual_n * 1.0 * remaining_years
    label = supplier or "selected vendor"
    assumptions = [
        f"Baseline annual commercial value ≈ {annual_n} for {label} (Fabric SQL).",
        f"Modeled remaining exposure window ≈ {remaining_years:.2f} years from effective/expiration signals.",
        "Low/base/high use 10%/25%/100% of annualized value as proxy multipliers when penalty caps are unclear.",
    ]
    if search_note:
        assumptions.append(search_note)

    return "\n".join(
        [
            "## Financial Exposure Projection",
            "",
            f"| Scenario | Estimated exposure ({label}) |",
            "| --- | --- |",
            f"| Low | {low:,.2f} |",
            f"| Base | {base:,.2f} |",
            f"| High | {high:,.2f} |",
            "",
            "Assumptions:",
            *[f"- {item}" for item in assumptions],
            "",
            "Actionable cost-control recommendations:",
            "- Negotiate an explicit liability cap tied to 12 months of fees before renewal.",
            "- Require amendment of uncapped indemnities; otherwise escalate for risk acceptance.",
            "- If High scenario exceeds internal risk appetite, pause auto-renew and rebid scope.",
        ]
    )


def _lifecycle_renewal_strategy(expiring_raw: str, spend_raw: str | None = None) -> str:
    try:
        expiring = json.loads(expiring_raw)
    except json.JSONDecodeError:
        expiring = {}
    rows = expiring.get("rows") or []
    spend_by_supplier: dict[str, float] = {}
    try:
        spend = json.loads(spend_raw or "{}")
        for row in spend.get("rows") or []:
            name = str(row.get("SupplierName") or "")
            spend_by_supplier[name.lower()] = float(
                row.get("TotalAnnualContractValue")
                or row.get("AnnualContractValue")
                or 0
            )
    except Exception:  # noqa: BLE001
        pass

    lines = [
        "## Proactive Renewal Strategy Sheet",
        "",
        "| Contract | Supplier | Expiry | Spend signal | Recommended action |",
        "| --- | --- | --- | --- | --- |",
    ]
    checklist: list[str] = []
    for row in rows[:10]:
        supplier = str(row.get("SupplierName") or "Unknown")
        cid = str(row.get("ContractID") or "—")
        expiry = str(row.get("ExpirationDate") or "—")
        annual = _as_number(row.get("AnnualContractValue")) or spend_by_supplier.get(supplier.lower())
        status = str(row.get("ContractStatus") or "").lower()
        auto = row.get("AutoRenewalFlag")
        spend_signal = f"{annual}" if annual is not None else "n/a"
        if status in {"expired", "terminated"}:
            action = "Terminate / transition"
        elif auto is True and (annual or 0) >= 100000:
            action = "Renegotiate pricing caps + liability"
        elif auto is True:
            action = "Auto-renew with SLA/liability review"
        else:
            action = "Renegotiate before term end"
        lines.append(
            f"| {cid} | {supplier} | {expiry} | {spend_signal} | {action} |"
        )
        checklist.append(f"{cid}: execute `{action}` and confirm notice-period compliance.")

    if not rows:
        lines.append("| — | — | — | — | No expiring rows returned |")

    lines.extend(
        [
            "",
            "Procurement execution checklist:",
            *[f"- {item}" for item in checklist[:8]],
            "- Confirm auto-renew notice dates and freeze PO increases pending decision.",
            "- Attach Red-Flag Compliance Audit output to the renewal packet.",
        ]
    )
    return "\n".join(lines)


def is_invoice_out_of_scope(user_text: str) -> bool:
    """Hard-match invoice/actual-spend intents before any tool selection."""
    return bool(_INVOICE_OOS_RE.search(user_text or ""))


def _choose_tools(user_text: str) -> list[str]:
    text = user_text.strip()
    chosen: list[str] = []
    if _MEMORY_RECALL_RE.search(text):
        # Memory recall is handled locally (no MCP tool required).
        return ["persona_memory_recall"]
    if _COMPARE_RE.search(text):
        chosen.append("compare_contracts")
    if _OVERLAP_RE.search(text):
        chosen.append("find_overlaps")
    if _RISK_RE.search(text):
        chosen.append("explain_contract_risk")
    if _PROFILE_RE.search(text) or (
        _CONTRACT_ID_RE.search(text)
        and re.search(r"\b(detail|profile|show)\b", text, re.I)
        and not _COMPARE_RE.search(text)
    ):
        chosen.append("get_contract_profile")
    if "find_overlaps" not in chosen and "explain_contract_risk" not in chosen:
        if _STRUCTURED_SEARCH_RE.search(text) or (
            re.search(r"\bcontracts?\b", text, re.I)
            and _SUPPLIER_RE.search(text)
            and "compare_contracts" not in chosen
            and "get_contract_profile" not in chosen
        ):
            chosen.append("search_contracts")
    if _MISSING_RE.search(text):
        chosen.append("check_missing_contract_fields")
        if (
            "search_contracts" not in chosen
            and "explain_contract_risk" not in chosen
        ):
            chosen.append("search_contracts")
    if _EXPIRE_RE.search(text) or (
        _RENEWAL_RE.search(text) and not _MISSING_RE.search(text)
    ):
        chosen.append("get_expiring_contracts")
    if _SPEND_RE.search(text) or _EXPOSURE_RE.search(text):
        # Contract-value rollups only — never for invoice intents (blocked earlier).
        chosen.append("get_vendor_spend_summary")
    if _EXPOSURE_RE.search(text):
        chosen.append("search_cloud_blob_contracts")
        chosen.append("get_expiring_contracts")
    if _DOC_SEARCH_RE.search(text):
        chosen.append("search_cloud_blob_contracts")
    if not chosen:
        chosen = ["search_contracts"]
    # Invoice-related turns must never call spend rollups.
    if is_invoice_out_of_scope(text):
        return []
    return list(dict.fromkeys(chosen))


def _is_no_such_contract_payload(payload: dict[str, Any]) -> bool:
    if payload.get("error") == "contract_not_present":
        return True
    message = str(payload.get("message") or "").lower()
    return "no such contract is available" in message or (
        "contract information is not present" in message
    )


def _no_such_contract_text(labels: list[Any] | None = None) -> str:
    cleaned = [str(item).strip() for item in (labels or []) if str(item).strip()]
    if cleaned:
        return f"No such contract is available for {', '.join(cleaned)}."
    return "No such contract is available."


def sanitize_default_compare_hallucination(
    text: str,
    *,
    user_text: str = "",
) -> str:
    """
    Strip the legacy CON-0001 vs CON-0002 defaulting message if an LLM or stale
    runtime still emits it. Prefer labeled missing-contract copy when possible.
    """
    raw = str(text or "")
    if not _DEFAULT_COMPARE_HALLUCINATION_RE.search(raw):
        return raw
    labels: list[str] = []
    labels.extend(_extract_contract_ids(user_text))
    labels.extend(_normalize_supplier_token(s) for s in _extract_suppliers(user_text))
    # Also keep unknown multi-side tokens from the compare prompt.
    for part in _split_compare_targets(user_text):
        token = part.strip().strip("\"'")
        if token and token not in labels and not _CONTRACT_ID_RE.fullmatch(token):
            if not _extract_suppliers(token):
                labels.append(_normalize_supplier_token(token))
    labels = list(dict.fromkeys(label for label in labels if label))
    return _no_such_contract_text(labels)


def _summarize_search_contracts(raw: str, *, limit: int = 10) -> str:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return f"Structured contract search\n{raw[:2000]}"
    if _is_no_such_contract_payload(payload):
        message = str(payload.get("message") or "").strip()
        if message:
            return message
        missing = payload.get("missing") or []
        criteria = payload.get("criteria") or {}
        labels = missing or [
            criteria.get(key)
            for key in ("vendor", "contract_type", "business_unit", "status")
            if criteria.get(key)
        ]
        return _no_such_contract_text(labels)
    rows = payload.get("rows") or []
    criteria = payload.get("criteria") or {}
    if not rows and any(criteria.get(k) for k in ("vendor", "contract_type")):
        labels = [
            criteria.get(key)
            for key in ("vendor", "contract_type")
            if criteria.get(key)
        ]
        return _no_such_contract_text(labels)
    lines = [
        f"Structured contract search ({payload.get('row_count', len(rows))} rows)",
        f"Filters: {criteria}" if any(criteria.values()) else "Filters: (none)",
    ]
    for row in rows[:limit]:
        lines.append(
            f"- {row.get('contract_id')} | {row.get('vendor_name')} | "
            f"{row.get('contract_type')} | {row.get('status')} | "
            f"ACV={row.get('annual_contract_value')} {row.get('currency')} | "
            f"expires={row.get('expiration_date')} | "
            f"payment_terms_days={row.get('payment_terms_days')} | "
            f"rate_card_on_file={row.get('rate_card_on_file')}"
        )
    if len(rows) > limit:
        lines.append(f"... {len(rows) - limit} more rows omitted")
    lines.append("Source: synthetic_gold_contracts (MCP search_contracts)")
    return "\n".join(lines)


def _summarize_contract_profile(raw: str) -> str:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return f"Contract profile\n{raw[:2000]}"
    if _is_no_such_contract_payload(payload) or payload.get("error") in {
        "Contract not found",
        "contract_not_present",
    }:
        message = str(payload.get("message") or "").strip()
        if message:
            return message
        cid = payload.get("contract_id")
        return _no_such_contract_text([cid] if cid else None)
    if payload.get("error"):
        return f"Contract profile error: {payload.get('error')} ({payload.get('contract_id')})"
    profile = payload.get("profile") or {}
    missing = profile.get("missing_fields") or []
    lines = [
        f"Contract profile: {profile.get('contract_id')}",
        f"- vendor: {profile.get('vendor_name')}",
        f"- number: {profile.get('contract_number')}",
        f"- type/status: {profile.get('contract_type')} / {profile.get('status')}",
        f"- business_unit: {profile.get('business_unit')}",
        f"- owner: {profile.get('contract_owner')}",
        f"- effective → expiration: {profile.get('effective_date')} → {profile.get('expiration_date')}",
        f"- renewal_date: {profile.get('renewal_date')}",
        f"- ACV: {profile.get('annual_contract_value')} {profile.get('currency')}",
        f"- payment_terms_days: {profile.get('payment_terms_days')}",
        f"- rate_card_on_file: {profile.get('rate_card_on_file')}",
        f"- supplier_risk_rating: {profile.get('supplier_risk_rating')}",
        f"- missing_fields: {', '.join(missing) if missing else '(none)'}",
        "Source: synthetic_gold_contracts (MCP get_contract_profile)",
    ]
    return "\n".join(lines)


def _summarize_overlaps(raw: str, *, limit: int = 15) -> str:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return f"Overlap scan\n{raw[:2000]}"
    rows = payload.get("rows") or []
    lines = [
        f"Overlapping contracts ({payload.get('row_count', len(rows))} pairs)",
        f"Filters: {payload.get('criteria')}",
    ]
    for row in rows[:limit]:
        lines.append(
            f"- {row.get('vendor')} | {row.get('contract_a')} vs {row.get('contract_b')} | "
            f"{row.get('overlap_start')} → {row.get('overlap_end')} | {row.get('why_flagged')}"
        )
    if not rows:
        lines.append("- No same-vendor effective→expiration overlaps found.")
    lines.append("Source: synthetic_gold_contracts (MCP find_overlaps)")
    return "\n".join(lines)


def _summarize_risk_explanations(raw: str, *, limit: int = 8) -> str:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return f"Contract risk explanation\n{raw[:2000]}"
    explanations = payload.get("explanations") or []
    lines = [
        f"Contract risk explanations ({payload.get('row_count', len(explanations))} contracts)",
        f"Filters: {payload.get('criteria')} | as_of={payload.get('as_of')}",
        f"Thresholds: {payload.get('thresholds')}",
    ]
    for item in explanations[:limit]:
        facts = item.get("known_facts") or {}
        risks = item.get("computed_risks") or []
        missing = item.get("missing_data") or []
        lines.append(f"### {item.get('contract_id')} / {facts.get('vendor_name')}")
        lines.append("known_facts:")
        lines.append(
            f"- ACV={facts.get('annual_contract_value')} {facts.get('currency')}; "
            f"payment_terms_days={facts.get('payment_terms_days')}; "
            f"rate_card_on_file={facts.get('rate_card_on_file')}; "
            f"risk_rating={facts.get('supplier_risk_rating')}; "
            f"expires={facts.get('expiration_date')}; renewal={facts.get('renewal_date')}"
        )
        lines.append("computed_risks:")
        if risks:
            for risk in risks:
                lines.append(
                    f"- [{risk.get('severity')}] {risk.get('code')}: {risk.get('detail')}"
                )
        else:
            lines.append("- (none)")
        lines.append(
            f"missing_data: {', '.join(missing) if missing else '(none)'}"
        )
        lines.append(
            f"recommended_review_action: {item.get('recommended_review_action')}"
        )
    lines.append("Source: synthetic_gold_contracts (MCP explain_contract_risk)")
    return "\n".join(lines)


def _summarize_persona_memory(
    *,
    persona_id: str,
    user_text: str,
    chat_history: list[Any] | None = None,
) -> str:
    try:
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        from memory.store import get_memory_store
    except Exception as exc:  # noqa: BLE001
        return f"Persona memory is unavailable ({exc})."

    store = get_memory_store()
    store.ensure_persona(persona_id)
    # Prefer an explicit topic after recall verbs; otherwise list recent memory.
    topic = None
    for pattern in (
        r"\babout\s+(.+)$",
        r"\bfor\s+(.+)$",
        r"\bregarding\s+(.+)$",
    ):
        match = re.search(pattern, user_text, re.I)
        if match:
            topic = match.group(1).strip(" .?!\"'")
            break
    recalled = store.recall(persona_id, query=topic, limit=8)
    lines = [
        f"### Persona memory recall (`{persona_id}`)",
        "",
    ]
    searches = recalled.get("searches") or []
    conversations = recalled.get("conversations") or []
    if not searches and not conversations:
        lines.append("No prior searches or conversations are stored for this persona yet.")
    if searches:
        lines.append("#### Previous searches")
        for idx, row in enumerate(searches, start=1):
            preview = str(row.get("result_preview") or "").strip()
            lines.append(
                f"{idx}. {row.get('query')}"
                + (f" — {preview[:120]}" if preview else "")
                + f" ({row.get('created_at')})"
            )
        lines.append("")
    if conversations:
        lines.append("#### Previous conversations")
        for idx, row in enumerate(conversations, start=1):
            title = row.get("title") or row.get("first_user_message") or row.get("id")
            lines.append(
                f"{idx}. {title} · {row.get('message_count', 0)} messages "
                f"({row.get('updated_at')})"
            )
    if chat_history:
        lines.extend(["", f"Active chat history turns available: {len(chat_history)}"])
    return "\n".join(lines)


async def run_offline_turn(
    user_text: str,
    chat_history: list[Any] | None = None,
    *,
    persona_id: str | None = None,
    conversation_id: str | None = None,
) -> str:
    """Intent-route to MCP tools without calling Azure OpenAI."""
    del conversation_id  # reserved for future turn-scoped memory tools
    if is_invoice_out_of_scope(user_text):
        return INVOICE_OOS_MESSAGE

    selected = _choose_tools(user_text)
    if selected == ["persona_memory_recall"]:
        return _summarize_persona_memory(
            persona_id=persona_id or "default-user",
            user_text=user_text,
            chat_history=chat_history,
        )

    # Lazy import so guardrail unit checks do not require MCP adapter stack.
    from mcp_clients import bridge

    tools = _tool_map(await bridge.get_tools())
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

    # Light context from prior turns when the user refers back without an explicit recall.
    if chat_history and re.search(r"\b(that|those|previous|earlier|same)\b", user_text, re.I):
        recent = []
        for item in chat_history[-4:]:
            content = getattr(item, "content", None)
            if content:
                recent.append(str(content)[:160])
            elif isinstance(item, dict) and item.get("content"):
                recent.append(str(item["content"])[:160])
        if recent:
            sections.append(
                "Context from prior turns in this conversation:\n- " + "\n- ".join(recent)
            )

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
                spend_raw = None
                spend_tool = tools.get("get_vendor_spend_summary")
                if spend_tool:
                    spend_filters = {
                        key: shared_filters[key]
                        for key in ("supplier_name", "contract_type", "annual_cost")
                        if key in shared_filters
                    }
                    spend_raw = await _ainvoke_tool(spend_tool, max_rows=25, **spend_filters)
                if _EXPIRE_RE.search(user_text) or _RENEWAL_RE.search(user_text):
                    sections.append(_lifecycle_renewal_strategy(raw, spend_raw))
                if _EXPOSURE_RE.search(user_text):
                    sections.append(_lifecycle_financial_exposure(spend_raw, raw))
            elif name == "get_vendor_spend_summary":
                spend_filters = {
                    key: shared_filters[key]
                    for key in ("supplier_name", "contract_type", "annual_cost")
                    if key in shared_filters
                }
                raw = await _ainvoke_tool(tool, max_rows=25, **spend_filters)
                sections.append(_summarize_sql_payload(raw, title="Vendor spend summary"))
                if _EXPOSURE_RE.search(user_text) and "Financial Exposure Projection" not in "\n".join(
                    sections
                ):
                    sections.append(_lifecycle_financial_exposure(raw, None))
            elif name == "compare_contracts":
                compare_kwargs = _build_compare_kwargs_from_text(
                    user_text,
                    contract_ids=contract_ids,
                    suppliers=suppliers,
                    contract_names=contract_names,
                    contract_types=contract_types,
                    annual_costs=annual_costs,
                )
                expand_matches = bool(compare_kwargs.pop("expand_matches", False))
                max_contracts = int(compare_kwargs.pop("max_contracts", 5) or 5)
                if expand_matches:
                    # Expand one vendor (or whole catalog slice) into an N-way ID list.
                    search_tool = tools.get("search_contracts")
                    vendor = None
                    if compare_kwargs.get("supplier_names"):
                        vendor = str(compare_kwargs["supplier_names"]).split(",")[0].strip()
                    if search_tool is None:
                        sections.append(
                            "N-way vendor expansion requires `search_contracts`, which is unavailable."
                        )
                        continue
                    search_raw = await _ainvoke_tool(
                        search_tool,
                        vendor=vendor,
                        max_rows=max(max_contracts, 25),
                    )
                    try:
                        search_payload = json.loads(search_raw)
                    except json.JSONDecodeError:
                        search_payload = {}
                    expanded_ids = [
                        str(row.get("contract_id"))
                        for row in (search_payload.get("rows") or [])
                        if row.get("contract_id")
                    ][:max_contracts]
                    if len(expanded_ids) >= 2:
                        compare_kwargs = {"contract_refs": ",".join(expanded_ids)}
                        sections.append(
                            f"Expanded compare set to {len(expanded_ids)} contracts"
                            + (f" for {vendor}" if vendor else "")
                            + f": {', '.join(expanded_ids)}."
                        )
                    else:
                        sections.append(
                            _no_such_contract_text([vendor] if vendor else None)
                        )
                        continue

                if not compare_kwargs:
                    sections.append(_no_such_contract_text())
                    continue
                raw = await _ainvoke_tool(tool, **compare_kwargs)

                # Enrich compare with spend + clause search (orchestrator layer only).
                risk_notes: list[str] = []
                try:
                    compare_payload = json.loads(raw)
                except json.JSONDecodeError:
                    compare_payload = {}

                # Missing contracts: return only the not-available message (no default compare).
                if _is_no_such_contract_payload(compare_payload):
                    sections.append(_summarize_compare_payload(raw))
                    continue

                contract_rows = compare_payload.get("contracts") or []
                if len(contract_rows) < 2 and compare_payload.get("left_contract_id"):
                    contract_rows = [
                        {
                            "ContractID": compare_payload.get("left_contract_id"),
                            "SupplierName": compare_payload.get("left_supplier_name"),
                        },
                        {
                            "ContractID": compare_payload.get("right_contract_id"),
                            "SupplierName": compare_payload.get("right_supplier_name"),
                        },
                    ]
                spend_tool = tools.get("get_vendor_spend_summary")
                search_tool = tools.get("search_cloud_blob_contracts")
                for row in contract_rows:
                    supplier = row.get("SupplierName")
                    label = row.get("ContractID")
                    if spend_tool and supplier:
                        await _ainvoke_tool(
                            spend_tool, max_rows=5, supplier_name=str(supplier)
                        )
                        risk_notes.append(
                            f"Historical spend context for {supplier} retrieved via "
                            f"get_vendor_spend_summary (Fabric SQL)."
                        )
                    if search_tool and supplier:
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
            elif name == "search_contracts":
                vendor = shared_filters.get("supplier_name")
                if vendor and vendor.lower() == "alphatech":
                    vendor = "AlphaTech Services"
                raw = await _ainvoke_tool(
                    tool,
                    vendor=vendor,
                    contract_type=shared_filters.get("contract_type"),
                    max_rows=50,
                )
                sections.append(_summarize_search_contracts(raw))
            elif name == "find_overlaps":
                vendor = shared_filters.get("supplier_name")
                if vendor and vendor.lower() == "alphatech":
                    vendor = "AlphaTech Services"
                raw = await _ainvoke_tool(
                    tool,
                    vendor=vendor,
                    max_rows=200,
                )
                sections.append(_summarize_overlaps(raw))
            elif name == "explain_contract_risk":
                vendor = shared_filters.get("supplier_name")
                if vendor and vendor.lower() == "alphatech":
                    vendor = "AlphaTech Services"
                cid = contract_ids[0] if len(contract_ids) == 1 else None
                raw = await _ainvoke_tool(
                    tool,
                    contract_id=cid,
                    vendor=vendor,
                )
                sections.append(_summarize_risk_explanations(raw))
            elif name == "get_contract_profile":
                cid = contract_ids[0] if contract_ids else None
                if not cid:
                    sections.append("No contract_id detected for get_contract_profile.")
                else:
                    raw = await _ainvoke_tool(tool, contract_id=cid)
                    sections.append(_summarize_contract_profile(raw))
            elif name == "check_missing_contract_fields":
                raw = await _ainvoke_tool(tool, max_rows=100, **shared_filters)
                sections.append(_summarize_missing_payload(raw))
                search_raw = None
                search_tool = tools.get("search_cloud_blob_contracts")
                if search_tool and "search_cloud_blob_contracts" in selected:
                    # Prefer the search result already scheduled later; fetch now for audit.
                    audit_query = (
                        "liability limitation indemnification SLA service level "
                        "termination notice"
                    )
                    if contract_ids:
                        audit_query = f"{contract_ids[0]} {audit_query}"
                    elif suppliers:
                        audit_query = f"{suppliers[0]} {audit_query}"
                    search_raw = await _ainvoke_tool(
                        search_tool,
                        query=audit_query,
                        top=20,
                        **shared_filters,
                    )
                if _MISSING_RE.search(user_text):
                    sections.append(_lifecycle_red_flag_audit(raw, search_raw))
                if _EXPOSURE_RE.search(user_text):
                    spend_tool = tools.get("get_vendor_spend_summary")
                    spend_raw = None
                    if spend_tool:
                        spend_filters = {
                            key: shared_filters[key]
                            for key in ("supplier_name", "contract_type", "annual_cost")
                            if key in shared_filters
                        }
                        spend_raw = await _ainvoke_tool(
                            spend_tool, max_rows=25, **spend_filters
                        )
                    if "Financial Exposure Projection" not in "\n".join(sections):
                        sections.append(
                            _lifecycle_financial_exposure(
                                spend_raw,
                                None,
                                search_note=(
                                    "Clause gaps from compliance audit increase modeled "
                                    "exposure when liability caps are absent."
                                ),
                            )
                        )
            elif name == "search_cloud_blob_contracts":
                # Prefer structured metadata tools for catalog questions.
                if (
                    "search_contracts" in selected
                    or "get_contract_profile" in selected
                    or "find_overlaps" in selected
                    or "explain_contract_risk" in selected
                ):
                    continue
                # Skip duplicate search when missing-field audit already fetched clauses.
                if (
                    "check_missing_contract_fields" in selected
                    and _MISSING_RE.search(user_text)
                    and any("## Red-Flag Compliance Audit" in s for s in sections)
                ):
                    continue
                raw = await _ainvoke_tool(
                    tool,
                    query=user_text,
                    top=20,
                    **shared_filters,
                )
                sections.append(_summarize_search_payload(raw, query=user_text, limit=20))
                if _MISSING_RE.search(user_text) and not any(
                    "## Red-Flag Compliance Audit" in s for s in sections
                ):
                    empty_missing = json.dumps(
                        {"incomplete_contracts": [], "checked_count": 0}
                    )
                    sections.append(_lifecycle_red_flag_audit(empty_missing, raw))
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
    # Missing-contract compares / lookups: return only the not-available message.
    if len(sections) == 1 and (
        "no such contract is available" in sections[0].lower()
        or "contract information is not present" in sections[0].lower()
    ):
        return sanitize_default_compare_hallucination(
            sections[0].strip(),
            user_text=user_text,
        )
    reply = header + "\n\n" + "\n\n".join(sections)
    return sanitize_default_compare_hallucination(reply, user_text=user_text)
