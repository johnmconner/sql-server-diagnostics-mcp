"""Implementation of the get_waiting_tasks tool."""

from __future__ import annotations

from typing import Any

import mcp.types as types

from sql_tshooter.db import DatabaseClient
from sql_tshooter.tools.top_waits import BENIGN_WAITS


TOOL_NAME = "get_waiting_tasks"
QUERY_TEXT_MAX_LENGTH = 220

QUERY = """
SELECT TOP (20)
    CAST(wt.session_id AS int) AS session_id,
    CAST(ISNULL(wt.blocking_session_id, 0) AS int) AS blocking_session_id,
    CAST(wt.wait_type AS nvarchar(120)) AS wait_type,
    CAST(wt.wait_duration_ms / 1000.0 AS float) AS wait_seconds,
    CAST(wt.resource_description AS nvarchar(512)) AS resource_description,
    CAST(DB_NAME(er.database_id) AS nvarchar(128)) AS database_name,
    CAST(er.status AS nvarchar(60)) AS status,
    CAST(es.host_name AS nvarchar(128)) AS host_name,
    CAST(es.login_name AS nvarchar(128)) AS login_name,
    CAST(es.program_name AS nvarchar(256)) AS program_name,
    CAST(st.text AS nvarchar(max)) AS query_text
FROM sys.dm_os_waiting_tasks AS wt
LEFT JOIN sys.dm_exec_requests AS er
    ON wt.session_id = er.session_id
LEFT JOIN sys.dm_exec_sessions AS es
    ON wt.session_id = es.session_id
OUTER APPLY sys.dm_exec_sql_text(er.sql_handle) AS st
WHERE wt.session_id <> @@SPID
ORDER BY wt.wait_duration_ms DESC, wt.session_id ASC;
""".strip()


def build_tool() -> types.Tool:
    return types.Tool(
        name=TOOL_NAME,
        description="Return the top meaningful live waiting tasks with session and SQL text context.",
        inputSchema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        outputSchema={
            "type": "object",
            "properties": {
                "waiting_tasks": {
                    "type": "array",
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "properties": {
                            "session_id": {"type": "integer"},
                            "blocking_session_id": {"type": "integer"},
                            "database_name": {"type": "string"},
                            "wait_type": {"type": "string"},
                            "duration_seconds": {"type": "number"},
                            "resource_description": {"type": "string"},
                            "status": {"type": "string"},
                            "host_name": {"type": "string"},
                            "login_name": {"type": "string"},
                            "program_name": {"type": "string"},
                            "truncated_query_text": {"type": "string"},
                        },
                        "required": [
                            "session_id",
                            "blocking_session_id",
                            "database_name",
                            "wait_type",
                            "duration_seconds",
                            "resource_description",
                            "status",
                            "host_name",
                            "login_name",
                            "program_name",
                            "truncated_query_text",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["waiting_tasks"],
            "additionalProperties": False,
        },
    )


async def execute(db_client: DatabaseClient) -> dict[str, Any]:
    rows = await db_client.fetch_all(QUERY)
    waiting_tasks = [
        _normalize_waiting_task_row(row)
        for row in rows
        if str(row["wait_type"]).upper() not in BENIGN_WAITS
    ]
    waiting_tasks.sort(
        key=lambda row: (-row["duration_seconds"], row["session_id"])
    )
    return {"waiting_tasks": waiting_tasks[:10]}


def _normalize_waiting_task_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": int(row["session_id"]),
        "blocking_session_id": max(int(row["blocking_session_id"] or 0), 0),
        "database_name": str(row["database_name"] or "unknown"),
        "wait_type": str(row["wait_type"] or "UNKNOWN"),
        "duration_seconds": round(max(float(row["wait_seconds"]), 0.0), 2),
        "resource_description": str(row["resource_description"] or ""),
        "status": str(row["status"] or "unknown"),
        "host_name": str(row["host_name"] or ""),
        "login_name": str(row["login_name"] or ""),
        "program_name": str(row["program_name"] or ""),
        "truncated_query_text": _truncate_query_text(row["query_text"]),
    }


def _truncate_query_text(value: Any) -> str:
    normalized_text = " ".join(str(value or "").split())
    if len(normalized_text) > QUERY_TEXT_MAX_LENGTH:
        return normalized_text[: QUERY_TEXT_MAX_LENGTH - 3].rstrip() + "..."
    return normalized_text
