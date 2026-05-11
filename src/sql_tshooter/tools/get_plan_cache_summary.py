"""Implementation of the get_plan_cache_summary tool."""

from __future__ import annotations

from typing import Any

import mcp.types as types

from sql_tshooter.db import DatabaseClient
from sql_tshooter.tools.common import collected_at_utc, truncate_text


TOOL_NAME = "get_plan_cache_summary"
QUERY_TEXT_MAX_LENGTH = 220

QUERY = """
SELECT TOP (30)
    CONVERT(varchar(18), qs.query_hash, 1) AS query_hash,
    CAST(qs.execution_count AS bigint) AS execution_count,
    CAST(qs.total_elapsed_time AS bigint) AS total_elapsed_time,
    CAST(qs.total_worker_time AS bigint) AS total_worker_time,
    CAST(qs.total_logical_reads AS bigint) AS total_logical_reads,
    CAST(COALESCE(cp.usecounts, 0) AS bigint) AS plan_reuse_count,
    CAST(st.text AS nvarchar(max)) AS query_text
FROM sys.dm_exec_query_stats AS qs
JOIN sys.dm_exec_cached_plans AS cp
    ON qs.plan_handle = cp.plan_handle
CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) AS st
WHERE cp.cacheobjtype = 'Compiled Plan'
  AND cp.objtype IN ('Proc', 'Prepared', 'Adhoc')
ORDER BY
    qs.total_worker_time DESC,
    qs.total_elapsed_time DESC,
    qs.execution_count DESC;
""".strip()


def build_tool() -> types.Tool:
    return types.Tool(
        name=TOOL_NAME,
        description="Return summarized high-resource cached plan entries.",
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
                "plan_cache_summary": {
                    "type": "array",
                    "maxItems": 20,
                    "items": {
                        "type": "object",
                        "properties": {
                            "query_hash": {"type": "string"},
                            "execution_count": {"type": "integer"},
                            "avg_duration_ms": {"type": "number"},
                            "total_cpu_ms": {"type": "number"},
                            "logical_reads": {"type": "integer"},
                            "plan_reuse_count": {"type": "integer"},
                            "truncated_query_text": {"type": "string"},
                        },
                        "required": [
                            "query_hash",
                            "execution_count",
                            "avg_duration_ms",
                            "total_cpu_ms",
                            "logical_reads",
                            "plan_reuse_count",
                            "truncated_query_text",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["collected_at_utc", "interpretation_hint", "plan_cache_summary"],
            "additionalProperties": False,
        },
    )


async def execute(db_client: DatabaseClient) -> dict[str, Any]:
    rows = await db_client.fetch_all(QUERY)
    summary_rows = [_normalize_plan_cache_row(row) for row in rows if int(row["execution_count"]) > 0]
    summary_rows.sort(
        key=lambda row: (-row["total_cpu_ms"], -row["avg_duration_ms"], -row["execution_count"])
    )
    return {
        "collected_at_utc": collected_at_utc(),
        "interpretation_hint": "High CPU cached plans with low reuse are often strong tuning candidates.",
        "plan_cache_summary": summary_rows[:20],
    }


def _normalize_plan_cache_row(row: dict[str, Any]) -> dict[str, Any]:
    execution_count = max(int(row["execution_count"]), 0)
    total_elapsed_time = max(float(row["total_elapsed_time"]), 0.0)
    total_worker_time = max(float(row["total_worker_time"]), 0.0)
    return {
        "query_hash": str(row["query_hash"]),
        "execution_count": execution_count,
        "avg_duration_ms": round(total_elapsed_time / execution_count / 1000.0, 2)
        if execution_count
        else 0.0,
        "total_cpu_ms": round(total_worker_time / 1000.0, 2),
        "logical_reads": max(int(row["total_logical_reads"]), 0),
        "plan_reuse_count": max(int(row["plan_reuse_count"]), 0),
        "truncated_query_text": truncate_text(row["query_text"], QUERY_TEXT_MAX_LENGTH),
    }

