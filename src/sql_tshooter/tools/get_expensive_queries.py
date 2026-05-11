"""Implementation of the get_expensive_queries tool."""

from __future__ import annotations

from typing import Any

import mcp.types as types

from sql_tshooter.db import DatabaseClient


TOOL_NAME = "get_expensive_queries"
QUERY_TEXT_MAX_LENGTH = 300

QUERY = """
SELECT TOP (10)
    CONVERT(varchar(18), qs.query_hash, 1) AS query_hash,
    CAST(qs.total_worker_time AS bigint) AS total_worker_time,
    CAST(qs.total_elapsed_time AS bigint) AS total_elapsed_time,
    CAST(qs.total_logical_reads AS bigint) AS total_logical_reads,
    CAST(qs.execution_count AS bigint) AS execution_count,
    CAST(st.text AS nvarchar(max)) AS query_text
FROM sys.dm_exec_query_stats AS qs
CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) AS st
ORDER BY
    (qs.total_worker_time * 1.0 / NULLIF(qs.execution_count, 0)) DESC,
    (qs.total_elapsed_time * 1.0 / NULLIF(qs.execution_count, 0)) DESC,
    qs.execution_count DESC;
""".strip()


def build_tool() -> types.Tool:
    return types.Tool(
        name=TOOL_NAME,
        description="Return the most expensive SQL Server queries by average resource usage.",
        inputSchema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        outputSchema={
            "type": "object",
            "properties": {
                "expensive_queries": {
                    "type": "array",
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "properties": {
                            "query_hash": {"type": "string"},
                            "avg_cpu_ms": {"type": "number"},
                            "avg_duration_ms": {"type": "number"},
                            "execution_count": {"type": "integer"},
                            "truncated_query_text": {"type": "string"},
                        },
                        "required": [
                            "query_hash",
                            "avg_cpu_ms",
                            "avg_duration_ms",
                            "execution_count",
                            "truncated_query_text",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["expensive_queries"],
            "additionalProperties": False,
        },
    )


async def execute(db_client: DatabaseClient) -> dict[str, Any]:
    rows = await db_client.fetch_all(QUERY)
    normalized_rows = [_normalize_query_row(row) for row in rows]
    normalized_rows.sort(
        key=lambda row: (
            -row["avg_cpu_ms"],
            -row["avg_duration_ms"],
            -row["execution_count"],
        )
    )
    return {"expensive_queries": normalized_rows[:10]}


def _normalize_query_row(row: dict[str, Any]) -> dict[str, Any]:
    execution_count = max(int(row["execution_count"]), 0)
    total_worker_time = max(float(row["total_worker_time"]), 0.0)
    total_elapsed_time = max(float(row["total_elapsed_time"]), 0.0)
    avg_cpu_ms = (total_worker_time / execution_count / 1000.0) if execution_count else 0.0
    avg_duration_ms = (
        total_elapsed_time / execution_count / 1000.0 if execution_count else 0.0
    )
    normalized_text = " ".join(str(row["query_text"] or "").split())
    if len(normalized_text) > QUERY_TEXT_MAX_LENGTH:
        normalized_text = normalized_text[: QUERY_TEXT_MAX_LENGTH - 3] + "..."
    return {
        "query_hash": str(row["query_hash"]),
        "avg_cpu_ms": round(avg_cpu_ms, 2),
        "avg_duration_ms": round(avg_duration_ms, 2),
        "execution_count": execution_count,
        "truncated_query_text": normalized_text,
    }
