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

# Missing contract(s): no default compare — not-available only
missing_one = json.loads(
    server.compare_contracts(contract_refs="CON-0001,CON-9999")
)
assert missing_one.get("error") == "contract_not_present", missing_one
assert "no such contract is available" in missing_one.get("message", "").lower()
assert "contracts" not in missing_one or not missing_one.get("contracts")
assert "CON-9999" in missing_one.get("message", "")
assert "defaulting" not in missing_one.get("message", "").lower()
assert "CON-0002" not in missing_one.get("message", "")

missing_both = json.loads(
    server.compare_contracts(contract_refs="CON-9998,CON-9999")
)
assert missing_both.get("error") == "contract_not_present", missing_both
assert "difference_count" not in missing_both

missing_suppliers = json.loads(
    server.compare_contracts(supplier_names="IBM,Salesforce")
)
assert missing_suppliers.get("error") == "contract_not_present", missing_suppliers
assert "no such contract is available" in missing_suppliers.get("message", "").lower()
assert "defaulting" not in missing_suppliers.get("message", "").lower()
assert "CON-0001" not in missing_suppliers.get("message", "")

missing_search = json.loads(server.search_contracts(vendor="IBM", max_rows=10))
assert missing_search.get("error") == "contract_not_present", missing_search
assert "no such contract is available" in missing_search.get("message", "").lower()

missing_profile = json.loads(server.get_contract_profile("CON-9999"))
assert missing_profile.get("error") == "contract_not_present", missing_profile
assert "no such contract is available" in missing_profile.get("message", "").lower()

print(json.dumps({
    "pair": [pair.get("left_contract_id"), pair.get("right_contract_id")],
    "nway": sorted(ids),
    "expanded": [row.get("ContractID") for row in expanded["contracts"]],
    "missing_message": missing_one.get("message"),
    "missing_suppliers": missing_suppliers.get("message"),
}))
"""
    )
    print("compare_contracts any/n-way OK", out)


def test_offline_router_missing_contract_no_default_compare() -> None:
    import asyncio

    from offline_router import _summarize_compare_payload, run_offline_turn

    payload = {
        "error": "contract_not_present",
        "message": "No such contract is available for CON-9999.",
        "missing": ["CON-9999"],
    }
    summary = _summarize_compare_payload(json.dumps(payload))
    assert summary == "No such contract is available for CON-9999."

    async def _run() -> str:
        return await run_offline_turn("Compare CON-0001 and CON-9999")

    reply = asyncio.run(_run())
    assert "No such contract is available" in reply
    assert "CON-9999" in reply
    assert "2-way" not in reply
    assert "Field matrix" not in reply
    assert "defaulting" not in reply.lower()
    assert "CON-0001 vs CON-0002" not in reply
    # Alone — no offline preamble wrapping the not-available message.
    assert reply.strip().startswith("No such contract is available")
    print("missing contract no-default OK", reply.strip())

    async def _run_suppliers() -> str:
        return await run_offline_turn("Compare IBM and Salesforce contracts")

    supplier_reply = asyncio.run(_run_suppliers())
    assert "No such contract is available" in supplier_reply
    assert "defaulting" not in supplier_reply.lower()
    assert "CON-0001 vs CON-0002" not in supplier_reply
    assert "Field matrix" not in supplier_reply
    assert supplier_reply.strip().startswith("No such contract is available")
    print("missing supplier compare OK", supplier_reply.strip())

    async def _run_profile() -> str:
        return await run_offline_turn("Show details for CON-9999")

    profile_reply = asyncio.run(_run_profile())
    assert "No such contract is available" in profile_reply
    assert "CON-9999" in profile_reply
    print("missing profile OK", profile_reply.strip())

    async def _run_search() -> str:
        return await run_offline_turn("Show contracts for IBM")

    search_reply = asyncio.run(_run_search())
    assert "No such contract is available" in search_reply
    assert "IBM" in search_reply
    print("missing vendor search OK", search_reply.strip())

    async def _run_mixed() -> str:
        return await run_offline_turn("Compare Microsoft and AcmeCorp")

    mixed_reply = asyncio.run(_run_mixed())
    assert "No such contract is available" in mixed_reply
    assert "defaulting" not in mixed_reply.lower()
    assert "CON-0001 vs CON-0002" not in mixed_reply
    assert "Field matrix" not in mixed_reply
    assert "2-way" not in mixed_reply
    print("mixed known/unknown supplier compare OK", mixed_reply.strip())


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

    # Known vendor + unknown vendor must NOT collapse into Microsoft expansion
    # (that previously produced an implicit CON-0001 vs CON-0002 style compare).
    q4 = "Compare Microsoft and AcmeCorp"
    kwargs4 = _build_compare_kwargs_from_text(
        q4,
        contract_ids=[],
        suppliers=_extract_suppliers(q4),
        contract_names=[],
        contract_types=[],
        annual_costs=[],
    )
    assert kwargs4.get("expand_matches") in (None, False)
    names4 = [n.strip() for n in str(kwargs4.get("supplier_names") or "").split(",") if n.strip()]
    assert "Microsoft" in names4
    assert any(n.lower() == "acmecorp" for n in names4), kwargs4

    q5 = "Compare FooVendor and BarVendor contracts"
    kwargs5 = _build_compare_kwargs_from_text(
        q5,
        contract_ids=[],
        suppliers=_extract_suppliers(q5),
        contract_names=[],
        contract_types=[],
        annual_costs=[],
    )
    assert kwargs5.get("expand_matches") in (None, False)
    names5 = [n.strip() for n in str(kwargs5.get("supplier_names") or "").split(",") if n.strip()]
    assert len(names5) >= 2, kwargs5
    print("offline compare routing OK", kwargs, kwargs2, kwargs3, kwargs4, kwargs5)


def test_sanitize_default_compare_hallucination() -> None:
    from offline_router import sanitize_default_compare_hallucination

    legacy = (
        "No two resolvable compare sides detected; "
        "defaulting comparison to CON-0001 vs CON-0002."
    )
    cleaned = sanitize_default_compare_hallucination(
        legacy,
        user_text="Compare IBM and Salesforce",
    )
    assert "defaulting" not in cleaned.lower()
    assert "No such contract is available" in cleaned
    assert "IBM" in cleaned and "Salesforce" in cleaned
    print("sanitize default compare OK", cleaned)


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
    test_offline_router_missing_contract_no_default_compare()
    test_offline_router_compare_routing()
    test_sanitize_default_compare_hallucination()
    test_oracle_vendor_not_blocked()
    test_persona_memory_recall_routing()
    test_find_overlaps_tool_and_routing()
    test_explain_contract_risk_tool_and_routing()
    test_contract_repository_abstraction()
    print("all POC guard checks passed")
