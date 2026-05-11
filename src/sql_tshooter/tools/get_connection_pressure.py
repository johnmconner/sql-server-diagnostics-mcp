"""Implementation of the get_connection_pressure tool."""

from __future__ import annotations

from collections import Counter
from typing import Any

import mcp.types as types

from sql_tshooter.db import DatabaseClient
from sql_tshooter.tools.common import collected_at_utc, truncate_identifier


TOOL_NAME = "get_connection_pressure"
NAME_MAX_LENGTH = 120
TOP_CONCENTRATIONS = 5

QUERY = """
SELECT
    CAST(es.session_id AS int) AS session_id,
    CAST(es.status AS nvarchar(60)) AS status,
    CAST(es.login_name AS nvarchar(256)) AS login_name,
    CAST(es.host_name AS nvarchar(256)) AS host_name,
    CAST(es.program_name AS nvarchar(256)) AS program_name,
    CAST(es.is_user_process AS bit) AS is_user_process
FROM sys.dm_exec_sessions AS es
LEFT JOIN sys.dm_exec_connections AS ec
    ON es.session_id = ec.session_id
WHERE es.session_id <> @@SPID
  AND es.is_user_process = 1;
""".strip()


def build_tool() -> types.Tool:
    return types.Tool(
        name=TOOL_NAME,
        description="Return a summarized view of current SQL Server connection pressure.",
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
                "total_user_sessions": {"type": "integer"},
                "active_user_sessions": {"type": "integer"},
                "sleeping_user_sessions": {"type": "integer"},
                "distinct_login_count": {"type": "integer"},
                "distinct_host_count": {"type": "integer"},
                "distinct_program_count": {"type": "integer"},
                "top_logins": _top_dimension_schema(),
                "top_hosts": _top_dimension_schema(),
                "top_programs": _top_dimension_schema(),
            },
            "required": [
                "collected_at_utc",
                "interpretation_hint",
                "total_user_sessions",
                "active_user_sessions",
                "sleeping_user_sessions",
                "distinct_login_count",
                "distinct_host_count",
                "distinct_program_count",
                "top_logins",
                "top_hosts",
                "top_programs",
            ],
            "additionalProperties": False,
        },
    )


async def execute(db_client: DatabaseClient) -> dict[str, Any]:
    rows = await db_client.fetch_all(QUERY)
    user_rows = [row for row in rows if bool(row.get("is_user_process", True))]
    active_rows = [row for row in user_rows if str(row.get("status") or "").lower() != "sleeping"]
    sleeping_rows = [row for row in user_rows if str(row.get("status") or "").lower() == "sleeping"]

    top_logins = _build_top_dimension(user_rows, "login_name")
    top_hosts = _build_top_dimension(user_rows, "host_name")
    top_programs = _build_top_dimension(user_rows, "program_name")

    interpretation_hint = "Connection activity looks broadly distributed."
    if top_programs and top_programs[0]["session_count"] >= max(5, len(user_rows) // 2):
        interpretation_hint = (
            "One client program accounts for a large share of sessions, which can indicate pooled-app buildup or leaked connections."
        )
    elif sleeping_rows and len(sleeping_rows) >= max(5, len(active_rows) * 2):
        interpretation_hint = (
            "Sleeping user sessions dominate the instance, which can indicate idle connection buildup rather than active SQL pressure."
        )

    return {
        "collected_at_utc": collected_at_utc(),
        "interpretation_hint": interpretation_hint,
        "total_user_sessions": len(user_rows),
        "active_user_sessions": len(active_rows),
        "sleeping_user_sessions": len(sleeping_rows),
        "distinct_login_count": _distinct_count(user_rows, "login_name"),
        "distinct_host_count": _distinct_count(user_rows, "host_name"),
        "distinct_program_count": _distinct_count(user_rows, "program_name"),
        "top_logins": top_logins,
        "top_hosts": top_hosts,
        "top_programs": top_programs,
    }


def _top_dimension_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "maxItems": TOP_CONCENTRATIONS,
        "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "session_count": {"type": "integer"},
            },
            "required": ["name", "session_count"],
            "additionalProperties": False,
        },
    }


def _build_top_dimension(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    counts = Counter(
        truncate_identifier(row.get(key), NAME_MAX_LENGTH)
        for row in rows
        if truncate_identifier(row.get(key), NAME_MAX_LENGTH) != "unknown"
    )
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))
    return [{"name": name, "session_count": count} for name, count in ranked[:TOP_CONCENTRATIONS]]


def _distinct_count(rows: list[dict[str, Any]], key: str) -> int:
    values = {
        truncate_identifier(row.get(key), NAME_MAX_LENGTH)
        for row in rows
        if truncate_identifier(row.get(key), NAME_MAX_LENGTH) != "unknown"
    }
    return len(values)
