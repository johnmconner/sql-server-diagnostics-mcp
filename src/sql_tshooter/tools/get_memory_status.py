"""Implementation of the get_memory_status tool."""

from __future__ import annotations

from typing import Any

import mcp.types as types

from sql_tshooter.db import DatabaseClient
from sql_tshooter.errors import ToolExecutionError


TOOL_NAME = "get_memory_status"

QUERY = """
SELECT
    CAST(osi.committed_target_kb / 1024 AS int) AS target_memory_mb,
    CAST(osi.committed_kb / 1024 AS int) AS total_memory_mb,
    CAST(pc.page_life_expectancy AS int) AS page_life_expectancy,
    CAST(pc.memory_grants_pending AS int) AS memory_grants_pending
FROM sys.dm_os_sys_info AS osi
CROSS JOIN (
    SELECT
        MAX(CASE WHEN counter_name = 'Page life expectancy' THEN cntr_value END) AS page_life_expectancy,
        MAX(CASE WHEN counter_name = 'Memory Grants Pending' THEN cntr_value END) AS memory_grants_pending
    FROM sys.dm_os_performance_counters
    WHERE counter_name IN ('Page life expectancy', 'Memory Grants Pending')
) AS pc;
""".strip()


def build_tool() -> types.Tool:
    return types.Tool(
        name=TOOL_NAME,
        description="Return a SQL Server memory pressure summary.",
        inputSchema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        outputSchema={
            "type": "object",
            "properties": {
                "target_memory_mb": {"type": "integer"},
                "total_memory_mb": {"type": "integer"},
                "page_life_expectancy": {"type": "integer"},
                "memory_grants_pending": {"type": "integer"},
            },
            "required": [
                "target_memory_mb",
                "total_memory_mb",
                "page_life_expectancy",
                "memory_grants_pending",
            ],
            "additionalProperties": False,
        },
    )


async def execute(db_client: DatabaseClient) -> dict[str, Any]:
    rows = await db_client.fetch_all(QUERY)
    if len(rows) != 1:
        raise ToolExecutionError("Expected a single memory status row from SQL Server.")

    row = rows[0]
    return {
        "target_memory_mb": max(int(row["target_memory_mb"] or 0), 0),
        "total_memory_mb": max(int(row["total_memory_mb"] or 0), 0),
        "page_life_expectancy": max(int(row["page_life_expectancy"] or 0), 0),
        "memory_grants_pending": max(int(row["memory_grants_pending"] or 0), 0),
    }
