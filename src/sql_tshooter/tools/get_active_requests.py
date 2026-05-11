"""Implementation of the get_active_requests tool."""

from __future__ import annotations

from typing import Any

import mcp.types as types

from sql_tshooter.db import DatabaseClient


TOOL_NAME = "get_active_requests"
QUERY_TEXT_MAX_LENGTH = 300

QUERY = """
SELECT TOP (10)
    CAST(er.session_id AS int) AS session_id,
    CAST(er.blocking_session_id AS int) AS blocking_session_id,
    CAST(er.status AS nvarchar(60)) AS status,
    CAST(er.command AS nvarchar(60)) AS command,
    CAST(DB_NAME(er.database_id) AS nvarchar(128)) AS database_name,
    CAST(er.wait_type AS nvarchar(120)) AS wait_type,
    CAST(er.wait_time / 1000.0 AS float) AS wait_seconds,
    CAST(er.cpu_time AS bigint) AS cpu_time_ms,
    CAST(er.logical_reads AS bigint) AS logical_reads,
    CAST(er.total_elapsed_time / 1000.0 AS float) AS elapsed_seconds,
    CAST(es.host_name AS nvarchar(128)) AS host_name,
    CAST(es.login_name AS nvarchar(128)) AS login_name,
    CAST(es.program_name AS nvarchar(256)) AS program_name,
    CAST(st.text AS nvarchar(max)) AS query_text
FROM sys.dm_exec_requests AS er
JOIN sys.dm_exec_sessions AS es
    ON er.session_id = es.session_id
OUTER APPLY sys.dm_exec_sql_text(er.sql_handle) AS st
WHERE es.is_user_process = 1
  AND er.session_id <> @@SPID
ORDER BY er.total_elapsed_time DESC, er.cpu_time DESC, er.session_id ASC;
""".strip()


def build_tool() -> types.Tool:
    return types.Tool(
        name=TOOL_NAME,
        description="Return the top active SQL Server requests with wait and SQL text context.",
        inputSchema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        outputSchema={
            "type": "object",
            "properties": {
                "active_requests": {
                    "type": "array",
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "properties": {
                            "session_id": {"type": "integer"},
                            "blocking_session_id": {"type": "integer"},
                            "status": {"type": "string"},
                            "command": {"type": "string"},
                            "database_name": {"type": "string"},
                            "wait_type": {"type": "string"},
                            "duration_seconds": {"type": "number"},
                            "cpu_time_ms": {"type": "integer"},
                            "logical_reads": {"type": "integer"},
                            "host_name": {"type": "string"},
                            "login_name": {"type": "string"},
                            "program_name": {"type": "string"},
                            "truncated_query_text": {"type": "string"},
                        },
                        "required": [
                            "session_id",
                            "blocking_session_id",
                            "status",
                            "command",
                            "database_name",
                            "wait_type",
                            "duration_seconds",
                            "cpu_time_ms",
                            "logical_reads",
                            "host_name",
                            "login_name",
                            "program_name",
                            "truncated_query_text",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["active_requests"],
            "additionalProperties": False,
        },
    )


async def execute(db_client: DatabaseClient) -> dict[str, Any]:
    rows = await db_client.fetch_all(QUERY)
    requests = [_normalize_request_row(row) for row in rows]
    requests.sort(
        key=lambda row: (-row["duration_seconds"], -row["cpu_time_ms"], row["session_id"])
    )
    return {"active_requests": requests[:10]}


def _normalize_request_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": int(row["session_id"]),
        "blocking_session_id": max(int(row["blocking_session_id"] or 0), 0),
        "status": str(row["status"] or "unknown"),
        "command": str(row["command"] or "unknown"),
        "database_name": str(row["database_name"] or "unknown"),
        "wait_type": str(row["wait_type"] or "NONE"),
        "duration_seconds": round(max(float(row["elapsed_seconds"]), 0.0), 2),
        "cpu_time_ms": max(int(row["cpu_time_ms"]), 0),
        "logical_reads": max(int(row["logical_reads"]), 0),
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
