"""Load shared runtime configuration from the workspace root `.env` only."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_ROOT_ENV = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ROOT_ENV, override=False)


def require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name} (set in root .env)")
    return value


def get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip() or default
