"""Implementation of the get_query_memory_grants tool."""

from __future__ import annotations

from typing import Any

import mcp.types as types

from sql_tshooter.db import DatabaseClient
from sql_tshooter.tools.common import collected_at_utc, truncate_text


TOOL_NAME = "get_query_memory_grants"
QUERY_TEXT_MAX_LENGTH = 240
MIN_REQUESTED_MEMORY_MB = 8.0

QUERY = """
SELECT TOP (20)
    CAST(mg.session_id AS int) AS session_id,
    CAST(mg.requested_memory_kb / 1024.0 AS float) AS requested_memory_mb,
    CAST(mg.granted_memory_kb / 1024.0 AS float) AS granted_memory_mb,
    CAST(COALESCE(mg.max_used_memory_kb, mg.granted_memory_kb) / 1024.0 AS float) AS used_memory_mb,
    CAST(mg.wait_time_ms AS bigint) AS wait_time_ms,
    CAST(
        CASE
            WHEN mg.grant_time IS NULL THEN 'waiting'
            ELSE 'granted'
        END AS nvarchar(40)
    ) AS grant_status,
    CAST(st.text AS nvarchar(max)) AS query_text
FROM sys.dm_exec_query_memory_grants AS mg
LEFT JOIN sys.dm_exec_requests AS er
    ON mg.session_id = er.session_id
OUTER APPLY sys.dm_exec_sql_text(COALESCE(er.sql_handle, mg.sql_handle)) AS st
WHERE mg.requested_memory_kb >= 8192
ORDER BY
    mg.granted_memory_kb DESC,
    mg.requested_memory_kb DESC,
    mg.wait_time_ms DESC,
    mg.session_id ASC;
""".strip()


def build_tool() -> types.Tool:
    return types.Tool(
        name=TOOL_NAME,
        description="Return active SQL Server memory grants with top consumers and waiters.",
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
                "memory_grants": {
                    "type": "array",
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "properties": {
                            "session_id": {"type": "integer"},
                            "requested_memory_mb": {"type": "number"},
                            "granted_memory_mb": {"type": "number"},
                            "used_memory_mb": {"type": "number"},
                            "wait_time_ms": {"type": "integer"},
                            "grant_status": {"type": "string"},
                            "truncated_query_text": {"type": "string"},
                        },
                        "required": [
                            "session_id",
                            "requested_memory_mb",
                            "granted_memory_mb",
                            "used_memory_mb",
                            "wait_time_ms",
                            "grant_status",
                            "truncated_query_text",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["collected_at_utc", "interpretation_hint", "memory_grants"],
            "additionalProperties": False,
        },
    )


async def execute(db_client: DatabaseClient) -> dict[str, Any]:
    rows = await db_client.fetch_all(QUERY)
    memory_grants = [
        _normalize_memory_grant_row(row)
        for row in rows
        if float(row["requested_memory_mb"]) >= MIN_REQUESTED_MEMORY_MB
    ]
    memory_grants.sort(
        key=lambda row: (
            -row["granted_memory_mb"],
            -row["requested_memory_mb"],
            -row["wait_time_ms"],
            row["session_id"],
        )
    )
    return {
        "collected_at_utc": collected_at_utc(),
        "interpretation_hint": (
            "Large waiting or under-granted memory requests can indicate memory grant pressure."
        ),
        "memory_grants": memory_grants[:10],
    }


def _normalize_memory_grant_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": int(row["session_id"]),
        "requested_memory_mb": round(max(float(row["requested_memory_mb"]), 0.0), 2),
        "granted_memory_mb": round(max(float(row["granted_memory_mb"]), 0.0), 2),
        "used_memory_mb": round(max(float(row["used_memory_mb"]), 0.0), 2),
        "wait_time_ms": max(int(row["wait_time_ms"]), 0),
        "grant_status": str(row["grant_status"] or "unknown"),
        "truncated_query_text": truncate_text(row["query_text"], QUERY_TEXT_MAX_LENGTH),
    }

