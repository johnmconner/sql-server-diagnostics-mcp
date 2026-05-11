"""Implementation of the get_query_store_regressions tool."""

from __future__ import annotations

from typing import Any

import mcp.types as types

from sql_tshooter.db import DatabaseClient
from sql_tshooter.tools.common import collected_at_utc, truncate_text


TOOL_NAME = "get_query_store_regressions"
QUERY_TEXT_MAX_LENGTH = 220
MIN_RECENT_EXECUTIONS = 3
MIN_BASELINE_EXECUTIONS = 5
MIN_DURATION_DELTA_MS = 100.0
REGRESSION_RATIO = 1.5

QUERY = """
WITH query_store_rollup AS (
    SELECT
        qsq.query_id,
        CONVERT(varchar(18), qsq.query_hash, 1) AS query_hash,
        CAST(qst.query_sql_text AS nvarchar(max)) AS query_text,
        SUM(CASE WHEN qsri.end_time >= DATEADD(HOUR, -1, SYSUTCDATETIME()) THEN qsrs.count_executions ELSE 0 END) AS execution_count_1h,
        SUM(CASE WHEN qsri.end_time >= DATEADD(HOUR, -1, SYSUTCDATETIME()) THEN qsrs.avg_duration * qsrs.count_executions ELSE 0 END) AS total_duration_1h,
        SUM(CASE WHEN qsri.end_time >= DATEADD(HOUR, -1, SYSUTCDATETIME()) THEN qsrs.avg_cpu_time * qsrs.count_executions ELSE 0 END) AS total_cpu_1h,
        SUM(CASE WHEN qsri.end_time >= DATEADD(HOUR, -1, SYSUTCDATETIME()) THEN qsrs.avg_logical_io_reads * qsrs.count_executions ELSE 0 END) AS total_reads_1h,
        SUM(CASE WHEN qsri.end_time < DATEADD(HOUR, -1, SYSUTCDATETIME()) AND qsri.end_time >= DATEADD(HOUR, -24, SYSUTCDATETIME()) THEN qsrs.count_executions ELSE 0 END) AS execution_count_baseline,
        SUM(CASE WHEN qsri.end_time < DATEADD(HOUR, -1, SYSUTCDATETIME()) AND qsri.end_time >= DATEADD(HOUR, -24, SYSUTCDATETIME()) THEN qsrs.avg_duration * qsrs.count_executions ELSE 0 END) AS total_duration_baseline,
        SUM(CASE WHEN qsri.end_time < DATEADD(HOUR, -1, SYSUTCDATETIME()) AND qsri.end_time >= DATEADD(HOUR, -24, SYSUTCDATETIME()) THEN qsrs.avg_cpu_time * qsrs.count_executions ELSE 0 END) AS total_cpu_baseline,
        SUM(CASE WHEN qsri.end_time < DATEADD(HOUR, -1, SYSUTCDATETIME()) AND qsri.end_time >= DATEADD(HOUR, -24, SYSUTCDATETIME()) THEN qsrs.avg_logical_io_reads * qsrs.count_executions ELSE 0 END) AS total_reads_baseline,
        COUNT(DISTINCT CASE WHEN qsri.end_time >= DATEADD(HOUR, -1, SYSUTCDATETIME()) THEN qsp.plan_id END) AS plan_count_recent,
        COUNT(DISTINCT CASE WHEN qsri.end_time < DATEADD(HOUR, -1, SYSUTCDATETIME()) AND qsri.end_time >= DATEADD(HOUR, -24, SYSUTCDATETIME()) THEN qsp.plan_id END) AS plan_count_baseline
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
        qst.query_sql_text
)
SELECT TOP (50)
    CAST(query_id AS bigint) AS query_id,
    CAST(query_hash AS nvarchar(18)) AS query_hash,
    CAST(query_text AS nvarchar(max)) AS query_text,
    CAST(execution_count_1h AS bigint) AS execution_count_1h,
    CAST(execution_count_baseline AS bigint) AS execution_count_baseline,
    CAST(CASE WHEN execution_count_1h > 0 THEN total_duration_1h / execution_count_1h / 1000.0 ELSE 0 END AS float) AS avg_duration_ms_1h,
    CAST(CASE WHEN execution_count_baseline > 0 THEN total_duration_baseline / execution_count_baseline / 1000.0 ELSE 0 END AS float) AS avg_duration_ms_baseline,
    CAST(CASE WHEN execution_count_1h > 0 THEN total_cpu_1h / execution_count_1h / 1000.0 ELSE 0 END AS float) AS avg_cpu_ms_1h,
    CAST(CASE WHEN execution_count_baseline > 0 THEN total_cpu_baseline / execution_count_baseline / 1000.0 ELSE 0 END AS float) AS avg_cpu_ms_baseline,
    CAST(CASE WHEN execution_count_1h > 0 THEN total_reads_1h / execution_count_1h ELSE 0 END AS float) AS avg_logical_io_reads_1h,
    CAST(CASE WHEN execution_count_baseline > 0 THEN total_reads_baseline / execution_count_baseline ELSE 0 END AS float) AS avg_logical_io_reads_baseline,
    CAST(plan_count_recent AS int) AS plan_count_recent,
    CAST(plan_count_baseline AS int) AS plan_count_baseline
FROM query_store_rollup
WHERE execution_count_1h > 0
ORDER BY
    avg_duration_ms_1h DESC,
    avg_cpu_ms_1h DESC,
    avg_logical_io_reads_1h DESC,
    query_id ASC;
""".strip()


