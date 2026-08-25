"""Offline staging checks for the mcp_server LinkSquares mock interceptor."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def test_offline_interceptor_roundtrip() -> None:
    env = {
        **os.environ,
        "USE_OFFLINE_MOCKS": "true",
        # Ensure production credential gates are not required in offline mode.
        "FABRIC_SQL_SERVER": "offline.local",
        "FABRIC_SQL_DATABASE": "gold_layer",
        "AZURE_SEARCH_ENDPOINT": "https://offline.search.windows.net",
        "AZURE_SEARCH_API_KEY": "offline-key",
        "AZURE_SEARCH_INDEX_NAME": "documents",
    }
    script = r"""
import json
import server

assert server._OFFLINE_MOCKS_ENABLED is True

expiring = json.loads(server.get_expiring_contracts(days_ahead=3650, max_rows=50))
assert expiring["row_count"] > 0, expiring
assert "ContractID" in expiring["columns"]

renewals = json.loads(server.list_renewals_in_window(days_ahead=365, max_rows=50))
assert renewals["row_count"] > 0, renewals
assert renewals["procedure"] == "renewal_window_list"
assert renewals["tool"] == "list_renewals_in_window"
assert renewals["window"]["start"] and renewals["window"]["end"]
alias_renewals = json.loads(server.get_contract_renewals(days_ahead=365, max_rows=50))
assert alias_renewals["row_count"] == renewals["row_count"]

spend = json.loads(server.get_vendor_spend_summary(max_rows=50))
assert spend["row_count"] > 0, spend
assert "SupplierName" in spend["columns"]

search = json.loads(server.search_cloud_blob_contracts("Microsoft", top=3))
assert search["query_type"] == "semantic"
assert search["count"] > 0
assert search["documents"]

compared = json.loads(
    server.compare_contracts(contract_ref_a="CON-0001", contract_ref_b="CON-0002")
)
assert compared.get("difference_count", 0) > 0, compared
assert compared.get("left_contract_id") == "CON-0001"

multi = json.loads(
    server.compare_contracts(contract_refs="CON-0001,CON-0002,CON-0004")
)
assert multi.get("contract_count") == 3 or len(multi.get("contracts") or []) == 3, multi
assert multi.get("field_matrix"), multi

# Arbitrary non-leading IDs + supplier expansion
later = json.loads(server.compare_contracts(contract_refs="CON-0044,CON-0077,CON-0090"))
assert later.get("error") is None, later
assert len(later.get("contracts") or []) == 3, later

expanded = json.loads(
    server.compare_contracts(
        supplier_names="AWS",
        expand_supplier_matches=True,
        max_contracts=3,
    )
)
assert expanded.get("error") is None, expanded
assert len(expanded.get("contracts") or []) == 3, expanded
assert all(r.get("SupplierName") == "AWS" for r in expanded["contracts"])

by_supplier = json.loads(
    server.compare_contracts(supplier_name_a="Microsoft", supplier_name_b="Oracle")
)
assert by_supplier.get("difference_count", 0) > 0, by_supplier
assert by_supplier.get("left_supplier_name")
assert by_supplier.get("right_supplier_name")

missing = json.loads(server.identify_missing_fields(max_rows=50))
assert "incomplete_contracts" in missing
assert missing["contracts_evaluated"] > 0
assert missing["tool"] == "identify_missing_fields"
alias_missing = json.loads(server.check_missing_contract_fields(max_rows=50))
assert alias_missing["incomplete_count"] == missing["incomplete_count"]

missing_msft = json.loads(
    server.identify_missing_fields(supplier_name="Microsoft", max_rows=50)
)
assert missing_msft["contracts_evaluated"] > 0

expiring_filtered = json.loads(
    server.get_expiring_contracts(days_ahead=3650, supplier_name="Microsoft", max_rows=50)
)
assert expiring_filtered["row_count"] > 0
assert all(
    "microsoft" in str(row.get("SupplierName") or "").lower()
    for row in expiring_filtered["rows"]
)

