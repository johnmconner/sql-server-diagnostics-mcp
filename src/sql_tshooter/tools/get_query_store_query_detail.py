"""Implementation of the get_query_store_query_detail tool."""

from __future__ import annotations

from typing import Any

import mcp.types as types

from sql_tshooter.db import DatabaseClient
from sql_tshooter.errors import ToolExecutionError
from sql_tshooter.tools.common import collected_at_utc, truncate_identifier, truncate_text
from sql_tshooter.tools.query_store_common import validate_query_id


TOOL_NAME = "get_query_store_query_detail"
QUERY_TEXT_MAX_LENGTH = 220
OBJECT_NAME_MAX_LENGTH = 160

QUERY = """
WITH query_detail AS (
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
        MAX(CASE WHEN qsp.is_forced_plan = 1 THEN qsp.plan_id END) AS forced_plan_id,
        MAX(qsrs.last_execution_time) AS last_execution_time_utc,
        SUM(CASE WHEN qsri.end_time >= DATEADD(HOUR, -1, SYSUTCDATETIME()) THEN qsrs.count_executions ELSE 0 END) AS execution_count_1h,
        SUM(CASE WHEN qsri.end_time >= DATEADD(HOUR, -1, SYSUTCDATETIME()) THEN qsrs.avg_duration * qsrs.count_executions ELSE 0 END) AS total_duration_1h,
        SUM(CASE WHEN qsri.end_time >= DATEADD(HOUR, -1, SYSUTCDATETIME()) THEN qsrs.avg_cpu_time * qsrs.count_executions ELSE 0 END) AS total_cpu_1h,
        SUM(CASE WHEN qsri.end_time >= DATEADD(HOUR, -1, SYSUTCDATETIME()) THEN qsrs.avg_logical_io_reads * qsrs.count_executions ELSE 0 END) AS total_reads_1h,
        SUM(CASE WHEN qsri.end_time < DATEADD(HOUR, -1, SYSUTCDATETIME()) AND qsri.end_time >= DATEADD(HOUR, -24, SYSUTCDATETIME()) THEN qsrs.count_executions ELSE 0 END) AS execution_count_baseline,
        SUM(CASE WHEN qsri.end_time < DATEADD(HOUR, -1, SYSUTCDATETIME()) AND qsri.end_time >= DATEADD(HOUR, -24, SYSUTCDATETIME()) THEN qsrs.avg_duration * qsrs.count_executions ELSE 0 END) AS total_duration_baseline,
        SUM(CASE WHEN qsri.end_time < DATEADD(HOUR, -1, SYSUTCDATETIME()) AND qsri.end_time >= DATEADD(HOUR, -24, SYSUTCDATETIME()) THEN qsrs.avg_cpu_time * qsrs.count_executions ELSE 0 END) AS total_cpu_baseline,
        SUM(CASE WHEN qsri.end_time < DATEADD(HOUR, -1, SYSUTCDATETIME()) AND qsri.end_time >= DATEADD(HOUR, -24, SYSUTCDATETIME()) THEN qsrs.avg_logical_io_reads * qsrs.count_executions ELSE 0 END) AS total_reads_baseline
    FROM sys.query_store_query AS qsq
    JOIN sys.query_store_query_text AS qst
        ON qsq.query_text_id = qst.query_text_id
    JOIN sys.query_store_plan AS qsp
        ON qsq.query_id = qsp.query_id
    LEFT JOIN sys.query_store_runtime_stats AS qsrs
        ON qsp.plan_id = qsrs.plan_id
    LEFT JOIN sys.query_store_runtime_stats_interval AS qsri
        ON qsrs.runtime_stats_interval_id = qsri.runtime_stats_interval_id
    WHERE qsq.query_id = ?
    GROUP BY
        qsq.query_id,
        qsq.query_hash,
        qsq.object_id,
        qst.query_sql_text
)
SELECT TOP (1)
    CAST(query_id AS bigint) AS query_id,
    CAST(query_hash AS nvarchar(18)) AS query_hash,
    CAST(object_name AS nvarchar(256)) AS object_name,
    CAST(query_text AS nvarchar(max)) AS query_text,
    CAST(plan_count AS int) AS plan_count,
    CAST(forced_plan_id AS bigint) AS forced_plan_id,
    CAST(last_execution_time_utc AS datetime2) AS last_execution_time_utc,
    CAST(execution_count_1h AS bigint) AS execution_count_1h,
    CAST(CASE WHEN execution_count_1h > 0 THEN total_duration_1h / execution_count_1h / 1000.0 ELSE 0 END AS float) AS avg_duration_ms_1h,
    CAST(CASE WHEN execution_count_1h > 0 THEN total_cpu_1h / execution_count_1h / 1000.0 ELSE 0 END AS float) AS avg_cpu_ms_1h,
    CAST(CASE WHEN execution_count_1h > 0 THEN total_reads_1h / execution_count_1h ELSE 0 END AS float) AS avg_logical_io_reads_1h,
    CAST(execution_count_baseline AS bigint) AS execution_count_baseline,
    CAST(CASE WHEN execution_count_baseline > 0 THEN total_duration_baseline / execution_count_baseline / 1000.0 ELSE 0 END AS float) AS avg_duration_ms_baseline,
    CAST(CASE WHEN execution_count_baseline > 0 THEN total_cpu_baseline / execution_count_baseline / 1000.0 ELSE 0 END AS float) AS avg_cpu_ms_baseline,
    CAST(CASE WHEN execution_count_baseline > 0 THEN total_reads_baseline / execution_count_baseline ELSE 0 END AS float) AS avg_logical_io_reads_baseline
FROM query_detail;
""".strip()


