"""Deterministic overlap + risk explanations grounded in repository data only."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from contract_analytics import _as_float, _is_missing, _payment_terms_days, _rate_card_on_file
from contract_repository import SOURCE_LABEL, ContractRepository

UNUSUAL_PAYMENT_TERMS_DAYS = 60
HIGH_ACV_THRESHOLD = 200_000.0
EXPIRING_SOON_DAYS = 90
HIGH_RISK_RATINGS = {"high", "critical"}


def _parse_date(value: Any) -> date | None:
    if _is_missing(value):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _date_overlap(
    a_start: date | None,
    a_end: date | None,
    b_start: date | None,
    b_end: date | None,
) -> tuple[date, date] | None:
    if not a_start or not a_end or not b_start or not b_end:
        return None
    if a_end < a_start or b_end < b_start:
        return None
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    if start <= end:
        return start, end
    return None


def find_overlapping_contracts(
    repo: ContractRepository,
    *,
    vendor: str | None = None,
    business_unit: str | None = None,
    max_rows: int = 200,
) -> dict[str, Any]:
    """
    Detect same-vendor effective→expiration window overlaps.

    Returns stable snake_case overlap records for demo/tool use.
    """
    filters: dict[str, Any] = {}
    if vendor:
        filters["vendor"] = vendor
    if business_unit:
        filters["business_unit"] = business_unit
    rows = repo.search(filters, max_rows=500) if filters else repo.list_all(max_rows=500)

    by_vendor: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        name = str(row.get("SupplierName") or "").strip()
        if not name:
            continue
        by_vendor.setdefault(name.lower(), []).append(row)

    overlaps: list[dict[str, Any]] = []
    for vendor_rows in by_vendor.values():
        for i in range(len(vendor_rows)):
            for j in range(i + 1, len(vendor_rows)):
                left, right = vendor_rows[i], vendor_rows[j]
                window = _date_overlap(
                    _parse_date(left.get("EffectiveDate")),
                    _parse_date(left.get("ExpirationDate")),
                    _parse_date(right.get("EffectiveDate")),
                    _parse_date(right.get("ExpirationDate")),
                )
                if not window:
                    continue
                # Prefer stable ordering by contract id.
                a, b = left, right
                if str(a.get("ContractID") or "") > str(b.get("ContractID") or ""):
                    a, b = b, a
                bu_a = str(a.get("BusinessUnit") or "")
                bu_b = str(b.get("BusinessUnit") or "")
                bu = bu_a if bu_a == bu_b else f"{bu_a}|{bu_b}".strip("|")
                overlaps.append(
                    {
                        "vendor": a.get("SupplierName"),
                        "business_unit": bu or None,
                        "contract_a": a.get("ContractID"),
                        "contract_b": b.get("ContractID"),
                        "overlap_start": window[0].isoformat(),
                        "overlap_end": window[1].isoformat(),
                        "why_flagged": (
                            "Same vendor has concurrent effective→expiration windows "
                            f"({a.get('ContractID')} {a.get('EffectiveDate')}→{a.get('ExpirationDate')} "
                            f"overlaps {b.get('ContractID')} {b.get('EffectiveDate')}→{b.get('ExpirationDate')})"
                        ),
                        "source": SOURCE_LABEL,
                    }
                )

    overlaps.sort(key=lambda item: (str(item.get("vendor")), str(item.get("contract_a"))))
    limited = overlaps[: max(1, int(max_rows))]
    return {
        "tool": "find_overlaps",
        "criteria": {"vendor": vendor, "business_unit": business_unit},
        "row_count": len(limited),
        "total_matches": len(overlaps),
        "rows": limited,
        "source": SOURCE_LABEL,
    }


def _percentile_high_acv(values: list[float], *, floor: float = HIGH_ACV_THRESHOLD) -> float:
    if not values:
        return floor
    ordered = sorted(values)
    idx = max(0, int(round(0.9 * (len(ordered) - 1))))
    return max(floor, ordered[idx])


def explain_contract_risks(
    repo: ContractRepository,
    *,
    contract_id: str | None = None,
    vendor: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """
    Build grounded risk explanations.

    Separates known_facts (raw tool-backed fields) from computed_risks
    (rule evaluations). Never invents unsupported risks.
    """
    today = today or date.today()
    targets: list[dict[str, Any]] = []
    if contract_id and str(contract_id).strip():
        row = repo.get_by_id(str(contract_id).strip())
        if row:
            targets = [row]
    elif vendor and str(vendor).strip():
        targets = repo.get_by_vendor(str(vendor).strip(), max_rows=200)
    else:
        targets = repo.list_all(max_rows=500)

    universe = repo.list_all(max_rows=500)
    acv_values = [
        v
        for v in (_as_float(r.get("AnnualContractValue")) for r in universe)
        if v is not None
    ]
    high_acv_cut = _percentile_high_acv(acv_values)

    overlap_payload = find_overlapping_contracts(
        repo,
        vendor=vendor,
        max_rows=500,
    )
    overlap_ids: set[str] = set()
    for item in overlap_payload.get("rows") or []:
        if item.get("contract_a"):
            overlap_ids.add(str(item["contract_a"]))
        if item.get("contract_b"):
            overlap_ids.add(str(item["contract_b"]))

    explanations: list[dict[str, Any]] = []
    for row in targets:
        cid = str(row.get("ContractID") or "")
        payment_days = _payment_terms_days(row)
        payment_n = _as_float(payment_days)
        acv = _as_float(row.get("AnnualContractValue"))
        rate_card = _rate_card_on_file(row)
        renewal = row.get("RenewalDate")
        risk_rating = str(row.get("SupplierRiskRating") or "").strip()
        exp = _parse_date(row.get("ExpirationDate"))
        days_to_exp = (exp - today).days if exp else None

        known_facts = {
            "contract_id": cid,
            "vendor_name": row.get("SupplierName"),
            "business_unit": row.get("BusinessUnit"),
            "contract_type": row.get("ContractType"),
            "status": row.get("ContractStatus"),
            "effective_date": row.get("EffectiveDate"),
            "expiration_date": row.get("ExpirationDate"),
            "renewal_date": renewal,
            "annual_contract_value": row.get("AnnualContractValue"),
            "currency": row.get("Currency"),
            "payment_terms_days": payment_days,
            "rate_card_on_file": rate_card,
            "supplier_risk_rating": row.get("SupplierRiskRating"),
        }

        computed_risks: list[dict[str, Any]] = []
        missing_data: list[str] = []

        if _is_missing(renewal):
            missing_data.append("renewal_date")
            computed_risks.append(
                {
                    "code": "missing_renewal_date",
                    "severity": "medium",
                    "detail": "RenewalDate is blank/null on the contract record.",
                }
            )
        if rate_card is False:
            missing_data.append("rate_card_on_file")
            computed_risks.append(
                {
                    "code": "missing_rate_card",
                    "severity": "medium",
                    "detail": "RateCardOnFile is false/absent.",
                }
            )
        if days_to_exp is not None and 0 <= days_to_exp <= EXPIRING_SOON_DAYS:
            computed_risks.append(
                {
                    "code": "expiring_soon",
                    "severity": "high",
                    "detail": f"Expires in {days_to_exp} days (threshold {EXPIRING_SOON_DAYS}).",
                }
            )
        if payment_n is not None and payment_n >= UNUSUAL_PAYMENT_TERMS_DAYS:
            computed_risks.append(
                {
                    "code": "unusual_payment_terms",
                    "severity": "medium",
                    "detail": (
                        f"Payment terms are Net {int(payment_n)} "
                        f"(>= {UNUSUAL_PAYMENT_TERMS_DAYS} days)."
                    ),
                }
            )
        if acv is not None and acv >= high_acv_cut:
            computed_risks.append(
                {
                    "code": "high_contract_value_outlier",
                    "severity": "medium",
                    "detail": (
                        f"AnnualContractValue {acv} meets/exceeds outlier cut {high_acv_cut}."
                    ),
                }
            )
        if risk_rating.lower() in HIGH_RISK_RATINGS:
            computed_risks.append(
                {
                    "code": "high_supplier_risk_rating",
                    "severity": "high",
                    "detail": f"SupplierRiskRating is '{risk_rating}'.",
                }
            )
        if cid in overlap_ids:
            related = [
                item
                for item in (overlap_payload.get("rows") or [])
                if cid in {str(item.get("contract_a")), str(item.get("contract_b"))}
            ]
            peers = []
            for item in related[:3]:
                other = (
                    item.get("contract_b")
                    if str(item.get("contract_a")) == cid
                    else item.get("contract_a")
                )
                peers.append(f"{other} ({item.get('overlap_start')}→{item.get('overlap_end')})")
            computed_risks.append(
                {
                    "code": "overlapping_contract",
                    "severity": "high",
                    "detail": "Overlaps another contract for the same vendor: "
                    + (", ".join(peers) if peers else "see find_overlaps"),
                }
            )

        if computed_risks:
            top = {r["code"] for r in computed_risks}
            if "overlapping_contract" in top or "expiring_soon" in top:
                action = "Prioritize commercial/legal review before renewal or new SOW award."
            elif "unusual_payment_terms" in top or "high_contract_value_outlier" in top:
                action = "Validate payment terms and rate card with Procurement; confirm ACV justification."
            elif "missing_renewal_date" in top or "missing_rate_card" in top:
                action = "Backfill missing renewal/rate-card metadata in the contract system of record."
            else:
                action = "Review flagged risk codes with Vendor Management."
        else:
            action = "No rule-based risks triggered from available structured fields."

        explanations.append(
            {
                "contract_id": cid,
                "known_facts": known_facts,
                "computed_risks": computed_risks,
                "missing_data": missing_data,
                "recommended_review_action": action,
                "source": SOURCE_LABEL,
            }
        )

    # Prefer contracts that actually have risks when scanning broadly.
    if not contract_id and not vendor:
        explanations = [e for e in explanations if e.get("computed_risks")] or explanations

    return {
        "tool": "explain_contract_risk",
        "criteria": {"contract_id": contract_id, "vendor": vendor},
        "as_of": today.isoformat(),
        "thresholds": {
            "unusual_payment_terms_days": UNUSUAL_PAYMENT_TERMS_DAYS,
            "high_acv_threshold_used": high_acv_cut,
            "expiring_soon_days": EXPIRING_SOON_DAYS,
        },
        "row_count": len(explanations),
        "explanations": explanations,
        "source": SOURCE_LABEL,
    }