health = json.loads(server.fabric_health_check())
assert health["status"] == "ok", health

structured = json.loads(server.search_contracts(vendor="Microsoft", max_rows=50))
assert structured["row_count"] >= 3, structured
assert any(r.get("contract_id") == "CON-0002" for r in structured["rows"])

profile = json.loads(server.get_contract_profile("CON-0002"))
assert profile.get("profile", {}).get("contract_id") == "CON-0002", profile
assert "missing_fields" in profile.get("profile", {})

overlaps = json.loads(server.find_overlaps(vendor="Microsoft", max_rows=50))
assert overlaps["row_count"] >= 1, overlaps
pair_ids = {
    frozenset({row.get("contract_a"), row.get("contract_b")}) for row in overlaps["rows"]
}
assert frozenset({"CON-0024", "CON-0029"}) in pair_ids, pair_ids

risk = json.loads(server.explain_contract_risk(contract_id="CON-0011"))
assert risk["row_count"] >= 1, risk
exp = risk["explanations"][0]
assert "known_facts" in exp and "computed_risks" in exp
codes = {r.get("code") for r in exp["computed_risks"]}
assert "unusual_payment_terms" in codes, codes

print("offline interceptor OK")
print(f"  expiring_rows={expiring['row_count']}")
print(f"  renewal_rows={renewals['row_count']} window={renewals['window']}")
print(f"  spend_rows={spend['row_count']}")
print(f"  search_docs={search['count']}")
print(f"  compare_diffs={compared['difference_count']}")
print(f"  incomplete={missing['incomplete_count']}")
print(f"  search_contracts={structured['row_count']}")
print(f"  profile={profile['profile']['contract_id']}")
print(f"  overlaps={overlaps['row_count']}")
print(f"  risk_codes={sorted(codes)}")
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stdout + "\n" + proc.stderr)
    print(proc.stdout.strip())


def test_production_tools_have_no_mock_branches() -> None:
    source = (ROOT / "server.py").read_text(encoding="utf-8")
    # Tool bodies must not branch on USE_OFFLINE_MOCKS.
    tool_markers = [
        "def get_expiring_contracts",
        "def list_renewals_in_window",
        "def get_contract_renewals",
        "def get_vendor_spend_summary",
        "def compare_contracts",
        "def identify_missing_fields",
        "def check_missing_contract_fields",
        "def search_cloud_blob_contracts",
        "def search_contracts",
        "def get_contract_profile",
        "def find_overlaps",
        "def explain_contract_risk",
    ]
    for marker in tool_markers:
        start = source.index(marker)
        # Slice until next top-level @mcp.tool or end helpers
        rest = source[start:]
        next_def = rest.find("\n@mcp.tool")
        body = rest if next_def < 0 else rest[:next_def]
        assert "USE_OFFLINE_MOCKS" not in body, f"{marker} contains mock conditional"
        assert "test_fixtures" not in body, f"{marker} references fixtures directly"
        assert "LinSquare_Contracts" not in body, f"{marker} references fixtures directly"
    print("production tools are mock-free")


def test_linksquares_fixture_files_present() -> None:
    assert (ROOT / "LinSquare_Contracts_100_Updated_30bb.json").is_file()
    assert (ROOT / "agreement_9a06.json").is_file()
    assert not (ROOT / "test_fixtures.json").exists()
    assert not (ROOT / "Test_contracts_0397.json").exists()
    from linksquares_fixtures import build_offline_fixture_tables

    tables = build_offline_fixture_tables()
    assert len(tables["Gold_Vendor_Contracts"]) == 100
    assert tables["Gold_Vendor_Spend"]
    assert tables["Azure_Search_Documents"]
    print("linksquares fixture files OK")


if __name__ == "__main__":
    test_linksquares_fixture_files_present()
    test_production_tools_have_no_mock_branches()
    test_offline_interceptor_roundtrip()
