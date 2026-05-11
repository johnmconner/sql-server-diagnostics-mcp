"""Implementation of the get_query_store_plan_variants tool."""

from __future__ import annotations

from typing import Any

import mcp.types as types

from sql_tshooter.db import DatabaseClient
from sql_tshooter.errors import ToolExecutionError
from sql_tshooter.tools.common import collected_at_utc
from sql_tshooter.tools.plan_xml_summary import summarize_plan_xml
from sql_tshooter.tools.query_store_common import validate_query_id


TOOL_NAME = "get_query_store_plan_variants"

QUERY = """
WITH plan_rollup AS (
    SELECT
        qsq.query_id,
        CONVERT(varchar(18), qsq.query_hash, 1) AS query_hash,
        qsp.plan_id,
        qsp.is_forced_plan,
        CAST(CONVERT(nvarchar(max), qsp.query_plan) AS nvarchar(max)) AS plan_xml,
        COUNT(*) AS runtime_stats_row_count,
        MAX(qsrs.last_execution_time) AS last_execution_time_utc,
        SUM(CASE WHEN qsri.end_time >= DATEADD(HOUR, -1, SYSUTCDATETIME()) THEN qsrs.count_executions ELSE 0 END) AS execution_count_1h,
        SUM(CASE WHEN qsri.end_time >= DATEADD(HOUR, -1, SYSUTCDATETIME()) THEN qsrs.avg_duration * qsrs.count_executions ELSE 0 END) AS total_duration_1h,
        SUM(CASE WHEN qsri.end_time >= DATEADD(HOUR, -1, SYSUTCDATETIME()) THEN qsrs.avg_cpu_time * qsrs.count_executions ELSE 0 END) AS total_cpu_1h,
        SUM(CASE WHEN qsri.end_time >= DATEADD(HOUR, -1, SYSUTCDATETIME()) THEN qsrs.avg_logical_io_reads * qsrs.count_executions ELSE 0 END) AS total_reads_1h
    FROM sys.query_store_query AS qsq
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
        qsp.plan_id,
        qsp.is_forced_plan,
        qsp.query_plan
)
SELECT TOP (20)
    CAST(query_id AS bigint) AS query_id,
    CAST(query_hash AS nvarchar(18)) AS query_hash,
    CAST(plan_id AS bigint) AS plan_id,
    CAST(is_forced_plan AS bit) AS is_forced_plan,
    CAST(plan_xml AS nvarchar(max)) AS plan_xml,
    CAST(runtime_stats_row_count AS bigint) AS runtime_stats_row_count,
    CAST(execution_count_1h AS bigint) AS execution_count_1h,
    CAST(CASE WHEN execution_count_1h > 0 THEN total_duration_1h / execution_count_1h / 1000.0 ELSE 0 END AS float) AS avg_duration_ms_1h,
    CAST(CASE WHEN execution_count_1h > 0 THEN total_cpu_1h / execution_count_1h / 1000.0 ELSE 0 END AS float) AS avg_cpu_ms_1h,
    CAST(CASE WHEN execution_count_1h > 0 THEN total_reads_1h / execution_count_1h ELSE 0 END AS float) AS avg_logical_io_reads_1h,
    CAST(last_execution_time_utc AS datetime2) AS last_execution_time_utc
FROM plan_rollup
ORDER BY
    execution_count_1h DESC,
    avg_duration_ms_1h DESC,
    plan_id ASC;
""".strip()


def build_tool() -> types.Tool:
    return types.Tool(
        name=TOOL_NAME,
        description="Return recent Query Store plan variants for one query_id.",
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
                "interpretation_hint": {"type": "string"},
                "plans": {
                    "type": "array",
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "properties": {
                            "plan_id": {"type": "integer"},
                            "is_forced_plan": {"type": "boolean"},
                            "execution_count_1h": {"type": "integer"},
                            "avg_duration_ms_1h": {"type": "number"},
                            "avg_cpu_ms_1h": {"type": "number"},
                            "avg_logical_io_reads_1h": {"type": "number"},
                            "last_execution_time_utc": {"type": ["string", "null"]},
                            "has_runtime_stats": {"type": "boolean"},
                            "plan_summary": {
                                "type": "object",
                                "properties": {
                                    "parallelism_detected": {"type": "boolean"},
                                    "missing_index_detected": {"type": "boolean"},
                                    "total_estimated_subtree_cost": {"type": "number"},
                                    "top_operator_names": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                                "required": [
                                    "parallelism_detected",
                                    "missing_index_detected",
                                    "total_estimated_subtree_cost",
                                    "top_operator_names",
                                ],
                                "additionalProperties": False,
                            },
                        },
                        "required": [
                            "plan_id",
                            "is_forced_plan",
                            "execution_count_1h",
                            "avg_duration_ms_1h",
                            "avg_cpu_ms_1h",
                            "avg_logical_io_reads_1h",
                            "last_execution_time_utc",
                            "has_runtime_stats",
                            "plan_summary",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "collected_at_utc",
                "query_id",
                "query_hash",
                "interpretation_hint",
                "plans",
            ],
            "additionalProperties": False,
        },
    )


async def execute(db_client: DatabaseClient, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    query_id = validate_query_id(arguments or {})
    rows = await db_client.fetch_all(QUERY, (query_id,))
    if not rows:
        raise ToolExecutionError("No Query Store query matched the supplied query_id.")

    normalized_rows = [_normalize_row(row) for row in rows]
    return {
        "collected_at_utc": collected_at_utc(),
        "query_id": query_id,
        "query_hash": str(rows[0].get("query_hash") or "unknown"),
        "interpretation_hint": (
            "Multiple recent plans for the same Query Store query can indicate instability even when current DMV snapshots look normal."
        ),
        "plans": normalized_rows[:10],
    }


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    summary = summarize_plan_xml(str(row.get("plan_xml") or ""))
    last_execution_time = row.get("last_execution_time_utc")
    return {
        "plan_id": int(row["plan_id"]),
        "is_forced_plan": bool(row.get("is_forced_plan")),
        "execution_count_1h": max(int(row.get("execution_count_1h") or 0), 0),
        "avg_duration_ms_1h": round(max(float(row.get("avg_duration_ms_1h") or 0.0), 0.0), 2),
        "avg_cpu_ms_1h": round(max(float(row.get("avg_cpu_ms_1h") or 0.0), 0.0), 2),
        "avg_logical_io_reads_1h": round(
            max(float(row.get("avg_logical_io_reads_1h") or 0.0), 0.0), 2
        ),
        "last_execution_time_utc": None if last_execution_time is None else str(last_execution_time),
        "has_runtime_stats": max(int(row.get("runtime_stats_row_count") or 0), 0) > 0,
        "plan_summary": {
            "parallelism_detected": summary["parallelism_detected"],
            "missing_index_detected": summary["missing_index_detected"],
            "total_estimated_subtree_cost": summary["total_estimated_subtree_cost"],
            "top_operator_names": summary["top_operator_names"],
        },
    }
