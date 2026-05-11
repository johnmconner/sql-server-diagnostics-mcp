"""Implementation of the get_disk_latency tool."""

from __future__ import annotations

from typing import Any

import mcp.types as types

from sql_tshooter.db import DatabaseClient


TOOL_NAME = "get_disk_latency"

QUERY = """
SELECT TOP (10)
    CAST(DB_NAME(vfs.database_id) AS nvarchar(128)) AS database_name,
    CAST(SUM(vfs.io_stall_read_ms) AS bigint) AS total_read_stall_ms,
    CAST(SUM(vfs.num_of_reads) AS bigint) AS total_reads,
    CAST(SUM(vfs.io_stall_write_ms) AS bigint) AS total_write_stall_ms,
    CAST(SUM(vfs.num_of_writes) AS bigint) AS total_writes
FROM sys.dm_io_virtual_file_stats(NULL, NULL) AS vfs
GROUP BY vfs.database_id
ORDER BY
    CASE
        WHEN SUM(vfs.num_of_reads) > 0
        THEN SUM(vfs.io_stall_read_ms) * 1.0 / SUM(vfs.num_of_reads)
        ELSE 0
    END DESC,
    CASE
        WHEN SUM(vfs.num_of_writes) > 0
        THEN SUM(vfs.io_stall_write_ms) * 1.0 / SUM(vfs.num_of_writes)
        ELSE 0
    END DESC;
""".strip()


def build_tool() -> types.Tool:
    return types.Tool(
        name=TOOL_NAME,
        description="Return the worst SQL Server database read and write latency summaries.",
        inputSchema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        outputSchema={
            "type": "object",
            "properties": {
                "disk_latency": {
                    "type": "array",
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "properties": {
                            "database_name": {"type": "string"},
                            "avg_read_ms": {"type": "number"},
                            "avg_write_ms": {"type": "number"},
                        },
                        "required": [
                            "database_name",
                            "avg_read_ms",
                            "avg_write_ms",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["disk_latency"],
            "additionalProperties": False,
        },
    )


async def execute(db_client: DatabaseClient) -> dict[str, Any]:
    rows = await db_client.fetch_all(QUERY)
    latency_rows = [_normalize_latency_row(row) for row in rows]
    latency_rows.sort(
        key=lambda row: (-row["avg_read_ms"], -row["avg_write_ms"], row["database_name"])
    )
    return {"disk_latency": latency_rows[:10]}


def _normalize_latency_row(row: dict[str, Any]) -> dict[str, Any]:
    total_reads = max(int(row["total_reads"]), 0)
    total_writes = max(int(row["total_writes"]), 0)
    total_read_stall_ms = max(float(row["total_read_stall_ms"]), 0.0)
    total_write_stall_ms = max(float(row["total_write_stall_ms"]), 0.0)
    avg_read_ms = total_read_stall_ms / total_reads if total_reads else 0.0
    avg_write_ms = total_write_stall_ms / total_writes if total_writes else 0.0
    return {
        "database_name": str(row["database_name"] or "unknown"),
        "avg_read_ms": round(avg_read_ms, 2),
        "avg_write_ms": round(avg_write_ms, 2),
    }
