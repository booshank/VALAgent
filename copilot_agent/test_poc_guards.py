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


def test_search_contracts_alphatech() -> None:
    out = _run_mcp_snippet(
        r"""
import json, server
payload = json.loads(server.search_contracts(vendor="AlphaTech Services", max_rows=50))
assert payload["row_count"] >= 3, payload
ids = {row["contract_id"] for row in payload["rows"]}
assert {"C-1001", "C-1002", "C-1003"} <= ids
row = next(r for r in payload["rows"] if r["contract_id"] == "C-1001")
for key in (
    "contract_id","vendor_name","business_unit","status","effective_date",
    "expiration_date","annual_contract_value","payment_terms_days",
    "rate_card_on_file","source",
):
    assert key in row, key
print(json.dumps({"row_count": payload["row_count"], "ids": sorted(ids)}))
"""
    )
    print("search_contracts OK", out)


def test_get_contract_profile_c1001() -> None:
    out = _run_mcp_snippet(
        r"""
import json, server
payload = json.loads(server.get_contract_profile("C-1001"))
assert payload.get("error") is None, payload
profile = payload["profile"]
assert profile["contract_id"] == "C-1001"
assert profile["vendor_name"] == "AlphaTech Services"
assert "missing_fields" in profile
assert profile["payment_terms_days"] == 30
assert profile["rate_card_on_file"] is True
print(json.dumps({"contract_id": profile["contract_id"], "missing_fields": profile["missing_fields"]}))
"""
    )
    print("get_contract_profile OK", out)


def test_oracle_vendor_not_blocked() -> None:
    from offline_router import _choose_tools, is_invoice_out_of_scope

    q = "Show contracts for Oracle"
    assert not is_invoice_out_of_scope(q)
    tools = _choose_tools(q)
    assert "search_contracts" in tools
    assert "get_vendor_spend_summary" not in tools
    print("oracle vendor routing OK", tools)


if __name__ == "__main__":
    test_invoice_guardrail_hard_match()
    test_search_contracts_alphatech()
    test_get_contract_profile_c1001()
    test_oracle_vendor_not_blocked()
    print("all POC guard checks passed")
