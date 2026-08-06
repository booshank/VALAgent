"""Deterministic checks for Synthetic Contract Intelligence Tool-Layer POC."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
MCP = REPO / "mcp_server"
MCP_PY = MCP / ".venv" / "bin" / "python"
sys.path.insert(0, str(ROOT))

os.environ["USE_OFFLINE_MOCKS"] = "true"


def test_invoice_guardrail_hard_match() -> None:
    from offline_router import INVOICE_OOS_MESSAGE, _choose_tools, is_invoice_out_of_scope

    question = "Can you show invoice spend also?"
    assert is_invoice_out_of_scope(question)
    assert _choose_tools(question) == []
    assert "get_vendor_spend_summary" not in _choose_tools(question)

    async def _run() -> str:
        from offline_router import run_offline_turn

        return await run_offline_turn(question)

    reply = asyncio.run(_run())
    assert reply.strip() == INVOICE_OOS_MESSAGE, reply
    assert "AnnualContractValue" not in reply
    assert "Vendor spend summary" not in reply
    print("invoice guardrail OK")


def _run_mcp_snippet(snippet: str) -> str:
    env = {
        **os.environ,
        "USE_OFFLINE_MOCKS": "true",
        "FABRIC_SQL_SERVER": "offline.local",
        "FABRIC_SQL_DATABASE": "gold_layer",
        "AZURE_SEARCH_ENDPOINT": "https://offline.search.windows.net",
        "AZURE_SEARCH_API_KEY": "offline-key",
        "AZURE_SEARCH_INDEX_NAME": "documents",
    }
    python = str(MCP_PY if MCP_PY.exists() else sys.executable)
    proc = subprocess.run(
        [python, "-c", snippet],
        cwd=str(MCP),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stdout + "\n" + proc.stderr)
    return proc.stdout.strip()


def test_search_contracts_microsoft() -> None:
    out = _run_mcp_snippet(
        r"""
import json, server
payload = json.loads(server.search_contracts(vendor="Microsoft", max_rows=50))
assert payload["row_count"] >= 3, payload
ids = {row["contract_id"] for row in payload["rows"]}
assert "CON-0002" in ids
row = next(r for r in payload["rows"] if r["contract_id"] == "CON-0002")
for key in (
    "contract_id","vendor_name","business_unit","status","effective_date",
    "expiration_date","annual_contract_value","payment_terms_days",
    "rate_card_on_file","source",
):
    assert key in row, key
print(json.dumps({"row_count": payload["row_count"], "sample": "CON-0002"}))
"""
    )
    print("search_contracts OK", out)


def test_get_contract_profile_con0002() -> None:
    out = _run_mcp_snippet(
        r"""
import json, server
payload = json.loads(server.get_contract_profile("CON-0002"))
assert payload.get("error") is None, payload
profile = payload["profile"]
assert profile["contract_id"] == "CON-0002"
assert profile["vendor_name"] == "Microsoft"
assert "missing_fields" in profile
assert profile["rate_card_on_file"] is True
print(json.dumps({"contract_id": profile["contract_id"], "missing_fields": profile["missing_fields"]}))
"""
    )
    print("get_contract_profile OK", out)


def test_compare_contracts_any_ids_and_nway() -> None:
    out = _run_mcp_snippet(
        r"""
import json, server

# Arbitrary pairwise (not the first two catalog rows)
pair = json.loads(server.compare_contracts(contract_refs="CON-0005,CON-0088"))
assert pair.get("error") is None, pair
assert {pair.get("left_contract_id"), pair.get("right_contract_id")} == {"CON-0005", "CON-0088"}
assert pair.get("difference_count", 0) > 0

# Explicit 4-way
nway = json.loads(
    server.compare_contracts(contract_refs="CON-0005,CON-0010,CON-0020,CON-0030")
)
assert nway.get("error") is None, nway
assert nway.get("mode") == "multi" or nway.get("contract_count") == 4
assert len(nway.get("contracts") or []) == 4
assert nway.get("difference_count", 0) > 0
ids = {row.get("ContractID") for row in nway["contracts"]}
assert ids == {"CON-0005", "CON-0010", "CON-0020", "CON-0030"}

# Supplier expansion
expanded = json.loads(
    server.compare_contracts(
        supplier_names="Microsoft",
        expand_supplier_matches=True,
        max_contracts=4,
    )
)
assert expanded.get("error") is None, expanded
assert len(expanded.get("contracts") or []) == 4
assert all(row.get("SupplierName") == "Microsoft" for row in expanded["contracts"])