def build_tool() -> types.Tool:
    return types.Tool(
        name=TOOL_NAME,
        description="Return major recent Query Store regressions from the configured database.",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
        outputSchema={
            "type": "object",
            "properties": {
                "collected_at_utc": {"type": "string"},
                "interpretation_hint": {"type": "string"},
                "regressions": {
                    "type": "array",
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "properties": {
                            "query_id": {"type": "integer"},
                            "query_hash": {"type": "string"},
                            "regression_type": {"type": "string"},
                            "execution_count_1h": {"type": "integer"},
                            "avg_duration_ms_1h": {"type": "number"},
                            "avg_duration_ms_baseline": {"type": "number"},
                            "avg_cpu_ms_1h": {"type": "number"},
                            "avg_cpu_ms_baseline": {"type": "number"},
                            "plan_count_recent": {"type": "integer"},
                            "new_plan_detected": {"type": "boolean"},
                            "truncated_query_text": {"type": "string"},
                        },
                        "required": [
                            "query_id",
                            "query_hash",
                            "regression_type",
                            "execution_count_1h",
                            "avg_duration_ms_1h",
                            "avg_duration_ms_baseline",
                            "avg_cpu_ms_1h",
                            "avg_cpu_ms_baseline",
                            "plan_count_recent",
                            "new_plan_detected",
                            "truncated_query_text",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["collected_at_utc", "interpretation_hint", "regressions"],
            "additionalProperties": False,
        },
    )


async def execute(db_client: DatabaseClient) -> dict[str, Any]:
    rows = await db_client.fetch_all(QUERY)
    regressions = []
    for row in rows:
        normalized = _normalize_row(row)
        if _is_major_regression(normalized):
            regressions.append(normalized)
    regressions.sort(
        key=lambda row: (
            -max(
                _ratio(row["avg_duration_ms_1h"], row["avg_duration_ms_baseline"]),
                _ratio(row["avg_cpu_ms_1h"], row["avg_cpu_ms_baseline"]),
                _ratio(row["avg_logical_io_reads_1h"], row["avg_logical_io_reads_baseline"]),
            ),
            -row["avg_duration_ms_1h"],
            row["query_id"],
        )
    )
    return {
        "collected_at_utc": collected_at_utc(),
        "interpretation_hint": (
            "Recent regressions compare the last hour against the prior 24-hour baseline so intermittent slowdowns are still visible after the fact."
        ),
        "regressions": regressions[:10],
    }


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    recent_duration = round(max(float(row.get("avg_duration_ms_1h") or 0.0), 0.0), 2)
    baseline_duration = round(max(float(row.get("avg_duration_ms_baseline") or 0.0), 0.0), 2)
    recent_cpu = round(max(float(row.get("avg_cpu_ms_1h") or 0.0), 0.0), 2)
    baseline_cpu = round(max(float(row.get("avg_cpu_ms_baseline") or 0.0), 0.0), 2)
    recent_reads = round(max(float(row.get("avg_logical_io_reads_1h") or 0.0), 0.0), 2)
    baseline_reads = round(max(float(row.get("avg_logical_io_reads_baseline") or 0.0), 0.0), 2)

    return {
        "query_id": int(row["query_id"]),
        "query_hash": str(row.get("query_hash") or "unknown"),
        "regression_type": _regression_type(
            recent_duration,
            baseline_duration,
            recent_cpu,
            baseline_cpu,
            recent_reads,
            baseline_reads,
        ),
        "execution_count_1h": max(int(row.get("execution_count_1h") or 0), 0),
        "execution_count_baseline": max(int(row.get("execution_count_baseline") or 0), 0),
        "avg_duration_ms_1h": recent_duration,
        "avg_duration_ms_baseline": baseline_duration,
        "avg_cpu_ms_1h": recent_cpu,
        "avg_cpu_ms_baseline": baseline_cpu,
        "avg_logical_io_reads_1h": recent_reads,
        "avg_logical_io_reads_baseline": baseline_reads,
        "plan_count_recent": max(int(row.get("plan_count_recent") or 0), 0),
        "plan_count_baseline": max(int(row.get("plan_count_baseline") or 0), 0),
        "new_plan_detected": max(int(row.get("plan_count_recent") or 0), 0)
        > max(int(row.get("plan_count_baseline") or 0), 0),
        "truncated_query_text": truncate_text(row.get("query_text"), QUERY_TEXT_MAX_LENGTH),
    }


def _is_major_regression(row: dict[str, Any]) -> bool:
    if row["execution_count_1h"] < MIN_RECENT_EXECUTIONS:
        return False
    if row["execution_count_baseline"] < MIN_BASELINE_EXECUTIONS:
        return False
    duration_ratio = _ratio(row["avg_duration_ms_1h"], row["avg_duration_ms_baseline"])
    cpu_ratio = _ratio(row["avg_cpu_ms_1h"], row["avg_cpu_ms_baseline"])
    reads_ratio = _ratio(row["avg_logical_io_reads_1h"], row["avg_logical_io_reads_baseline"])
    return (
        (duration_ratio >= REGRESSION_RATIO and row["avg_duration_ms_1h"] - row["avg_duration_ms_baseline"] >= MIN_DURATION_DELTA_MS)
        or cpu_ratio >= REGRESSION_RATIO
        or reads_ratio >= REGRESSION_RATIO
    )


def _ratio(recent: float, baseline: float) -> float:
    if baseline <= 0:
        return 0.0
    return recent / baseline


def _regression_type(
    recent_duration: float,
    baseline_duration: float,
    recent_cpu: float,
    baseline_cpu: float,
    recent_reads: float,
    baseline_reads: float,
) -> str:
    ratios = {
        "duration": _ratio(recent_duration, baseline_duration),
        "cpu": _ratio(recent_cpu, baseline_cpu),
        "io": _ratio(recent_reads, baseline_reads),
    }
    top_name = max(ratios, key=ratios.get)
    top_ratio = ratios[top_name]
    significant = [name for name, ratio in ratios.items() if ratio >= REGRESSION_RATIO]
    if len(significant) >= 2 and top_ratio >= REGRESSION_RATIO:
        return "mixed"
    return top_name
