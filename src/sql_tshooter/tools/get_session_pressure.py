"""Implementation of the get_session_pressure tool."""

from __future__ import annotations

from typing import Any

import mcp.types as types

from sql_tshooter.db import DatabaseClient
from sql_tshooter.tools.common import collected_at_utc, truncate_identifier, truncate_text


TOOL_NAME = "get_session_pressure"
QUERY_TEXT_MAX_LENGTH = 220
IDENTIFIER_MAX_LENGTH = 120
MIN_NOTABLE_IDLE_SECONDS = 60

QUERY = """
SELECT TOP (40)
    CAST(es.session_id AS int) AS session_id,
    CAST(es.status AS nvarchar(60)) AS status,
    CAST(es.login_name AS nvarchar(256)) AS login_name,
    CAST(es.host_name AS nvarchar(256)) AS host_name,
    CAST(es.program_name AS nvarchar(256)) AS program_name,
    CAST(DB_NAME(COALESCE(er.database_id, es.database_id)) AS nvarchar(128)) AS database_name,
    CAST(es.open_transaction_count AS int) AS open_transaction_count,
    CAST(
        DATEDIFF(
            SECOND,
            COALESCE(es.last_request_end_time, es.login_time, GETDATE()),
            GETDATE()
        ) AS int
    ) AS idle_seconds,
    CAST(er.status AS nvarchar(60)) AS request_status,
    CAST(ISNULL(er.blocking_session_id, 0) AS int) AS blocking_session_id,
    CAST(st.text AS nvarchar(max)) AS query_text
FROM sys.dm_exec_sessions AS es
LEFT JOIN sys.dm_exec_requests AS er
    ON es.session_id = er.session_id
OUTER APPLY sys.dm_exec_sql_text(er.sql_handle) AS st
WHERE es.session_id <> @@SPID
  AND es.is_user_process = 1
ORDER BY
    es.open_transaction_count DESC,
    DATEDIFF(SECOND, COALESCE(es.last_request_end_time, es.login_time, GETDATE()), GETDATE()) DESC,
    ISNULL(er.blocking_session_id, 0) DESC,
    es.session_id ASC;
""".strip()


def build_tool() -> types.Tool:
    return types.Tool(
        name=TOOL_NAME,
        description="Return the most notable user sessions for connection and transaction pressure triage.",
        inputSchema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        outputSchema={
            "type": "object",
            "properties": {
                "collected_at_utc": {"type": "string"},
                "interpretation_hint": {"type": "string"},
                "notable_sessions": {
                    "type": "array",
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "properties": {
                            "session_id": {"type": "integer"},
                            "status": {"type": "string"},
                            "login_name": {"type": "string"},
                            "host_name": {"type": "string"},
                            "program_name": {"type": "string"},
                            "database_name": {"type": "string"},
                            "open_transaction_count": {"type": "integer"},
                            "idle_seconds": {"type": "integer"},
                            "request_status": {"type": "string"},
                            "blocking_session_id": {"type": "integer"},
                            "truncated_query_text": {"type": "string"},
                        },
                        "required": [
                            "session_id",
                            "status",
                            "login_name",
                            "host_name",
                            "program_name",
                            "database_name",
                            "open_transaction_count",
                            "idle_seconds",
                            "request_status",
                            "blocking_session_id",
                            "truncated_query_text",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["collected_at_utc", "interpretation_hint", "notable_sessions"],
            "additionalProperties": False,
        },
    )


async def execute(db_client: DatabaseClient) -> dict[str, Any]:
    rows = await db_client.fetch_all(QUERY)
    notable_sessions = [_normalize_session_row(row) for row in rows if _is_notable(row)]
    notable_sessions.sort(
        key=lambda row: (
            -row["open_transaction_count"],
            -(1 if row["blocking_session_id"] > 0 else 0),
            -row["idle_seconds"],
            row["session_id"],
        )
    )
    return {
        "collected_at_utc": collected_at_utc(),
        "interpretation_hint": (
            "Long-idle sessions with open transactions or blockers are stronger pressure signals than short-lived sleepers."
        ),
        "notable_sessions": notable_sessions[:10],
    }


def _is_notable(row: dict[str, Any]) -> bool:
    open_transaction_count = max(int(row.get("open_transaction_count") or 0), 0)
    idle_seconds = max(int(row.get("idle_seconds") or 0), 0)
    blocking_session_id = max(int(row.get("blocking_session_id") or 0), 0)
    request_status = str(row.get("request_status") or "").strip().lower()
    status = str(row.get("status") or "").strip().lower()
    return (
        open_transaction_count > 0
        or blocking_session_id > 0
        or bool(request_status)
        or (status == "sleeping" and idle_seconds >= MIN_NOTABLE_IDLE_SECONDS)
    )


def _normalize_session_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": int(row["session_id"]),
        "status": str(row.get("status") or "unknown"),
        "login_name": truncate_identifier(row.get("login_name"), IDENTIFIER_MAX_LENGTH),
        "host_name": truncate_identifier(row.get("host_name"), IDENTIFIER_MAX_LENGTH),
        "program_name": truncate_identifier(row.get("program_name"), IDENTIFIER_MAX_LENGTH),
        "database_name": truncate_identifier(row.get("database_name"), IDENTIFIER_MAX_LENGTH),
        "open_transaction_count": max(int(row.get("open_transaction_count") or 0), 0),
        "idle_seconds": max(int(row.get("idle_seconds") or 0), 0),
        "request_status": str(row.get("request_status") or "idle"),
        "blocking_session_id": max(int(row.get("blocking_session_id") or 0), 0),
        "truncated_query_text": truncate_text(row.get("query_text"), QUERY_TEXT_MAX_LENGTH),
    }