print(json.dumps({
    "pair": [pair.get("left_contract_id"), pair.get("right_contract_id")],
    "nway": sorted(ids),
    "expanded": [row.get("ContractID") for row in expanded["contracts"]],
}))
"""
    )
    print("compare_contracts any/n-way OK", out)


def test_offline_router_compare_routing() -> None:
    from offline_router import (
        _build_compare_kwargs_from_text,
        _extract_contract_ids,
        _extract_suppliers,
        _split_compare_targets,
    )

    q = "Compare CON-0005 vs CON-0010 vs CON-0020"
    assert _extract_contract_ids(q) == ["CON-0005", "CON-0010", "CON-0020"]
    assert _split_compare_targets(q) == ["CON-0005", "CON-0010", "CON-0020"]
    kwargs = _build_compare_kwargs_from_text(
        q,
        contract_ids=_extract_contract_ids(q),
        suppliers=_extract_suppliers(q),
        contract_names=[],
        contract_types=[],
        annual_costs=[],
    )
    assert kwargs["contract_refs"] == "CON-0005,CON-0010,CON-0020"

    q2 = "Compare AWS, Microsoft, and Cisco"
    assert set(_extract_suppliers(q2)) >= {"AWS", "Microsoft", "Cisco"}
    kwargs2 = _build_compare_kwargs_from_text(
        q2,
        contract_ids=[],
        suppliers=_extract_suppliers(q2),
        contract_names=[],
        contract_types=[],
        annual_costs=[],
    )
    names = [n.strip() for n in kwargs2["supplier_names"].split(",")]
    assert set(names) >= {"AWS", "Microsoft", "Cisco"}

    q3 = "Compare all Microsoft contracts"
    kwargs3 = _build_compare_kwargs_from_text(
        q3,
        contract_ids=[],
        suppliers=_extract_suppliers(q3),
        contract_names=[],
        contract_types=[],
        annual_costs=[],
    )
    assert kwargs3.get("expand_matches") is True
    assert "CON-0001,CON-0002" not in str(kwargs3)
    print("offline compare routing OK", kwargs, kwargs2, kwargs3)


def test_oracle_vendor_not_blocked() -> None:
    from offline_router import _choose_tools, is_invoice_out_of_scope

    q = "Show contracts for Oracle"
    assert not is_invoice_out_of_scope(q)
    tools = _choose_tools(q)
    assert "search_contracts" in tools
    assert "get_vendor_spend_summary" not in tools
    print("oracle vendor routing OK", tools)


def test_persona_memory_recall_routing() -> None:
    from offline_router import _choose_tools, _summarize_persona_memory
    import tempfile
    from pathlib import Path
    import os
    import sys

    assert _choose_tools("Show my previous searches") == ["persona_memory_recall"]
    assert _choose_tools("Recall old conversations") == ["persona_memory_recall"]

    repo = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo))
    from memory.store import PersonaMemoryStore

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "recall.sqlite"
        os.environ["VAL_MEMORY_DB"] = str(db)
        store = PersonaMemoryStore(db)
        store.ensure_persona("recall-user", "Recall User")
        conv = store.ensure_conversation(None, "recall-user")
        store.append_message(
            conv["id"],
            "user",
            "Show contracts for Microsoft",
            persona_id="recall-user",
        )
        store.update_latest_search_preview(
            "recall-user",
            conv["id"],
            "33 Microsoft rows",
        )
        text = _summarize_persona_memory(
            persona_id="recall-user",
            user_text="Show my previous searches about Microsoft",
        )
        assert "Persona memory recall" in text
        assert "Microsoft" in text
        print("persona memory recall OK")



def test_find_overlaps_tool_and_routing() -> None:
    from offline_router import _choose_tools

    q = "Are there overlapping contracts for the same vendor?"
    assert _choose_tools(q) == ["find_overlaps"]
    out = _run_mcp_snippet(
        r"""
import json, server
payload = json.loads(server.find_overlaps(max_rows=200))
assert payload["row_count"] >= 1, payload
rows = payload["rows"]
assert {"vendor","business_unit","contract_a","contract_b","overlap_start","overlap_end","why_flagged","source"} <= set(rows[0])
msft = [r for r in rows if r.get("vendor") == "Microsoft"]
assert any({r.get("contract_a"), r.get("contract_b")} == {"CON-0024","CON-0029"} for r in msft), msft[:5]
print(json.dumps({"row_count": payload["row_count"], "sample": msft[0]}))
"""
    )
    print("find_overlaps OK", out)


def test_explain_contract_risk_tool_and_routing() -> None:
    from offline_router import _choose_tools

    q = "Which contracts have unusual payment terms or high rates?"
    assert "explain_contract_risk" in _choose_tools(q)
    out = _run_mcp_snippet(
        r"""
import json, server
payload = json.loads(server.explain_contract_risk(contract_id="CON-0011"))
exp = payload["explanations"][0]
for key in ("known_facts","computed_risks","missing_data","recommended_review_action","source"):
    assert key in exp, key
codes = {r["code"] for r in exp["computed_risks"]}
assert "unusual_payment_terms" in codes, codes
assert exp["known_facts"]["payment_terms_days"] == 180
print(json.dumps({"codes": sorted(codes), "action": exp["recommended_review_action"]}))
"""
    )
    print("explain_contract_risk OK", out)


def test_contract_repository_abstraction() -> None:
    out = _run_mcp_snippet(
        r"""
import server  # activates offline interceptor before repository SQL access
from contract_repository import FabricContractRepository, get_contract_repository
repo = get_contract_repository()
assert isinstance(repo, FabricContractRepository)
all_rows = repo.list_all(max_rows=200)
assert len(all_rows) >= 100
one = repo.get_by_id("CON-0002")
assert one and one.get("ContractID") == "CON-0002"
vendor_rows = repo.get_by_vendor("Microsoft")
assert len(vendor_rows) >= 3
searched = repo.search({"vendor":"Microsoft","status":"Active"})
assert searched
print("repository_ok", len(all_rows), one["ContractID"], len(vendor_rows))
"""
    )
    print("ContractRepository OK", out)


if __name__ == "__main__":
    test_invoice_guardrail_hard_match()
    test_search_contracts_microsoft()
    test_get_contract_profile_con0002()
    test_compare_contracts_any_ids_and_nway()
    test_offline_router_compare_routing()
    test_oracle_vendor_not_blocked()
    test_persona_memory_recall_routing()
    test_find_overlaps_tool_and_routing()
    test_explain_contract_risk_tool_and_routing()
    test_contract_repository_abstraction()
    print("all POC guard checks passed")
