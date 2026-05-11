"""Implementation of the get_blocking_sessions tool."""

from __future__ import annotations

from typing import Any

import mcp.types as types

from sql_tshooter.db import DatabaseClient


TOOL_NAME = "get_blocking_sessions"

QUERY = """
SELECT TOP (10)
    CAST(er.blocking_session_id AS int) AS blocking_session_id,
    CAST(er.session_id AS int) AS blocked_session_id,
    CAST(er.wait_time / 1000.0 AS float) AS duration_seconds,
    CAST(er.wait_type AS nvarchar(120)) AS wait_type,
    CAST(DB_NAME(er.database_id) AS nvarchar(128)) AS database_name
FROM sys.dm_exec_requests AS er
WHERE er.blocking_session_id > 0
ORDER BY er.wait_time DESC, er.session_id ASC;
""".strip()


def build_tool() -> types.Tool:
    return types.Tool(
        name=TOOL_NAME,
        description="Return the top active SQL Server blocking chains.",
        inputSchema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        outputSchema={
            "type": "object",
            "properties": {
                "blocking_sessions": {
                    "type": "array",
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "properties": {
                            "blocking_session_id": {"type": "integer"},
                            "blocked_session_id": {"type": "integer"},
                            "duration_seconds": {"type": "number"},
                            "wait_type": {"type": "string"},
                            "database_name": {"type": "string"},
                        },
                        "required": [
                            "blocking_session_id",
                            "blocked_session_id",
                            "duration_seconds",
                            "wait_type",
                            "database_name",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["blocking_sessions"],
            "additionalProperties": False,
        },
    )


async def execute(db_client: DatabaseClient) -> dict[str, Any]:
    rows = await db_client.fetch_all(QUERY)
    blocking_rows = [
        _normalize_blocking_row(row)
        for row in rows
        if int(row["blocking_session_id"]) > 0
    ]
    blocking_rows.sort(
        key=lambda row: (-row["duration_seconds"], row["blocked_session_id"])
    )
    return {"blocking_sessions": blocking_rows[:10]}


def _normalize_blocking_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "blocking_session_id": int(row["blocking_session_id"]),
        "blocked_session_id": int(row["blocked_session_id"]),
        "duration_seconds": round(max(float(row["duration_seconds"]), 0.0), 2),
        "wait_type": str(row["wait_type"] or "UNKNOWN"),
        "database_name": str(row["database_name"] or "unknown"),
    }
