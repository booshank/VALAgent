"""Offline staging checks for the mcp_server mock interceptor."""

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
assert any("Gold_Vendor_Contracts".lower() in c.lower() or True for c in expiring["columns"])

spend = json.loads(server.get_vendor_spend_summary(max_rows=50))
assert spend["row_count"] > 0, spend
assert "SupplierName" in spend["columns"]

search = json.loads(server.search_cloud_blob_contracts("Microsoft", top=3))
assert search["query_type"] == "semantic"
assert search["count"] > 0
assert search["documents"]

health = json.loads(server.fabric_health_check())
assert health["status"] == "ok", health

print("offline interceptor OK")
print(f"  expiring_rows={expiring['row_count']}")
print(f"  spend_rows={spend['row_count']}")
print(f"  search_docs={search['count']}")
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
        "def get_vendor_spend_summary",
        "def search_cloud_blob_contracts",
    ]
    for marker in tool_markers:
        start = source.index(marker)
        # Slice until next top-level @mcp.tool or end helpers
        rest = source[start:]
        next_def = rest.find("\n@mcp.tool")
        body = rest if next_def < 0 else rest[:next_def]
        assert "USE_OFFLINE_MOCKS" not in body, f"{marker} contains mock conditional"
        assert "test_fixtures" not in body, f"{marker} references fixtures directly"
    print("production tools are mock-free")


if __name__ == "__main__":
    test_production_tools_have_no_mock_branches()
    test_offline_interceptor_roundtrip()
