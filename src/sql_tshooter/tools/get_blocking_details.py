"""Implementation of the get_blocking_details tool."""

from __future__ import annotations

from typing import Any

import mcp.types as types

from sql_tshooter.db import DatabaseClient


TOOL_NAME = "get_blocking_details"
QUERY_TEXT_MAX_LENGTH = 220

QUERY = """
SELECT TOP (10)
    CAST(er.blocking_session_id AS int) AS blocking_session_id,
    CAST(er.session_id AS int) AS blocked_session_id,
    CAST(er.wait_type AS nvarchar(120)) AS wait_type,
    CAST(er.wait_time / 1000.0 AS float) AS wait_seconds,
    CAST(DB_NAME(er.database_id) AS nvarchar(128)) AS database_name,
    CAST(bs.host_name AS nvarchar(128)) AS blocker_host_name,
    CAST(bs.login_name AS nvarchar(128)) AS blocker_login_name,
    CAST(bs.program_name AS nvarchar(256)) AS blocker_program_name,
    CAST(ws.host_name AS nvarchar(128)) AS blocked_host_name,
    CAST(ws.login_name AS nvarchar(128)) AS blocked_login_name,
    CAST(ws.program_name AS nvarchar(256)) AS blocked_program_name,
    CAST(wt.resource_description AS nvarchar(512)) AS resource_description,
    CAST(bl.request_mode AS nvarchar(60)) AS lock_mode,
    CAST(blocker_text.text AS nvarchar(max)) AS blocker_query_text,
    CAST(blocked_text.text AS nvarchar(max)) AS blocked_query_text
FROM sys.dm_exec_requests AS er
JOIN sys.dm_exec_sessions AS ws
    ON er.session_id = ws.session_id
LEFT JOIN sys.dm_exec_sessions AS bs
    ON er.blocking_session_id = bs.session_id
LEFT JOIN sys.dm_os_waiting_tasks AS wt
    ON er.session_id = wt.session_id
LEFT JOIN sys.dm_tran_locks AS bl
    ON er.session_id = bl.request_session_id
   AND bl.request_status = 'WAIT'
OUTER APPLY sys.dm_exec_sql_text(er.sql_handle) AS blocked_text
OUTER APPLY (
    SELECT TOP (1) r2.sql_handle
    FROM sys.dm_exec_requests AS r2
    WHERE r2.session_id = er.blocking_session_id
) AS blocker_handle
OUTER APPLY sys.dm_exec_sql_text(blocker_handle.sql_handle) AS blocker_text
WHERE er.blocking_session_id > 0
  AND ws.is_user_process = 1
ORDER BY er.wait_time DESC, er.session_id ASC;
""".strip()


def build_tool() -> types.Tool:
    return types.Tool(
        name=TOOL_NAME,
        description="Return detailed active blocking chains with session and SQL text context.",
        inputSchema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        outputSchema={
            "type": "object",
            "properties": {
                "blocking_details": {
                    "type": "array",
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "properties": {
                            "blocking_session_id": {"type": "integer"},
                            "blocked_session_id": {"type": "integer"},
                            "database_name": {"type": "string"},
                            "wait_type": {"type": "string"},
                            "duration_seconds": {"type": "number"},
                            "resource_description": {"type": "string"},
                            "lock_mode": {"type": "string"},
                            "blocker_host_name": {"type": "string"},
                            "blocker_login_name": {"type": "string"},
                            "blocker_program_name": {"type": "string"},
                            "blocked_host_name": {"type": "string"},
                            "blocked_login_name": {"type": "string"},
                            "blocked_program_name": {"type": "string"},
                            "blocker_query_text": {"type": "string"},
                            "blocked_query_text": {"type": "string"},
                        },
                        "required": [
                            "blocking_session_id",
                            "blocked_session_id",
                            "database_name",
                            "wait_type",
                            "duration_seconds",
                            "resource_description",
                            "lock_mode",
                            "blocker_host_name",
                            "blocker_login_name",
                            "blocker_program_name",
                            "blocked_host_name",
                            "blocked_login_name",
                            "blocked_program_name",
                            "blocker_query_text",
                            "blocked_query_text",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["blocking_details"],
            "additionalProperties": False,
        },
    )


async def execute(db_client: DatabaseClient) -> dict[str, Any]:
    rows = await db_client.fetch_all(QUERY)
    details = [
        _normalize_blocking_detail_row(row)
        for row in rows
        if int(row["blocking_session_id"]) > 0
    ]
    details.sort(
        key=lambda row: (-row["duration_seconds"], row["blocked_session_id"])
    )
    return {"blocking_details": details[:10]}


def _normalize_blocking_detail_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "blocking_session_id": int(row["blocking_session_id"]),
        "blocked_session_id": int(row["blocked_session_id"]),
        "database_name": str(row["database_name"] or "unknown"),
        "wait_type": str(row["wait_type"] or "UNKNOWN"),
        "duration_seconds": round(max(float(row["wait_seconds"]), 0.0), 2),
        "resource_description": str(row["resource_description"] or ""),
        "lock_mode": str(row["lock_mode"] or ""),
        "blocker_host_name": str(row["blocker_host_name"] or ""),
        "blocker_login_name": str(row["blocker_login_name"] or ""),
        "blocker_program_name": str(row["blocker_program_name"] or ""),
        "blocked_host_name": str(row["blocked_host_name"] or ""),
        "blocked_login_name": str(row["blocked_login_name"] or ""),
        "blocked_program_name": str(row["blocked_program_name"] or ""),
        "blocker_query_text": _truncate_query_text(row["blocker_query_text"]),
        "blocked_query_text": _truncate_query_text(row["blocked_query_text"]),
    }


def _truncate_query_text(value: Any) -> str:
    normalized_text = " ".join(str(value or "").split())
    if len(normalized_text) > QUERY_TEXT_MAX_LENGTH:
        return normalized_text[: QUERY_TEXT_MAX_LENGTH - 3].rstrip() + "..."
    return normalized_text
