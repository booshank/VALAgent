"""Contract comparison, completeness, and shared lookup analytics."""

from __future__ import annotations

import json
import re
from typing import Any

# Fields treated as mandatory for a usable commercial contract record.
DEFAULT_REQUIRED_FIELDS: tuple[str, ...] = (
    "ContractID",
    "ContractNumber",
    "ContractName",
    "ContractType",
    "ContractStatus",
    "SupplierID",
    "SupplierName",
    "ContractValue",
    "Currency",
    "EffectiveDate",
    "ExpirationDate",
    "ContractOwner",
    "BusinessUnit",
)

# High-signal fields highlighted first in compare output.
COMPARE_PRIORITY_FIELDS: tuple[str, ...] = (
    "ContractID",
    "ContractNumber",
    "ContractName",
    "ContractType",
    "AgreementType",
    "ContractStatus",
    "SupplierID",
    "SupplierName",
    "ContractValue",
    "AnnualContractValue",
    "Currency",
    "EffectiveDate",
    "ExpirationDate",
    "RenewalDate",
    "AutoRenewalFlag",
    "BusinessUnit",
    "ContractOwner",
    "ParentContractID",
    "ContractVersion",
    "SupplierRiskRating",
)

# Shared lookup dimensions used by compare / missing / expiring / spend tools.
LOOKUP_FIELDS: tuple[str, ...] = (
    "contract_ref",      # ContractID or ContractNumber
    "supplier_name",
    "contract_name",
    "contract_type",
    "annual_cost",       # AnnualContractValue
)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    # pandas.read_sql often materializes SQL NULL as NaN / NA.
    try:
        import pandas as pd

        if pd.isna(value):
            return True
    except Exception:  # noqa: BLE001
        pass
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, float) and value != value:  # NaN
        return True
    if isinstance(value, (list, dict, set, tuple)) and len(value) == 0:
        return True
    return False


