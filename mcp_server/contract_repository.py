"""
ContractRepository abstraction for the Synthetic Contract Intelligence POC.

Today: FabricContractRepository reads Gold_Vendor_Contracts via Fabric SQL
(or the offline LinkSquares sample interceptor). Later: swap implementation
for live LinkSquares / other CLM sources without changing MCP tool signatures.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from contract_analytics import build_criteria, filter_contracts, resolve_contract
from fabric_sql import execute_query

SOURCE_LABEL = "synthetic_gold_contracts"


class ContractRepository(ABC):
    """Replaceable contract data access boundary."""

    @abstractmethod
    def list_all(self, *, max_rows: int = 500) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_by_id(self, contract_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    def search(self, filters: dict[str, Any] | None = None, *, max_rows: int = 200) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_by_vendor(self, vendor: str, *, max_rows: int = 200) -> list[dict[str, Any]]:
        raise NotImplementedError


class FabricContractRepository(ContractRepository):
    """Gold-layer Fabric SQL backed repository (offline fixtures when mocked)."""

    _SELECT_SQL = """
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

    def list_all(self, *, max_rows: int = 500) -> list[dict[str, Any]]:
        payload = execute_query(self._SELECT_SQL, max_rows=max_rows)
        rows = payload.get("rows") or []
        return [row for row in rows if isinstance(row, dict)]

    def get_by_id(self, contract_id: str) -> dict[str, Any] | None:
        if not contract_id or not str(contract_id).strip():
            return None
        resolved = resolve_contract(
            self.list_all(max_rows=500),
            build_criteria(contract_ref=str(contract_id).strip()),
        )
        contract = resolved.get("contract")
        return contract if isinstance(contract, dict) else None

    def search(self, filters: dict[str, Any] | None = None, *, max_rows: int = 200) -> list[dict[str, Any]]:
        filters = filters or {}
        criteria = build_criteria(
            supplier_name=filters.get("vendor") or filters.get("supplier_name"),
            contract_type=filters.get("contract_type"),
            contract_ref=filters.get("contract_id") or filters.get("contract_ref"),
            contract_name=filters.get("contract_name"),
            annual_cost=filters.get("annual_cost"),
        )
        rows = filter_contracts(self.list_all(max_rows=500), criteria)
        business_unit = filters.get("business_unit")
        if business_unit and str(business_unit).strip():
            needle = str(business_unit).strip().lower()
            rows = [
                row
                for row in rows
                if needle in str(row.get("BusinessUnit") or "").lower()
            ]
        status = filters.get("status")
        if status and str(status).strip():
            needle = str(status).strip().lower()
            rows = [
                row
                for row in rows
                if needle in str(row.get("ContractStatus") or "").lower()
            ]
        return rows[: max(1, int(max_rows))]

    def get_by_vendor(self, vendor: str, *, max_rows: int = 200) -> list[dict[str, Any]]:
        return self.search({"vendor": vendor}, max_rows=max_rows)


_default_repo: ContractRepository | None = None


def get_contract_repository() -> ContractRepository:
    """Process-wide repository singleton (swap here for future CLM backends)."""
    global _default_repo
    if _default_repo is None:
        _default_repo = FabricContractRepository()
    return _default_repo


def set_contract_repository(repo: ContractRepository | None) -> None:
    """Test/helper hook to replace the active repository implementation."""
    global _default_repo
    _default_repo = repo
