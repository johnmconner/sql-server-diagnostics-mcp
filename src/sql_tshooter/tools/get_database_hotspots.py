"""Implementation of the get_database_hotspots tool."""

from __future__ import annotations

from typing import Any

import mcp.types as types

from sql_tshooter.db import DatabaseClient
from sql_tshooter.tools.common import collected_at_utc, truncate_identifier


TOOL_NAME = "get_database_hotspots"
NAME_MAX_LENGTH = 120

QUERY = """
WITH request_counts AS (
    SELECT
        DB_NAME(er.database_id) AS database_name,
        COUNT(*) AS active_request_count
    FROM sys.dm_exec_requests AS er
    JOIN sys.dm_exec_sessions AS es
        ON er.session_id = es.session_id
    WHERE es.is_user_process = 1
      AND er.session_id <> @@SPID
      AND er.database_id IS NOT NULL
    GROUP BY DB_NAME(er.database_id)
),
wait_counts AS (
    SELECT
        DB_NAME(er.database_id) AS database_name,
        wt.wait_type AS wait_type,
        COUNT(*) AS wait_count
    FROM sys.dm_os_waiting_tasks AS wt
    JOIN sys.dm_exec_requests AS er
        ON wt.session_id = er.session_id
    JOIN sys.dm_exec_sessions AS es
        ON er.session_id = es.session_id
    WHERE es.is_user_process = 1
      AND er.session_id <> @@SPID
      AND er.database_id IS NOT NULL
      AND wt.wait_type IS NOT NULL
    GROUP BY DB_NAME(er.database_id), wt.wait_type
),
wait_ranked AS (
    SELECT
        database_name,
        wait_type,
        wait_count,
        ROW_NUMBER() OVER (
            PARTITION BY database_name
            ORDER BY wait_count DESC, wait_type ASC
        ) AS wait_rank
    FROM wait_counts
),
memory_grants AS (
    SELECT
        DB_NAME(er.database_id) AS database_name,
        COUNT(*) AS memory_grant_count
    FROM sys.dm_exec_query_memory_grants AS mg
    JOIN sys.dm_exec_requests AS er
        ON mg.session_id = er.session_id
    JOIN sys.dm_exec_sessions AS es
        ON mg.session_id = es.session_id
    WHERE es.is_user_process = 1
      AND mg.session_id <> @@SPID
      AND er.database_id IS NOT NULL
    GROUP BY DB_NAME(er.database_id)
),
tempdb_usage AS (
    SELECT
        DB_NAME(COALESCE(er.database_id, es.database_id)) AS database_name,
        SUM(
            (ssu.internal_objects_alloc_page_count - ssu.internal_objects_dealloc_page_count)
            * 8.0 / 1024
        ) AS tempdb_internal_object_mb,
        SUM(
            (ssu.user_objects_alloc_page_count - ssu.user_objects_dealloc_page_count)
            * 8.0 / 1024
        ) AS tempdb_user_object_mb
    FROM sys.dm_db_session_space_usage AS ssu
    JOIN sys.dm_exec_sessions AS es
        ON ssu.session_id = es.session_id
    LEFT JOIN sys.dm_exec_requests AS er
        ON ssu.session_id = er.session_id
    WHERE es.is_user_process = 1
      AND ssu.session_id <> @@SPID
      AND COALESCE(er.database_id, es.database_id) IS NOT NULL
    GROUP BY DB_NAME(COALESCE(er.database_id, es.database_id))
),
database_keys AS (
    SELECT database_name FROM request_counts
    UNION
    SELECT database_name FROM wait_ranked
    UNION
    SELECT database_name FROM memory_grants
    UNION
    SELECT database_name FROM tempdb_usage
)
SELECT TOP (20)
    CAST(dk.database_name AS nvarchar(128)) AS database_name,
    CAST(ISNULL(rc.active_request_count, 0) AS int) AS active_request_count,
    CAST(ISNULL(wr.wait_count, 0) AS int) AS waiting_task_count,
    CAST(ISNULL(mg.memory_grant_count, 0) AS int) AS memory_grant_count,
    CAST(ISNULL(tu.tempdb_internal_object_mb, 0.0) AS float) AS tempdb_internal_object_mb,
    CAST(ISNULL(tu.tempdb_user_object_mb, 0.0) AS float) AS tempdb_user_object_mb,
    CAST(ISNULL(wr.wait_type, 'NONE') AS nvarchar(120)) AS dominant_wait_type
FROM database_keys AS dk
LEFT JOIN request_counts AS rc
    ON dk.database_name = rc.database_name
LEFT JOIN wait_ranked AS wr
    ON dk.database_name = wr.database_name
   AND wr.wait_rank = 1
LEFT JOIN memory_grants AS mg
    ON dk.database_name = mg.database_name
LEFT JOIN tempdb_usage AS tu
    ON dk.database_name = tu.database_name
ORDER BY
    ISNULL(rc.active_request_count, 0) DESC,
    ISNULL(wr.wait_count, 0) DESC,
    ISNULL(mg.memory_grant_count, 0) DESC,
    ISNULL(tu.tempdb_internal_object_mb, 0.0) + ISNULL(tu.tempdb_user_object_mb, 0.0) DESC,
    dk.database_name ASC;
""".strip()