def build_tool() -> types.Tool:
    return types.Tool(
        name=TOOL_NAME,
        description="Return historical Query Store detail for one query_id.",
        inputSchema={
            "type": "object",
            "properties": {"query_id": {"type": "integer"}},
            "required": ["query_id"],
            "additionalProperties": False,
        },
        outputSchema={
            "type": "object",
            "properties": {
                "collected_at_utc": {"type": "string"},
                "query_id": {"type": "integer"},
                "query_hash": {"type": "string"},
                "object_name": {"type": "string"},
                "plan_count": {"type": "integer"},
                "forced_plan_id": {"type": ["integer", "null"]},
                "execution_count_1h": {"type": "integer"},
                "avg_duration_ms_1h": {"type": "number"},
                "avg_cpu_ms_1h": {"type": "number"},
                "avg_logical_io_reads_1h": {"type": "number"},
                "execution_count_baseline": {"type": "integer"},
                "avg_duration_ms_baseline": {"type": "number"},
                "avg_cpu_ms_baseline": {"type": "number"},
                "avg_logical_io_reads_baseline": {"type": "number"},
                "last_execution_time_utc": {"type": ["string", "null"]},
                "truncated_query_text": {"type": "string"},
                "interpretation_hint": {"type": "string"},
            },
            "required": [
                "collected_at_utc",
                "query_id",
                "query_hash",
                "object_name",
                "plan_count",
                "forced_plan_id",
                "execution_count_1h",
                "avg_duration_ms_1h",
                "avg_cpu_ms_1h",
                "avg_logical_io_reads_1h",
                "execution_count_baseline",
                "avg_duration_ms_baseline",
                "avg_cpu_ms_baseline",
                "avg_logical_io_reads_baseline",
                "last_execution_time_utc",
                "truncated_query_text",
                "interpretation_hint",
            ],
            "additionalProperties": False,
        },
    )


async def execute(db_client: DatabaseClient, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    query_id = validate_query_id(arguments or {})
    rows = await db_client.fetch_all(QUERY, (query_id,))
    if not rows:
        raise ToolExecutionError("No Query Store query matched the supplied query_id.")
    row = rows[0]
    return _normalize_row(row)


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    last_execution_time = row.get("last_execution_time_utc")
    recent_duration = round(max(float(row.get("avg_duration_ms_1h") or 0.0), 0.0), 2)
    baseline_duration = round(max(float(row.get("avg_duration_ms_baseline") or 0.0), 0.0), 2)
    recent_cpu = round(max(float(row.get("avg_cpu_ms_1h") or 0.0), 0.0), 2)
    baseline_cpu = round(max(float(row.get("avg_cpu_ms_baseline") or 0.0), 0.0), 2)
    recent_reads = round(max(float(row.get("avg_logical_io_reads_1h") or 0.0), 0.0), 2)
    baseline_reads = round(max(float(row.get("avg_logical_io_reads_baseline") or 0.0), 0.0), 2)

    return {
        "collected_at_utc": collected_at_utc(),
        "query_id": int(row["query_id"]),
        "query_hash": str(row.get("query_hash") or "unknown"),
        "object_name": truncate_identifier(row.get("object_name"), OBJECT_NAME_MAX_LENGTH),
        "plan_count": max(int(row.get("plan_count") or 0), 0),
        "forced_plan_id": None if row.get("forced_plan_id") is None else int(row["forced_plan_id"]),
        "execution_count_1h": max(int(row.get("execution_count_1h") or 0), 0),
        "avg_duration_ms_1h": recent_duration,
        "avg_cpu_ms_1h": recent_cpu,
        "avg_logical_io_reads_1h": recent_reads,
        "execution_count_baseline": max(int(row.get("execution_count_baseline") or 0), 0),
        "avg_duration_ms_baseline": baseline_duration,
        "avg_cpu_ms_baseline": baseline_cpu,
        "avg_logical_io_reads_baseline": baseline_reads,
        "last_execution_time_utc": None if last_execution_time is None else str(last_execution_time),
        "truncated_query_text": truncate_text(row.get("query_text"), QUERY_TEXT_MAX_LENGTH),
        "interpretation_hint": _interpretation_hint(
            recent_duration,
            baseline_duration,
            recent_cpu,
            baseline_cpu,
            max(int(row.get("plan_count") or 0), 0),
        ),
    }


def _interpretation_hint(
    recent_duration: float,
    baseline_duration: float,
    recent_cpu: float,
    baseline_cpu: float,
    plan_count: int,
) -> str:
    if baseline_duration > 0 and recent_duration >= baseline_duration * 1.5:
        return "Recent duration is materially above baseline, so this query is a likely historical regression candidate."
    if baseline_cpu > 0 and recent_cpu >= baseline_cpu * 1.5:
        return "Recent CPU is materially above baseline, which suggests a workload or plan shift."
    if plan_count > 1:
        return "Multiple known Query Store plans exist for this query, which can indicate plan instability."
    return "This view is most useful for comparing recent performance with the historical baseline for a single query."
