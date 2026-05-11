"""Implementation of the get_tempdb_usage tool."""

from __future__ import annotations

from typing import Any

import mcp.types as types

from sql_tshooter.db import DatabaseClient
from sql_tshooter.tools.common import collected_at_utc, truncate_text


TOOL_NAME = "get_tempdb_usage"
QUERY_TEXT_MAX_LENGTH = 220

QUERY = """
SELECT TOP (20)
    CAST(ssu.session_id AS int) AS session_id,
    CAST(
        (ssu.internal_objects_alloc_page_count - ssu.internal_objects_dealloc_page_count)
        * 8.0 / 1024 AS float
    ) AS internal_object_mb,
    CAST(
        (ssu.user_objects_alloc_page_count - ssu.user_objects_dealloc_page_count)
        * 8.0 / 1024 AS float
    ) AS user_object_mb,
    CAST(ISNULL(er.wait_type, '') AS nvarchar(120)) AS wait_type,
    CAST(st.text AS nvarchar(max)) AS query_text
FROM sys.dm_db_session_space_usage AS ssu
LEFT JOIN sys.dm_exec_requests AS er
    ON ssu.session_id = er.session_id
OUTER APPLY sys.dm_exec_sql_text(er.sql_handle) AS st
WHERE ssu.session_id <> @@SPID
ORDER BY
    (ssu.internal_objects_alloc_page_count - ssu.internal_objects_dealloc_page_count)
        + (ssu.user_objects_alloc_page_count - ssu.user_objects_dealloc_page_count) DESC,
    ssu.session_id ASC;
""".strip()


def build_tool() -> types.Tool:
    return types.Tool(
        name=TOOL_NAME,
        description="Return the top TempDB consumers with summarized spill indicators.",
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
                "total_internal_object_mb": {"type": "number"},
                "total_user_object_mb": {"type": "number"},
                "tempdb_usage": {
                    "type": "array",
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "properties": {
                            "session_id": {"type": "integer"},
                            "internal_object_mb": {"type": "number"},
                            "user_object_mb": {"type": "number"},
                            "spill_indicator": {"type": "string"},
                            "truncated_query_text": {"type": "string"},
                        },
                        "required": [
                            "session_id",
                            "internal_object_mb",
                            "user_object_mb",
                            "spill_indicator",
                            "truncated_query_text",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "collected_at_utc",
                "interpretation_hint",
                "total_internal_object_mb",
                "total_user_object_mb",
                "tempdb_usage",
            ],
            "additionalProperties": False,
        },
    )


async def execute(db_client: DatabaseClient) -> dict[str, Any]:
    rows = await db_client.fetch_all(QUERY)
    usage_rows = [_normalize_tempdb_row(row) for row in rows]
    usage_rows.sort(
        key=lambda row: (
            -(row["internal_object_mb"] + row["user_object_mb"]),
            row["session_id"],
        )
    )
    top_rows = usage_rows[:10]
    return {
        "collected_at_utc": collected_at_utc(),
        "interpretation_hint": (
            "Large internal object usage often points to spills or TempDB-heavy workspace operations."
        ),
        "total_internal_object_mb": round(sum(row["internal_object_mb"] for row in usage_rows), 2),
        "total_user_object_mb": round(sum(row["user_object_mb"] for row in usage_rows), 2),
        "tempdb_usage": top_rows,
    }


def _normalize_tempdb_row(row: dict[str, Any]) -> dict[str, Any]:
    internal_mb = round(max(float(row["internal_object_mb"]), 0.0), 2)
    user_mb = round(max(float(row["user_object_mb"]), 0.0), 2)
    wait_type = str(row["wait_type"] or "").upper()
    spill_indicator = "none"
    if internal_mb >= 32 or wait_type in {"RESOURCE_SEMAPHORE", "IO_COMPLETION"}:
        spill_indicator = "possible"
    if internal_mb >= 128:
        spill_indicator = "likely"

    return {
        "session_id": int(row["session_id"]),
        "internal_object_mb": internal_mb,
        "user_object_mb": user_mb,
        "spill_indicator": spill_indicator,
        "truncated_query_text": truncate_text(row["query_text"], QUERY_TEXT_MAX_LENGTH),
    }
