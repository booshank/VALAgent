"""
Dual MCP stdio clients:

  Client A — local Data Retrieval Agent (`mcp_server/server.py`)
  Client B — external `mcp-server-pgvector` via `uvx`
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from config import get

logger = logging.getLogger(__name__)

_WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
_MCP_SERVER_DIR = _WORKSPACE_ROOT / "mcp_server"
_MCP_SERVER_SCRIPT = _MCP_SERVER_DIR / "server.py"
_MCP_SERVER_VENV_PYTHON = _MCP_SERVER_DIR / ".venv" / "bin" / "python"


def _fabric_python() -> str:
    """Prefer the mcp_server virtualenv so Fabric/Search deps resolve correctly."""
    if _MCP_SERVER_VENV_PYTHON.is_file():
        return str(_MCP_SERVER_VENV_PYTHON)
    return sys.executable


def _resolve_uvx() -> str | None:
    """Return an absolute uvx path, or None if it is not installed."""
    found = shutil.which("uvx")
    if found:
        return found
    candidate = Path.home() / ".local" / "bin" / "uvx"
    if candidate.is_file():
        return str(candidate)
    return None


def _build_server_config(*, include_pgvector: bool = True) -> dict[str, dict[str, Any]]:
    python_exe = _fabric_python()
    fabric_env = {
        **os.environ,
        # Ensure child process resolves packages relative to mcp_server when needed.
        "PYTHONPATH": str(_MCP_SERVER_DIR)
        + os.pathsep
        + os.environ.get("PYTHONPATH", ""),
        # Guarantees uvx is visible to child processes spawned by MCP adapters.
        "PATH": str(Path.home() / ".local" / "bin")
        + os.pathsep
        + os.environ.get("PATH", ""),
    }

    config: dict[str, dict[str, Any]] = {
        "fabric_data": {
            "transport": "stdio",
            "command": python_exe,
            "args": [str(_MCP_SERVER_SCRIPT)],
            "env": fabric_env,
            "cwd": str(_MCP_SERVER_DIR),
        },
    }

    if not include_pgvector:
        return config

    uvx = _resolve_uvx()
    if not uvx:
        logger.warning(
            "uvx not found on PATH; skipping pgvector MCP client. "
            "Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"
        )
        return config

    pg_url = get("PGVECTOR_DATABASE_URL")
    pg_collection = get("PGVECTOR_COLLECTION", "val_operational_memory")

    # Client B: spawn mcp-server-pgvector dynamically with uvx.
    pgvector_args = ["mcp-server-pgvector"]
    if pg_collection:
        pgvector_args.extend(["--collection", pg_collection])

    config["pgvector"] = {
        "transport": "stdio",
        "command": uvx,
        "args": pgvector_args,
        "env": {
            **fabric_env,
            "DATABASE_URL": pg_url,
            "PGVECTOR_DATABASE_URL": pg_url,
        },
    }
    return config


class DualMCPBridge:
    """Maintains two concurrent asynchronous MCP connection lines."""

    def __init__(self) -> None:
        self._client: MultiServerMCPClient | None = None
        self._tools: list[BaseTool] | None = None

    async def start(self) -> list[BaseTool]:
        if self._tools is not None:
            return self._tools

        # Prefer both clients; fall back to Fabric-only if pgvector/uvx fails.
        for include_pgvector in (True, False):
            config = _build_server_config(include_pgvector=include_pgvector)
            if include_pgvector and "pgvector" not in config:
                continue
            try:
                logger.info(
                    "Starting MCP clients: fabric_data=%s pgvector=%s",
                    _MCP_SERVER_SCRIPT,
                    "enabled" if "pgvector" in config else "disabled",
                )
                self._client = MultiServerMCPClient(config)
                self._tools = await self._client.get_tools()
                logger.info("Loaded %d MCP tools across servers", len(self._tools))
                return self._tools
            except Exception:
                logger.exception(
                    "Failed starting MCP clients (pgvector=%s); "
                    "retrying without pgvector"
                    if include_pgvector
                    else "Fabric-only MCP start failed",
                    include_pgvector,
                )
                self._client = None
                self._tools = None
                if not include_pgvector:
                    raise

        raise RuntimeError("Unable to start any MCP clients")

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