def _as_float(value: Any) -> float | None:
    if _is_missing(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("$", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _norm_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _text_matches(cell: Any, needle: str, *, exact: bool = False) -> bool:
    hay = _norm_text(cell)
    needle_n = _norm_text(needle)
    if not needle_n or not hay:
        return False
    if exact:
        return hay == needle_n
    return needle_n in hay or hay in needle_n


def _annual_cost_matches(cell: Any, target: Any, *, tolerance: float = 1.0) -> bool:
    left = _as_float(cell)
    right = _as_float(target)
    if left is None or right is None:
        return False
    return abs(left - right) <= max(tolerance, abs(right) * 0.001)


def build_criteria(
    *,
    contract_ref: str | None = None,
    supplier_name: str | None = None,
    contract_name: str | None = None,
    contract_type: str | None = None,
    annual_cost: float | str | None = None,
) -> dict[str, Any]:
    """Normalize optional lookup criteria used across analytics tools."""
    criteria: dict[str, Any] = {}
    if contract_ref and str(contract_ref).strip():
        criteria["contract_ref"] = str(contract_ref).strip()
    if supplier_name and str(supplier_name).strip():
        criteria["supplier_name"] = str(supplier_name).strip()
    if contract_name and str(contract_name).strip():
        criteria["contract_name"] = str(contract_name).strip()
    if contract_type and str(contract_type).strip():
        criteria["contract_type"] = str(contract_type).strip()
    if annual_cost is not None and str(annual_cost).strip() != "":
        parsed = _as_float(annual_cost)
        if parsed is not None:
            criteria["annual_cost"] = parsed
    return criteria


def criteria_active(criteria: dict[str, Any] | None) -> bool:
    return bool(criteria)


def filter_contracts(
    rows: list[dict[str, Any]],
    criteria: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Filter contracts by any combination of:
    contract_ref, supplier_name, contract_name, contract_type, annual_cost.
    """
    if not criteria:
        return list(rows)

    matched: list[dict[str, Any]] = []
    for row in rows:
        if "contract_ref" in criteria:
            ref = criteria["contract_ref"]
            id_hit = _text_matches(row.get("ContractID"), ref, exact=True)
            num_hit = _text_matches(row.get("ContractNumber"), ref, exact=True)
            # Also allow loose contains on id/number tokens.
            loose = _text_matches(row.get("ContractID"), ref) or _text_matches(
                row.get("ContractNumber"), ref
            )
            if not (id_hit or num_hit or loose):
                continue
        if "supplier_name" in criteria and not _text_matches(
            row.get("SupplierName"), criteria["supplier_name"]
        ):
            continue
        if "contract_name" in criteria and not _text_matches(
            row.get("ContractName"), criteria["contract_name"]
        ):
            continue
        if "contract_type" in criteria and not _text_matches(
            row.get("ContractType"), criteria["contract_type"]
        ):
            continue
        if "annual_cost" in criteria and not _annual_cost_matches(
            row.get("AnnualContractValue"), criteria["annual_cost"]
        ):
            continue
        matched.append(row)
    return matched


def _candidate_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "ContractID": row.get("ContractID"),
        "ContractNumber": row.get("ContractNumber"),
        "ContractName": row.get("ContractName"),
        "ContractType": row.get("ContractType"),
        "SupplierName": row.get("SupplierName"),
        "AnnualContractValue": row.get("AnnualContractValue"),
        "ContractStatus": row.get("ContractStatus"),
    }


def resolve_contract(
    rows: list[dict[str, Any]],
    criteria: dict[str, Any] | None = None,
    *,
    prefer_unique: bool = True,
) -> dict[str, Any]:
    """
    Resolve criteria to a single contract when possible.

    Preference order for ties:
    1) exact ContractID / ContractNumber
    2) exact ContractName
    3) exact SupplierName
    4) first remaining match
    """
    matches = filter_contracts(rows, criteria)
    if not matches:
        return {
            "contract": None,
            "match_count": 0,
            "candidates": [],
            "criteria": criteria or {},
        }
    if len(matches) == 1 or not prefer_unique:
        return {
            "contract": matches[0],
            "match_count": len(matches),
            "candidates": [_candidate_summary(r) for r in matches[:10]],
            "criteria": criteria or {},
        }

    ref = _norm_text((criteria or {}).get("contract_ref"))
    name = _norm_text((criteria or {}).get("contract_name"))
    supplier = _norm_text((criteria or {}).get("supplier_name"))

    def score(row: dict[str, Any]) -> tuple[int, str]:
        points = 0
        if ref and _norm_text(row.get("ContractID")) == ref:
            points += 100
        if ref and _norm_text(row.get("ContractNumber")) == ref:
            points += 90
        if name and _norm_text(row.get("ContractName")) == name:
            points += 50
        if supplier and _norm_text(row.get("SupplierName")) == supplier:
            points += 40
        # Prefer Active contracts when still tied.
        if _norm_text(row.get("ContractStatus")) == "active":
            points += 5
        return (points, str(row.get("ContractID") or ""))

    ranked = sorted(matches, key=score, reverse=True)
    best_score = score(ranked[0])[0]
    unique_best = [row for row in ranked if score(row)[0] == best_score]
    if len(unique_best) == 1:
        chosen = unique_best[0]
        ambiguous = False
    else:
        # Soft-resolve vendor/type-level lookups to one representative contract
        # (highest score, preferring Active) so compare/filter tools remain usable.
        chosen = ranked[0]
        ambiguous = True
    return {
        "contract": chosen,
        "match_count": len(matches),
        "candidates": [_candidate_summary(r) for r in ranked[:10]],
        "criteria": criteria or {},
        "ambiguous": ambiguous,
    }


def find_contract_row(
    rows: list[dict[str, Any]],
    contract_ref: str | None = None,
    *,
    supplier_name: str | None = None,
    contract_name: str | None = None,
    contract_type: str | None = None,
    annual_cost: float | str | None = None,
) -> dict[str, Any] | None:
    """Backward-compatible helper: resolve one contract from shared criteria."""
    criteria = build_criteria(
        contract_ref=contract_ref,
        supplier_name=supplier_name,
        contract_name=contract_name,
        contract_type=contract_type,
        annual_cost=annual_cost,
    )
    if not criteria:
        return None
    return resolve_contract(rows, criteria).get("contract")


def compare_contract_rows(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    left_id: str,
    right_id: str,
) -> dict[str, Any]:
    """Field-level diff between two contract dictionaries."""
    multi = compare_many_contract_rows([left, right])
    left_cid = str(left.get("ContractID") or left_id)
    right_cid = str(right.get("ContractID") or right_id)
    differences: list[dict[str, Any]] = []
    matching: list[str] = []
    for row in multi.get("field_matrix") or []:
        field = row.get("field")
        values = row.get("values") or {}
        if row.get("all_match"):
            matching.append(str(field))
        else:
            differences.append(
                {
                    "field": field,
                    left_cid: values.get(left_cid),
                    right_cid: values.get(right_cid),
                }
            )
    overview = {item["ContractID"]: item for item in multi.get("contracts") or []}
    return {
        "mode": "pairwise",
        "left_contract_id": left_cid,
        "right_contract_id": right_cid,
        "left_contract_number": left.get("ContractNumber"),
        "right_contract_number": right.get("ContractNumber"),
        "left_supplier_name": left.get("SupplierName"),
        "right_supplier_name": right.get("SupplierName"),
        "left_contract_name": left.get("ContractName"),
        "right_contract_name": right.get("ContractName"),
        "left_contract_type": left.get("ContractType"),
        "right_contract_type": right.get("ContractType"),
        "left_annual_cost": left.get("AnnualContractValue"),
        "right_annual_cost": right.get("AnnualContractValue"),
        "fields_compared": multi.get("fields_compared"),
        "matching_field_count": len(matching),
        "difference_count": len(differences),
        "differences": differences,
        "matching_fields": matching,
        "contracts": multi.get("contracts"),
        "field_matrix": multi.get("field_matrix"),
        "overview": overview,
    }


def compare_many_contract_rows(contracts: list[dict[str, Any]]) -> dict[str, Any]:
    """
    N-way field comparison across 2+ contracts.

    Returns an overview per contract plus a field matrix with per-contract values.
    """
    if len(contracts) < 2:
        raise ValueError("compare_many_contract_rows requires at least 2 contracts")

    labeled: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for idx, row in enumerate(contracts):
        cid = str(row.get("ContractID") or row.get("ContractNumber") or f"contract_{idx+1}")
        if cid in seen:
            cid = f"{cid}#{idx+1}"
        seen.add(cid)
        labeled.append((cid, row))

    keys = sorted(set().union(*(row.keys() for _, row in labeled)))
    ordered: list[str] = []
    for key in COMPARE_PRIORITY_FIELDS:
        if key in keys:
            ordered.append(key)
    ordered.extend(key for key in keys if key not in ordered)

    field_matrix: list[dict[str, Any]] = []
    matching_fields: list[str] = []
    differing_fields: list[str] = []
    for key in ordered:
        values = {cid: row.get(key) for cid, row in labeled}
        normalized = [json.dumps(value, default=str, sort_keys=True) for value in values.values()]
        all_match = len(set(normalized)) == 1
        entry = {
            "field": key,
            "values": values,
            "all_match": all_match,
        }
        field_matrix.append(entry)
        if all_match:
            matching_fields.append(key)
        else:
            differing_fields.append(key)

    overview = []
    for cid, row in labeled:
        overview.append(
            {
                "ContractID": cid,
                "ContractNumber": row.get("ContractNumber"),
                "ContractName": row.get("ContractName"),
                "ContractType": row.get("ContractType"),
                "SupplierName": row.get("SupplierName"),
                "ContractStatus": row.get("ContractStatus"),
                "ContractValue": row.get("ContractValue"),
                "AnnualContractValue": row.get("AnnualContractValue"),
                "Currency": row.get("Currency"),
                "EffectiveDate": row.get("EffectiveDate"),
                "ExpirationDate": row.get("ExpirationDate"),
                "AutoRenewalFlag": row.get("AutoRenewalFlag"),
            }
        )

    return {
        "mode": "multi",
        "contract_count": len(labeled),
        "contract_ids": [cid for cid, _ in labeled],
        "contracts": overview,
        "fields_compared": len(ordered),
        "matching_field_count": len(matching_fields),
        "difference_count": len(differing_fields),
        "matching_fields": matching_fields,
        "differing_fields": differing_fields,
        "field_matrix": field_matrix,
    }


def check_missing_fields_in_rows(
    rows: list[dict[str, Any]],
    *,
    required_fields: list[str] | None = None,
    criteria: dict[str, Any] | None = None,
    contract_ref: str | None = None,
) -> dict[str, Any]:
    """
    Identify contracts with missing/blank required commercial fields.

    Optional shared criteria narrow the evaluation set (supplier/name/type/cost/ref).
    """
    fields = list(required_fields or DEFAULT_REQUIRED_FIELDS)
    effective = dict(criteria or {})
    if contract_ref and "contract_ref" not in effective:
        effective["contract_ref"] = contract_ref

    if effective:
        target_rows = filter_contracts(rows, effective)
    else:
        target_rows = list(rows)

    incomplete: list[dict[str, Any]] = []
    complete_count = 0
    for row in target_rows:
        missing = [field for field in fields if _is_missing(row.get(field))]
        if missing:
            incomplete.append(
                {
                    "ContractID": row.get("ContractID"),
                    "ContractNumber": row.get("ContractNumber"),
                    "ContractName": row.get("ContractName"),
                    "ContractType": row.get("ContractType"),
                    "SupplierName": row.get("SupplierName"),
                    "AnnualContractValue": row.get("AnnualContractValue"),
                    "ContractStatus": row.get("ContractStatus"),
                    "missing_fields": missing,
                    "missing_count": len(missing),
                }
            )
        else:
            complete_count += 1

    return {
        "required_fields": fields,
        "criteria": effective,
        "contracts_evaluated": len(target_rows),
        "complete_count": complete_count,
        "incomplete_count": len(incomplete),
        "not_found": bool(effective) and len(target_rows) == 0,
        "incomplete_contracts": incomplete,
    }


PROFILE_REQUIRED_FIELDS: tuple[str, ...] = DEFAULT_REQUIRED_FIELDS + (
    "RenewalDate",
)


def _payment_terms_days(row: dict[str, Any]) -> Any:
    if not _is_missing(row.get("PaymentTermsDays")):
        return row.get("PaymentTermsDays")
    if not _is_missing(row.get("NoticePeriodDays")):
        return row.get("NoticePeriodDays")
    return None


def _rate_card_on_file(row: dict[str, Any]) -> bool:
    value = row.get("RateCardOnFile")
    if isinstance(value, bool):
        return value
    if _is_missing(value):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def normalize_contract_search_row(row: dict[str, Any]) -> dict[str, Any]:
    """Stable structured search projection (snake_case)."""
    return {
        "contract_id": row.get("ContractID"),
        "contract_number": row.get("ContractNumber"),
        "vendor_name": row.get("SupplierName"),
        "business_unit": row.get("BusinessUnit"),
        "contract_type": row.get("ContractType"),
        "status": row.get("ContractStatus"),
        "effective_date": row.get("EffectiveDate"),
        "expiration_date": row.get("ExpirationDate"),
        "renewal_date": row.get("RenewalDate"),
        "annual_contract_value": row.get("AnnualContractValue"),
        "currency": row.get("Currency"),
        "rate_card_on_file": _rate_card_on_file(row),
        "payment_terms_days": _payment_terms_days(row),
        "source": "synthetic_gold_contracts",
    }


def normalize_contract_profile(row: dict[str, Any]) -> dict[str, Any]:
    """Full normalized profile for one contract, including missing_fields."""
    missing = [
        field for field in PROFILE_REQUIRED_FIELDS if _is_missing(row.get(field))
    ]
    return {
        "contract_id": row.get("ContractID"),
        "contract_number": row.get("ContractNumber"),
        "vendor_name": row.get("SupplierName"),
        "business_unit": row.get("BusinessUnit"),
        "contract_type": row.get("ContractType"),
        "status": row.get("ContractStatus"),
        "effective_date": row.get("EffectiveDate"),
        "expiration_date": row.get("ExpirationDate"),
        "renewal_date": row.get("RenewalDate"),
        "contract_owner": row.get("ContractOwner"),
        "annual_contract_value": row.get("AnnualContractValue"),
        "currency": row.get("Currency"),
        "payment_terms_days": _payment_terms_days(row),
        "rate_card_on_file": _rate_card_on_file(row),
        "supplier_risk_rating": row.get("SupplierRiskRating"),
        "missing_fields": missing,
        "source": "synthetic_gold_contracts",
    }
