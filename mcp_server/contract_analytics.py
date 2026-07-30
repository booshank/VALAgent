"""Contract comparison and completeness analytics over Gold-layer rows."""

from __future__ import annotations

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


def find_contract_row(
    rows: list[dict[str, Any]],
    contract_ref: str,
) -> dict[str, Any] | None:
    """Match a contract by ContractID or ContractNumber (case-insensitive)."""
    needle = (contract_ref or "").strip().lower()
    if not needle:
        return None
    for row in rows:
        cid = str(row.get("ContractID") or "").strip().lower()
        cnum = str(row.get("ContractNumber") or "").strip().lower()
        if needle in {cid, cnum}:
            return row
    return None


def compare_contract_rows(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    left_id: str,
    right_id: str,
) -> dict[str, Any]:
    """Field-level diff between two contract dictionaries."""
    keys = sorted(set(left.keys()) | set(right.keys()))
    # Stable order: priority fields first, then remaining alphabetical.
    ordered: list[str] = []
    for key in COMPARE_PRIORITY_FIELDS:
        if key in keys:
            ordered.append(key)
    ordered.extend(key for key in keys if key not in ordered)

    differences: list[dict[str, Any]] = []
    matching: list[str] = []
    for key in ordered:
        lv = left.get(key)
        rv = right.get(key)
        if lv == rv:
            matching.append(key)
        else:
            differences.append(
                {
                    "field": key,
                    left_id: lv,
                    right_id: rv,
                }
            )

    return {
        "left_contract_id": left.get("ContractID") or left_id,
        "right_contract_id": right.get("ContractID") or right_id,
        "left_contract_number": left.get("ContractNumber"),
        "right_contract_number": right.get("ContractNumber"),
        "fields_compared": len(ordered),
        "matching_field_count": len(matching),
        "difference_count": len(differences),
        "differences": differences,
        "matching_fields": matching,
    }


def check_missing_fields_in_rows(
    rows: list[dict[str, Any]],
    *,
    required_fields: list[str] | None = None,
    contract_ref: str | None = None,
) -> dict[str, Any]:
    """
    Identify contracts with missing/blank required commercial fields.

    If contract_ref is provided, only that contract is evaluated.
    """
    fields = list(required_fields or DEFAULT_REQUIRED_FIELDS)
    target_rows = rows
    if contract_ref:
        match = find_contract_row(rows, contract_ref)
        target_rows = [match] if match else []

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
                    "SupplierName": row.get("SupplierName"),
                    "ContractStatus": row.get("ContractStatus"),
                    "missing_fields": missing,
                    "missing_count": len(missing),
                }
            )
        else:
            complete_count += 1

    return {
        "required_fields": fields,
        "contracts_evaluated": len(target_rows),
        "complete_count": complete_count,
        "incomplete_count": len(incomplete),
        "contract_ref": contract_ref,
        "not_found": bool(contract_ref) and len(target_rows) == 0,
        "incomplete_contracts": incomplete,
    }
