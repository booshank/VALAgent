#!/usr/bin/env python3
"""
Optional Azure AI Foundry provisioning for VAL CoPilot.

Current POC runtime does NOT require Foundry. The primary validated path is:
  Streamlit Validation UI → Flask cognitive router → FastMCP tools → synthetic Gold.

This script is the optional future host path: it loads root `.env`, authenticates
with DefaultAzureCredential, wraps MCP tool implementations in a Foundry ToolSet
(FunctionTool), and creates a managed agent using SYSTEM_PROMPT (lifecycle
procedures + invoice/spend OOS guardrail).

Required environment (root `.env`) — only when using this optional path:
  AZURE_FOUNDRY_CONNECTION_STRING
    Either a project endpoint URL, or a semicolon-delimited connection string
    containing an `endpoint=` (and optional subscriptionId / resourceGroupName /
    projectName) segment — the legacy Foundry project connection string form.
  AZURE_OPENAI_DEPLOYMENT_NAME (or AZURE_FOUNDRY_MODEL_DEPLOYMENT)
    Model deployment name used by the managed agent.

Optional:
  AZURE_FOUNDRY_AGENT_NAME  (default: val-copilot)

Usage:
  python deploy_to_foundry.py
  python deploy_to_foundry.py --dry-run   # validate ToolSet wiring only
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Callable

from azure.identity import DefaultAzureCredential

from config import get, require
from agent import SYSTEM_PROMPT

logger = logging.getLogger("deploy_to_foundry")

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MCP_SERVER_DIR = _REPO_ROOT / "mcp_server"

# ToolSet / FunctionTool live on the Agents SDK used by azure-ai-projects 1.x.
try:
    from azure.ai.agents.models import FunctionTool, ToolSet
except ImportError as exc:  # pragma: no cover - dependency pin surface
    raise SystemExit(
        "Missing azure-ai-agents ToolSet/FunctionTool. Install pinned deps:\n"
        "  pip install 'azure-ai-projects==1.0.0' 'azure-ai-agents>=1.0.0' "
        "'azure-identity>=1.19.0'\n"
        f"Original import error: {exc}"
    ) from exc

from azure.ai.projects import AIProjectClient


def _ensure_mcp_on_path() -> None:
    mcp_path = str(_MCP_SERVER_DIR)
    if mcp_path not in sys.path:
        sys.path.insert(0, mcp_path)


def load_fabric_tools() -> dict[str, Callable[..., Any]]:
    """Import MCP tool callables from mcp_server/server.py for the Foundry ToolSet.

    Includes the structured contract-intelligence surface used by the tool-layer
    POC (search/profile/renewals/spend rollup/overlaps/risk) plus blob search.
    """
    _ensure_mcp_on_path()
    # Import after path mutation so local modules (azure_search, contract_analytics)
    # resolve the same way the FastMCP process does.
    from server import (  # type: ignore[import-not-found]
        explain_contract_risk,
        find_overlaps,
        get_contract_profile,
        get_expiring_contracts,
        get_vendor_spend_summary,
        search_cloud_blob_contracts,
        search_contracts,
    )

    tools = {
        "search_contracts": search_contracts,
        "get_contract_profile": get_contract_profile,
        "get_expiring_contracts": get_expiring_contracts,
        "get_vendor_spend_summary": get_vendor_spend_summary,
        "find_overlaps": find_overlaps,
        "explain_contract_risk": explain_contract_risk,
        "search_cloud_blob_contracts": search_cloud_blob_contracts,
    }
    for name, fn in tools.items():
        if not callable(fn):
            raise TypeError(f"Expected callable MCP tool for {name}, got {type(fn)!r}")
    return tools


def parse_foundry_connection_string(conn_str: str) -> dict[str, str]:
    """
    Parse AZURE_FOUNDRY_CONNECTION_STRING into structured fields.

    Accepted forms:
      1) Bare project endpoint URL
         https://<account>.services.ai.azure.com/api/projects/<project>
      2) Semicolon-delimited key=value pairs (legacy Foundry connection string)
         endpoint=...;subscriptionId=...;resourceGroupName=...;projectName=...
    """
    raw = (conn_str or "").strip().strip('"').strip("'")
    if not raw:
        raise ValueError("AZURE_FOUNDRY_CONNECTION_STRING is empty")

    if raw.startswith("http://") or raw.startswith("https://"):
        if ";" not in raw:
            return {"endpoint": raw.rstrip("/")}
        # Rare: URL followed by additional segments without endpoint= key.
        endpoint, _, rest = raw.partition(";")
        parsed = {"endpoint": endpoint.rstrip("/")}
        for part in rest.split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            key, value = part.split("=", 1)
            parsed[key.strip()] = value.strip()
        return parsed

    parsed: dict[str, str] = {}
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        parsed[key.strip()] = value.strip()

    endpoint = parsed.get("endpoint") or parsed.get("Endpoint") or ""
    if not endpoint:
        raise ValueError(
            "AZURE_FOUNDRY_CONNECTION_STRING must include an endpoint URL "
            "(bare URL or endpoint=...;subscriptionId=...;...)"
        )
    parsed["endpoint"] = endpoint.rstrip("/")
    return parsed


def build_toolset(tools: dict[str, Callable[..., Any]]) -> ToolSet:
    """Wrap MCP tool implementations in an Azure AI Foundry FunctionTool ToolSet."""
    function_tool = FunctionTool(set(tools.values()))
    toolset = ToolSet()
    toolset.add(function_tool)
    return toolset


def build_project_client(endpoint: str, credential: DefaultAzureCredential) -> AIProjectClient:
    """
    Initialize AIProjectClient from the parsed Foundry endpoint.

    Prefer the classic from_connection_string factory when present (older SDKs);
    otherwise construct directly from the project endpoint + Entra credential.
    """
    factory = getattr(AIProjectClient, "from_connection_string", None)
    conn_str = require("AZURE_FOUNDRY_CONNECTION_STRING")
    if callable(factory):
        logger.info("Initializing AIProjectClient via from_connection_string")
        return factory(credential=credential, conn_str=conn_str)

    logger.info("Initializing AIProjectClient from project endpoint")
    return AIProjectClient(endpoint=endpoint, credential=credential)


def deploy_agent(
    *,
    dry_run: bool = False,
    agent_name: str | None = None,
) -> dict[str, Any]:
    """Create (or dry-run) the managed Foundry agent with ToolSet + SYSTEM_PROMPT."""
    conn_fields = parse_foundry_connection_string(require("AZURE_FOUNDRY_CONNECTION_STRING"))
    endpoint = conn_fields["endpoint"]
    model = (
        get("AZURE_FOUNDRY_MODEL_DEPLOYMENT")
        or get("AZURE_OPENAI_DEPLOYMENT_NAME")
        or ""
    ).strip()
    if not model:
        raise ValueError(
            "Set AZURE_FOUNDRY_MODEL_DEPLOYMENT or AZURE_OPENAI_DEPLOYMENT_NAME "
            "in the root .env"
        )
    name = (agent_name or get("AZURE_FOUNDRY_AGENT_NAME", "val-copilot")).strip()

    tools = load_fabric_tools()
    toolset = build_toolset(tools)
    definitions = list(toolset.definitions)

    summary: dict[str, Any] = {
        "endpoint": endpoint,
        "subscription_id": conn_fields.get("subscriptionId")
        or conn_fields.get("SubscriptionId"),
        "resource_group": conn_fields.get("resourceGroupName")
        or conn_fields.get("ResourceGroupName"),
        "project_name": conn_fields.get("projectName") or conn_fields.get("ProjectName"),
        "agent_name": name,
        "model": model,
        "tool_count": len(definitions),
        "tools": [item.get("function", {}).get("name") for item in definitions],
        "instructions_chars": len(SYSTEM_PROMPT),
        "dry_run": dry_run,
    }

    logger.info(
        "Prepared Foundry ToolSet with tools=%s (instructions=%s chars)",
        summary["tools"],
        summary["instructions_chars"],
    )

    if dry_run:
        summary["status"] = "dry_run"
        summary["message"] = (
            "ToolSet and SYSTEM_PROMPT validated locally; "
            "skipped AIProjectClient.create_agent"
        )
        return summary

    credential = DefaultAzureCredential()
    with credential:
        project_client = build_project_client(endpoint, credential)
        try:
            agent = project_client.agents.create_agent(
                model=model,
                name=name,
                description=(
                    "VAL CoPilot — enterprise vendor / contract cognitive routing agent "
                    "with Fabric SQL + Azure AI Search tools and lifecycle procedures "
                    "(compliance audits, counter-clauses, exposure, renewals)."
                ),
                instructions=SYSTEM_PROMPT,
                toolset=toolset,
                temperature=0.1,
                metadata={
                    "product": "VAL CoPilot",
                    "source": "copilot_agent/deploy_to_foundry.py",
                    "routing": "fabric_sql+azure_ai_search",
                },
            )
        finally:
            close = getattr(project_client, "close", None)
            if callable(close):
                close()

    summary["status"] = "created"
    summary["agent_id"] = getattr(agent, "id", None)
    summary["agent_name_remote"] = getattr(agent, "name", name)
    summary["model_remote"] = getattr(agent, "model", model)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deploy VAL CoPilot LangChain routing agent to Azure AI Foundry"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate connection-string parsing and ToolSet wiring without provisioning",
    )
    parser.add_argument(
        "--agent-name",
        default=None,
        help="Override AZURE_FOUNDRY_AGENT_NAME (default: val-copilot)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        result = deploy_agent(dry_run=args.dry_run, agent_name=args.agent_name)
    except Exception as exc:  # noqa: BLE001 — CLI surface
        logger.error("Foundry deployment failed: %s", exc)
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2))
        return 1

    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
