"""
Load LinkSquares POC sample files into Gold-shaped offline fixture tables.

Source files (mcp_server/):
  - LinSquare_Contracts_100_Updated_30bb.json
  - agreement_9a06.json

Projections keep MCP/SQL tool contracts stable while the POC data source is
the LinkSquares-shaped sample (not the retired test_fixtures.json).
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

_DIR = Path(__file__).resolve().parent
CONTRACTS_FILE = _DIR / "LinSquare_Contracts_100_Updated_30bb.json"
AGREEMENT_FILE = _DIR / "agreement_9a06.json"

_NET_DAYS_RE = re.compile(r"\bnet\s*(\d+)\b", re.IGNORECASE)


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "")[:19]).date()
    except ValueError:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


def _add_months(value: date, months: int) -> date:
    year = value.year + (value.month - 1 + months) // 12
    month = (value.month - 1 + months) % 12 + 1
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    dim = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return date(year, month, min(value.day, dim))


def _payment_terms_days(payment_terms: Any) -> int | None:
    text = str(payment_terms or "").strip()
    if not text:
        return None
    match = _NET_DAYS_RE.search(text)
    if match:
        return int(match.group(1))
    return None


def _rate_card_on_file(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _supplier_id(supplier_name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "", supplier_name).upper() or "UNKNOWN"
    return f"SUP-{slug[:24]}"


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def load_agreement_metadata(path: Path | None = None) -> dict[str, Any]:
    payload = json.loads((path or AGREEMENT_FILE).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{AGREEMENT_FILE.name} must be a JSON object")
    return payload


def load_raw_contracts(path: Path | None = None) -> list[dict[str, Any]]:
    payload = json.loads((path or CONTRACTS_FILE).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{CONTRACTS_FILE.name} must be a JSON array")
    return [row for row in payload if isinstance(row, dict)]


def project_contract_row(raw: dict[str, Any], agreement: dict[str, Any]) -> dict[str, Any]:
    """Map one LinkSquares sample row (+ shared agreement metadata) to Gold shape."""
    supplier = str(raw.get("SupplierName") or "").strip() or "Unknown"
    renewal = _parse_date(raw.get("RenewalDate"))
    term_months = int(agreement.get("ContractTermMonths") or 36)
    notice_days = agreement.get("NoticePeriodDays")
    auto_renewal = bool(agreement.get("AutoRenewalFlag", False))
    contract_value = float(raw.get("ContractValue") or 0)
    years = max(term_months / 12.0, 1.0)
    annual = round(contract_value / years, 2)
    payment_days = _payment_terms_days(raw.get("PaymentTerms"))
    rate_card = _rate_card_on_file(raw.get("RateCardAvailable"))
    overlap_flag = str(raw.get("OverlapFlag") or "No").strip() or "No"
    action = str(raw.get("ActionRequired") or "No").strip() or "No"

    if renewal is None:
        effective = expiration = None
        status = "Draft"
    else:
        expiration = renewal
        effective = _add_months(renewal, -term_months)
        status = "Active"

    # Mild risk hint from source flags (deterministic, no invented narrative).
    if overlap_flag.lower() == "yes" or (payment_days or 0) >= 180:
        risk = "High"
    elif (payment_days or 0) >= 60 or not rate_card:
        risk = "Medium"
    else:
        risk = "Low"

    contract_id = str(raw.get("ContractID") or "").strip()
    return {
        "ContractID": contract_id,
        "ContractNumber": raw.get("ContractNumber"),
        "ContractName": raw.get("ContractName"),
        "ContractType": agreement.get("AgreementSubCategory") or "Cloud Infrastructure",
        "AgreementType": agreement.get("AgreementCategory") or "Technology",
        "ContractStatus": status,
        "SupplierID": _supplier_id(supplier),
        "SupplierName": supplier,
        "ContractValue": contract_value,
        "AnnualContractValue": annual,
        "Currency": "USD",
        "EffectiveDate": _iso(effective),
        "ExpirationDate": _iso(expiration),
        "RenewalDate": _iso(renewal),
        "AutoRenewalFlag": auto_renewal,
        "BusinessUnit": raw.get("OpCoVendor") or supplier,
        "ContractOwner": None,
        "ParentContractID": None,
        "ParentContractNumber": None,
        "ContractVersion": "1.0",
        "SupplierRiskRating": risk,
        "NoticePeriodDays": notice_days,
        "PaymentTermsDays": payment_days,
        "PaymentTerms": raw.get("PaymentTerms"),
        "RateCardOnFile": rate_card,
        "RateCardAvailable": raw.get("RateCardAvailable"),
        "OverlapFlag": overlap_flag,
        "ActionRequired": action,
        "ContractURL": f"https://contracts.example.com/{contract_id}" if contract_id else None,
        "AgreementCategory": agreement.get("AgreementCategory"),
        "AgreementSubCategory": agreement.get("AgreementSubCategory"),
        "Jurisdiction": agreement.get("Jurisdiction"),
        "GoverningLaw": agreement.get("GoverningLaw"),
        "ConfidentialityClause": agreement.get("ConfidentialityClause"),
        "DataPrivacyClause": agreement.get("DataPrivacyClause"),
        "SLAIncluded": agreement.get("SLAIncluded"),
        "AutoRenewalPeriodMonths": agreement.get("AutoRenewalPeriodMonths"),
        "ContractTermMonths": term_months,
    }


def build_spend_rows(contracts: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
                "Currency": row.get("Currency") or "USD",
                "BusinessUnits": [],
            },
        )
        bucket["ContractCount"] += 1
        bucket["TotalContractValue"] += float(row.get("ContractValue") or 0)
        bucket["TotalAnnualContractValue"] += float(row.get("AnnualContractValue") or 0)
        bu = row.get("BusinessUnit")
        if bu and bu not in bucket["BusinessUnits"]:
            bucket["BusinessUnits"].append(bu)
    return sorted(
        rolled.values(),
        key=lambda item: float(item.get("TotalContractValue") or 0),
        reverse=True,
    )


def build_search_documents(contracts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for row in contracts:
        cid = row.get("ContractID")
        supplier = row.get("SupplierName")
        name = row.get("ContractName")
        docs.append(
            {
                "id": cid,
                "content": (
                    f"{name} between buyer and {supplier}. "
                    f"Type={row.get('ContractType')}; Status={row.get('ContractStatus')}; "
                    f"Value={row.get('ContractValue')} {row.get('Currency')}; "
                    f"Effective={row.get('EffectiveDate')}; Expires={row.get('ExpirationDate')}; "
                    f"PaymentTerms={row.get('PaymentTerms')}; OverlapFlag={row.get('OverlapFlag')}."
                ),
                "title": name,
                "supplierName": supplier,
                "contractId": cid,
                "contractStatus": row.get("ContractStatus"),
                "contractType": row.get("ContractType"),
                "expirationDate": row.get("ExpirationDate"),
                "contractUrl": row.get("ContractURL"),
                "@search.score": 1.0,
            }
        )
    return docs


def build_offline_fixture_tables(
    *,
    contracts_path: Path | None = None,
    agreement_path: Path | None = None,
) -> dict[str, Any]:
    """Return Gold_Vendor_Contracts / Gold_Vendor_Spend / Azure_Search_Documents."""
    agreement = load_agreement_metadata(agreement_path)
    raw_rows = load_raw_contracts(contracts_path)
    contracts = [project_contract_row(row, agreement) for row in raw_rows]
    return {
        "Gold_Vendor_Contracts": contracts,
        "Gold_Vendor_Spend": build_spend_rows(contracts),
        "Azure_Search_Documents": build_search_documents(contracts),
        "Agreement_Metadata": agreement,
    }
