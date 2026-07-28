"""
Dual MCP stdio clients:

  Client A — local Data Retrieval Agent (`mcp_server/server.py`)
  Client B — external `mcp-server-pgvector` via `uvx`
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from config import get

logger = logging.getLogger(__name__)

_WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
_MCP_SERVER_SCRIPT = _WORKSPACE_ROOT / "mcp_server" / "server.py"


def _build_server_config() -> dict[str, dict[str, Any]]:
    python_exe = sys.executable
    fabric_env = {
        **os.environ,
        # Ensure child process resolves packages relative to mcp_server when needed.
        "PYTHONPATH": str(_WORKSPACE_ROOT / "mcp_server")
        + os.pathsep
        + os.environ.get("PYTHONPATH", ""),
    }

    pg_url = get("PGVECTOR_DATABASE_URL")
    pg_collection = get("PGVECTOR_COLLECTION", "val_operational_memory")

    # Client B: spawn mcp-server-pgvector dynamically with uvx.
    # Common entrypoints accept DATABASE_URL via env; collection via args when supported.
    pgvector_args = ["mcp-server-pgvector"]
    if pg_collection:
        pgvector_args.extend(["--collection", pg_collection])

    return {
        "fabric_data": {
            "transport": "stdio",
            "command": python_exe,
            "args": [str(_MCP_SERVER_SCRIPT)],
            "env": fabric_env,
            "cwd": str(_WORKSPACE_ROOT / "mcp_server"),
        },
        "pgvector": {
            "transport": "stdio",
            "command": "uvx",
            "args": pgvector_args,
            "env": {
                **os.environ,
                "DATABASE_URL": pg_url,
                "PGVECTOR_DATABASE_URL": pg_url,
            },
        },
    }


class DualMCPBridge:
    """Maintains two concurrent asynchronous MCP connection lines."""

    def __init__(self) -> None:
        self._client: MultiServerMCPClient | None = None
        self._tools: list[BaseTool] | None = None

    async def start(self) -> list[BaseTool]:
        if self._tools is not None:
            return self._tools

        config = _build_server_config()
        logger.info(
            "Starting dual MCP clients: fabric_data=%s pgvector=uvx mcp-server-pgvector",
            _MCP_SERVER_SCRIPT,
        )
        self._client = MultiServerMCPClient(config)
        self._tools = await self._client.get_tools()
        logger.info("Loaded %d MCP tools across both servers", len(self._tools))
        return self._tools

    async def get_tools(self) -> list[BaseTool]:
        return await self.start()

    async def aclose(self) -> None:
        self._tools = None
        client = self._client
        self._client = None
        if client is None:
            return
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close is None:
            return
        result = close()
        if hasattr(result, "__await__"):
            await result  # type: ignore[misc]


bridge = DualMCPBridge()
