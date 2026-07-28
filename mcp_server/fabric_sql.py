"""Microsoft Fabric SQL Gold Layer access via ODBC Driver 18 + ActiveDirectoryDefault."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pyodbc

from config import get, require


def _connection_string() -> str:
    server = require("FABRIC_SQL_SERVER")
    database = require("FABRIC_SQL_DATABASE")
    driver = get("FABRIC_SQL_DRIVER", "ODBC Driver 18 for SQL Server")
    # Authentication=ActiveDirectoryDefault is mandatory per architecture constraints.
    return (
        f"Driver={{{driver}}};"
        f"Server={server};"
        f"Database={database};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Authentication=ActiveDirectoryDefault;"
    )


def get_connection() -> pyodbc.Connection:
    """Open a pooled-friendly ODBC connection to Fabric SQL Gold."""
    return pyodbc.connect(_connection_string(), timeout=30)


def execute_query(sql: str, params: list[Any] | None = None, max_rows: int = 500) -> dict[str, Any]:
    """
    Execute a read-oriented SQL query against the Fabric Gold layer.

    Returns a JSON-serializable payload of columns + row dictionaries.
    """
    if not sql or not sql.strip():
        raise ValueError("SQL query must be a non-empty string")

    normalized = sql.lstrip().lower()
    blocked = ("insert ", "update ", "delete ", "drop ", "alter ", "truncate ", "merge ", "create ")
    if any(normalized.startswith(verb) for verb in blocked):
        raise ValueError("Only SELECT / read queries are permitted against the Gold layer")

    params = params or []
    with get_connection() as conn:
        df = pd.read_sql(sql, conn, params=params)
        if len(df) > max_rows:
            df = df.head(max_rows)
            truncated = True
        else:
            truncated = False

        records = df.where(pd.notnull(df), None).to_dict(orient="records")
        return {
            "columns": list(df.columns),
            "row_count": len(records),
            "truncated": truncated,
            "rows": records,
        }