def build_tool() -> types.Tool:
    return types.Tool(
        name=TOOL_NAME,
        description="Return a per-database summary of current workload concentration on a shared SQL instance.",
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
                "database_hotspots": {
                    "type": "array",
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "properties": {
                            "database_name": {"type": "string"},
                            "active_request_count": {"type": "integer"},
                            "waiting_task_count": {"type": "integer"},
                            "memory_grant_count": {"type": "integer"},
                            "tempdb_internal_object_mb": {"type": "number"},
                            "tempdb_user_object_mb": {"type": "number"},
                            "dominant_wait_type": {"type": "string"},
                        },
                        "required": [
                            "database_name",
                            "active_request_count",
                            "waiting_task_count",
                            "memory_grant_count",
                            "tempdb_internal_object_mb",
                            "tempdb_user_object_mb",
                            "dominant_wait_type",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["collected_at_utc", "interpretation_hint", "database_hotspots"],
            "additionalProperties": False,
        },
    )


async def execute(db_client: DatabaseClient) -> dict[str, Any]:
    rows = await db_client.fetch_all(QUERY)
    database_hotspots = [_normalize_database_hotspot_row(row) for row in rows if _is_hot(row)]
    database_hotspots.sort(
        key=lambda row: (
            -row["active_request_count"],
            -row["waiting_task_count"],
            -row["memory_grant_count"],
            -(row["tempdb_internal_object_mb"] + row["tempdb_user_object_mb"]),
            row["database_name"].lower(),
        )
    )
    return {
        "collected_at_utc": collected_at_utc(),
        "interpretation_hint": (
            "When one database dominates requests, waits, memory grants, or TempDB usage, the issue is usually concentrated rather than instance-wide."
        ),
        "database_hotspots": database_hotspots[:10],
    }


def _is_hot(row: dict[str, Any]) -> bool:
    return any(
        (
            int(row.get("active_request_count") or 0) > 0,
            int(row.get("waiting_task_count") or 0) > 0,
            int(row.get("memory_grant_count") or 0) > 0,
            float(row.get("tempdb_internal_object_mb") or 0.0) > 0,
            float(row.get("tempdb_user_object_mb") or 0.0) > 0,
        )
    )


def _normalize_database_hotspot_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "database_name": truncate_identifier(row.get("database_name"), NAME_MAX_LENGTH),
        "active_request_count": max(int(row.get("active_request_count") or 0), 0),
        "waiting_task_count": max(int(row.get("waiting_task_count") or 0), 0),
        "memory_grant_count": max(int(row.get("memory_grant_count") or 0), 0),
        "tempdb_internal_object_mb": round(
            max(float(row.get("tempdb_internal_object_mb") or 0.0), 0.0), 2
        ),
        "tempdb_user_object_mb": round(
            max(float(row.get("tempdb_user_object_mb") or 0.0), 0.0), 2
        ),
        "dominant_wait_type": str(row.get("dominant_wait_type") or "NONE"),
    }
