"""Implementation of the get_lock_summary tool."""

from __future__ import annotations

from typing import Any

import mcp.types as types

from sql_tshooter.db import DatabaseClient


TOOL_NAME = "get_lock_summary"

QUERY = """
SELECT TOP (10)
    CAST(tl.request_session_id AS int) AS session_id,
    CAST(DB_NAME(tl.resource_database_id) AS nvarchar(128)) AS database_name,
    CAST(tl.resource_type AS nvarchar(60)) AS resource_type,
    CAST(tl.request_mode AS nvarchar(60)) AS request_mode,
    CAST(COUNT_BIG(*) AS bigint) AS lock_count,
    CAST(MAX(es.host_name) AS nvarchar(128)) AS host_name,
    CAST(MAX(es.login_name) AS nvarchar(128)) AS login_name,
    CAST(MAX(es.program_name) AS nvarchar(256)) AS program_name
FROM sys.dm_tran_locks AS tl
LEFT JOIN sys.dm_exec_sessions AS es
    ON tl.request_session_id = es.session_id
WHERE tl.request_session_id > 0
GROUP BY
    tl.request_session_id,
    tl.resource_database_id,
    tl.resource_type,
    tl.request_mode
ORDER BY COUNT_BIG(*) DESC, tl.request_session_id ASC;
""".strip()


def build_tool() -> types.Tool:
    return types.Tool(
        name=TOOL_NAME,
        description="Return the top SQL Server lock aggregates by session, database, resource, and mode.",
        inputSchema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        outputSchema={
            "type": "object",
            "properties": {
                "lock_summary": {
                    "type": "array",
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "properties": {
                            "session_id": {"type": "integer"},
                            "database_name": {"type": "string"},
                            "resource_type": {"type": "string"},
                            "request_mode": {"type": "string"},
                            "lock_count": {"type": "integer"},
                            "host_name": {"type": "string"},
                            "login_name": {"type": "string"},
                            "program_name": {"type": "string"},
                        },
                        "required": [
                            "session_id",
                            "database_name",
                            "resource_type",
                            "request_mode",
                            "lock_count",
                            "host_name",
                            "login_name",
                            "program_name",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["lock_summary"],
            "additionalProperties": False,
        },
    )


async def execute(db_client: DatabaseClient) -> dict[str, Any]:
    rows = await db_client.fetch_all(QUERY)
    locks = [_normalize_lock_row(row) for row in rows]
    locks.sort(key=lambda row: (-row["lock_count"], row["session_id"]))
    return {"lock_summary": locks[:10]}


def _normalize_lock_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": int(row["session_id"]),
        "database_name": str(row["database_name"] or "unknown"),
        "resource_type": str(row["resource_type"] or "UNKNOWN"),
        "request_mode": str(row["request_mode"] or "UNKNOWN"),
        "lock_count": max(int(row["lock_count"]), 0),
        "host_name": str(row["host_name"] or ""),
        "login_name": str(row["login_name"] or ""),
        "program_name": str(row["program_name"] or ""),
    }
