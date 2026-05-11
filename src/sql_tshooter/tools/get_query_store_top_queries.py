"""Implementation of the get_query_store_top_queries tool."""

from __future__ import annotations

from typing import Any

import mcp.types as types

from sql_tshooter.db import DatabaseClient
from sql_tshooter.tools.common import collected_at_utc, truncate_identifier, truncate_text


TOOL_NAME = "get_query_store_top_queries"
QUERY_TEXT_MAX_LENGTH = 220
OBJECT_NAME_MAX_LENGTH = 160

QUERY = """
WITH query_store_rollup AS (
    SELECT
        qsq.query_id,
        CONVERT(varchar(18), qsq.query_hash, 1) AS query_hash,
        CAST(
            CASE
                WHEN qsq.object_id > 0 THEN
                    QUOTENAME(OBJECT_SCHEMA_NAME(qsq.object_id)) + N'.' + QUOTENAME(OBJECT_NAME(qsq.object_id))
                ELSE NULL
            END AS nvarchar(256)
        ) AS object_name,
        CAST(qst.query_sql_text AS nvarchar(max)) AS query_text,
        COUNT(DISTINCT qsp.plan_id) AS plan_count,
        MAX(qsrs.last_execution_time) AS last_execution_time_utc,
        SUM(CASE WHEN qsri.end_time >= DATEADD(HOUR, -1, SYSUTCDATETIME()) THEN qsrs.count_executions ELSE 0 END) AS execution_count_1h,
        SUM(CASE WHEN qsri.end_time >= DATEADD(HOUR, -24, SYSUTCDATETIME()) THEN qsrs.count_executions ELSE 0 END) AS execution_count_24h,
        SUM(CASE WHEN qsri.end_time >= DATEADD(HOUR, -1, SYSUTCDATETIME()) THEN qsrs.avg_duration * qsrs.count_executions ELSE 0 END) AS total_duration_1h,
        SUM(CASE WHEN qsri.end_time >= DATEADD(HOUR, -1, SYSUTCDATETIME()) THEN qsrs.avg_cpu_time * qsrs.count_executions ELSE 0 END) AS total_cpu_1h,
        SUM(CASE WHEN qsri.end_time >= DATEADD(HOUR, -1, SYSUTCDATETIME()) THEN qsrs.avg_logical_io_reads * qsrs.count_executions ELSE 0 END) AS total_reads_1h
    FROM sys.query_store_query AS qsq
    JOIN sys.query_store_query_text AS qst
        ON qsq.query_text_id = qst.query_text_id
    JOIN sys.query_store_plan AS qsp
        ON qsq.query_id = qsp.query_id
    JOIN sys.query_store_runtime_stats AS qsrs
        ON qsp.plan_id = qsrs.plan_id
    JOIN sys.query_store_runtime_stats_interval AS qsri
        ON qsrs.runtime_stats_interval_id = qsri.runtime_stats_interval_id
    GROUP BY
        qsq.query_id,
        qsq.query_hash,
        qsq.object_id,
        qst.query_sql_text
)
SELECT TOP (20)
    CAST(query_id AS bigint) AS query_id,
    CAST(query_hash AS nvarchar(18)) AS query_hash,
    CAST(object_name AS nvarchar(256)) AS object_name,
    CAST(query_text AS nvarchar(max)) AS query_text,
    CAST(execution_count_1h AS bigint) AS execution_count_1h,
    CAST(
        CASE WHEN execution_count_1h > 0 THEN total_duration_1h / execution_count_1h / 1000.0 ELSE 0 END
        AS float
    ) AS avg_duration_ms_1h,
    CAST(
        CASE WHEN execution_count_1h > 0 THEN total_cpu_1h / execution_count_1h / 1000.0 ELSE 0 END
        AS float
    ) AS avg_cpu_ms_1h,
    CAST(
        CASE WHEN execution_count_1h > 0 THEN total_reads_1h / execution_count_1h ELSE 0 END
        AS float
    ) AS avg_logical_io_reads_1h,
    CAST(execution_count_24h AS bigint) AS execution_count_24h,
    CAST(plan_count AS int) AS plan_count,
    CAST(last_execution_time_utc AS datetime2) AS last_execution_time_utc,
    CAST(total_duration_1h AS float) AS total_duration_score_1h,
    CAST(total_cpu_1h AS float) AS total_cpu_score_1h,
    CAST(total_reads_1h AS float) AS total_reads_score_1h
FROM query_store_rollup
WHERE execution_count_1h > 0
ORDER BY
    total_duration_score_1h DESC,
    total_cpu_score_1h DESC,
    total_reads_score_1h DESC,
    query_id ASC;
""".strip()


def build_tool() -> types.Tool:
    return types.Tool(
        name=TOOL_NAME,
        description="Return top recent Query Store queries from the configured database.",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
        outputSchema={
            "type": "object",
            "properties": {
                "collected_at_utc": {"type": "string"},
                "interpretation_hint": {"type": "string"},
                "top_queries": {
                    "type": "array",
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "properties": {
                            "query_id": {"type": "integer"},
                            "query_hash": {"type": "string"},
                            "object_name": {"type": "string"},
                            "execution_count_1h": {"type": "integer"},
                            "avg_duration_ms_1h": {"type": "number"},
                            "avg_cpu_ms_1h": {"type": "number"},
                            "avg_logical_io_reads_1h": {"type": "number"},
                            "execution_count_24h": {"type": "integer"},
                            "plan_count": {"type": "integer"},
                            "last_execution_time_utc": {"type": ["string", "null"]},
                            "truncated_query_text": {"type": "string"},
                        },
                        "required": [
                            "query_id",
                            "query_hash",
                            "object_name",
                            "execution_count_1h",
                            "avg_duration_ms_1h",
                            "avg_cpu_ms_1h",
                            "avg_logical_io_reads_1h",
                            "execution_count_24h",
                            "plan_count",
                            "last_execution_time_utc",
                            "truncated_query_text",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["collected_at_utc", "interpretation_hint", "top_queries"],
            "additionalProperties": False,
        },
    )


async def execute(db_client: DatabaseClient) -> dict[str, Any]:
    rows = await db_client.fetch_all(QUERY)
    top_queries = [_normalize_row(row) for row in rows]
    return {
        "collected_at_utc": collected_at_utc(),
        "interpretation_hint": (
            "These are the heaviest recent Query Store queries in the configured database, which is useful when live DMVs are quiet but the incident was recent."
        ),
        "top_queries": top_queries[:10],
    }


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    last_execution_time = row.get("last_execution_time_utc")
    return {
        "query_id": int(row["query_id"]),
        "query_hash": str(row.get("query_hash") or "unknown"),
        "object_name": truncate_identifier(row.get("object_name"), OBJECT_NAME_MAX_LENGTH),
        "execution_count_1h": max(int(row.get("execution_count_1h") or 0), 0),
        "avg_duration_ms_1h": round(max(float(row.get("avg_duration_ms_1h") or 0.0), 0.0), 2),
        "avg_cpu_ms_1h": round(max(float(row.get("avg_cpu_ms_1h") or 0.0), 0.0), 2),
        "avg_logical_io_reads_1h": round(
            max(float(row.get("avg_logical_io_reads_1h") or 0.0), 0.0), 2
        ),
        "execution_count_24h": max(int(row.get("execution_count_24h") or 0), 0),
        "plan_count": max(int(row.get("plan_count") or 0), 0),
        "last_execution_time_utc": None if last_execution_time is None else str(last_execution_time),
        "truncated_query_text": truncate_text(row.get("query_text"), QUERY_TEXT_MAX_LENGTH),
    }
