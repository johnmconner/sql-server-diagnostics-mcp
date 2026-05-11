"""Implementation of the get_server_info tool."""

from __future__ import annotations

from typing import Any

import mcp.types as types

from sql_tshooter.db import DatabaseClient
from sql_tshooter.errors import ToolExecutionError


TOOL_NAME = "get_server_info"

QUERY = """
SELECT
    CAST(SERVERPROPERTY('ServerName') AS nvarchar(128)) AS server_name,
    CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(128)) AS sql_version,
    CAST(SERVERPROPERTY('Edition') AS nvarchar(128)) AS edition,
    DATEDIFF(SECOND, sqlserver_start_time, SYSDATETIME()) AS uptime_seconds,
    CAST((
        SELECT value_in_use
        FROM sys.configurations
        WHERE name = 'max server memory (MB)'
    ) AS int) AS max_server_memory_mb,
    CAST(cpu_count AS int) AS cpu_count
FROM sys.dm_os_sys_info;
""".strip()


def build_tool() -> types.Tool:
    return types.Tool(
        name=TOOL_NAME,
        description="Return basic SQL Server version, uptime, memory, and CPU metadata.",
        inputSchema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        outputSchema={
            "type": "object",
            "properties": {
                "server_name": {"type": "string"},
                "sql_version": {"type": "string"},
                "edition": {"type": "string"},
                "uptime_seconds": {"type": "integer"},
                "max_server_memory_mb": {"type": "integer"},
                "cpu_count": {"type": "integer"},
            },
            "required": [
                "server_name",
                "sql_version",
                "edition",
                "uptime_seconds",
                "max_server_memory_mb",
                "cpu_count",
            ],
            "additionalProperties": False,
        },
    )


async def execute(db_client: DatabaseClient) -> dict[str, Any]:
    rows = await db_client.fetch_all(QUERY)
    if len(rows) != 1:
        raise ToolExecutionError("Expected a single server metadata row from SQL Server.")

    row = rows[0]
    return {
        "server_name": str(row["server_name"]),
        "sql_version": str(row["sql_version"]),
        "edition": str(row["edition"]),
        "uptime_seconds": int(row["uptime_seconds"]),
        "max_server_memory_mb": int(row["max_server_memory_mb"]),
        "cpu_count": int(row["cpu_count"]),
    }

