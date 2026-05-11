"""Implementation of the get_wait_stats_by_query tool."""

from __future__ import annotations

from typing import Any

import mcp.types as types

from sql_tshooter.db import DatabaseClient
from sql_tshooter.tools.common import collected_at_utc, truncate_text
from sql_tshooter.tools.top_waits import BENIGN_WAITS


TOOL_NAME = "get_wait_stats_by_query"
QUERY_TEXT_MAX_LENGTH = 220

QUERY = """
SELECT TOP (30)
    CAST(er.session_id AS int) AS session_id,
    CAST(er.wait_type AS nvarchar(120)) AS wait_type,
    CAST(er.wait_time AS bigint) AS wait_time_ms,
    CAST(er.cpu_time AS bigint) AS cpu_time_ms,
    CAST(er.logical_reads AS bigint) AS logical_reads,
    CAST(es.is_user_process AS bit) AS is_user_process,
    CAST(st.text AS nvarchar(max)) AS query_text
FROM sys.dm_exec_requests AS er
JOIN sys.dm_exec_sessions AS es
    ON er.session_id = es.session_id
OUTER APPLY sys.dm_exec_sql_text(er.sql_handle) AS st
WHERE er.session_id <> @@SPID
  AND es.is_user_process = 1
  AND er.wait_type IS NOT NULL
  AND er.wait_time > 0
ORDER BY er.wait_time DESC, er.cpu_time DESC, er.session_id ASC;
""".strip()


def build_tool() -> types.Tool:
    return types.Tool(
        name=TOOL_NAME,
        description="Correlate active waits to the queries currently experiencing them.",
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
                "waits_by_query": {
                    "type": "array",
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "properties": {
                            "session_id": {"type": "integer"},
                            "dominant_wait_type": {"type": "string"},
                            "total_wait_ms": {"type": "integer"},
                            "cpu_time_ms": {"type": "integer"},
                            "logical_reads": {"type": "integer"},
                            "truncated_query_text": {"type": "string"},
                        },
                        "required": [
                            "session_id",
                            "dominant_wait_type",
                            "total_wait_ms",
                            "cpu_time_ms",
                            "logical_reads",
                            "truncated_query_text",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["collected_at_utc", "interpretation_hint", "waits_by_query"],
            "additionalProperties": False,
        },
    )


async def execute(db_client: DatabaseClient) -> dict[str, Any]:
    rows = await db_client.fetch_all(QUERY)
    aggregated: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        wait_type = str(row["wait_type"] or "UNKNOWN").upper()
        if wait_type in BENIGN_WAITS:
            continue
        normalized_text = truncate_text(row["query_text"], QUERY_TEXT_MAX_LENGTH)
        if not normalized_text:
            continue
        key = (normalized_text, wait_type)
        if key not in aggregated:
            aggregated[key] = {
                "session_id": int(row["session_id"]),
                "dominant_wait_type": wait_type,
                "total_wait_ms": max(int(row["wait_time_ms"]), 0),
                "cpu_time_ms": max(int(row["cpu_time_ms"]), 0),
                "logical_reads": max(int(row["logical_reads"]), 0),
                "truncated_query_text": normalized_text,
            }
        else:
            aggregated[key]["total_wait_ms"] += max(int(row["wait_time_ms"]), 0)
            aggregated[key]["cpu_time_ms"] += max(int(row["cpu_time_ms"]), 0)
            aggregated[key]["logical_reads"] += max(int(row["logical_reads"]), 0)

    waits_by_query = list(aggregated.values())
    waits_by_query.sort(
        key=lambda row: (-row["total_wait_ms"], -row["cpu_time_ms"], row["session_id"])
    )
    return {
        "collected_at_utc": collected_at_utc(),
        "interpretation_hint": "Top active user-process waits can help link current pressure to specific statements.",
        "waits_by_query": waits_by_query[:10],
    }
