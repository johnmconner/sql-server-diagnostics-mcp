"""Implementation of the get_database_sizes tool."""

from __future__ import annotations

from typing import Any

import mcp.types as types

from sql_tshooter.db import DatabaseClient


TOOL_NAME = "get_database_sizes"

QUERY = """
SELECT
    CAST(d.name AS nvarchar(128)) AS database_name,
    CAST(COALESCE(SUM(mf.size), 0) * 8.0 / 1024 / 1024 AS float) AS total_size_gb,
    CAST(
        COALESCE(SUM(CASE WHEN mf.type_desc = 'ROWS' THEN mf.size ELSE 0 END), 0)
        * 8.0 / 1024 / 1024
        AS float
    ) AS used_space_gb,
    CAST(d.recovery_model_desc AS nvarchar(60)) AS recovery_model
FROM sys.databases AS d
LEFT JOIN sys.master_files AS mf
    ON d.database_id = mf.database_id
WHERE d.state = 0
GROUP BY
    d.name,
    d.recovery_model_desc
ORDER BY total_size_gb DESC, d.name ASC;
""".strip()


def build_tool() -> types.Tool:
    return types.Tool(
        name=TOOL_NAME,
        description="Return SQL Server database sizes and recovery models.",
        inputSchema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        outputSchema={
            "type": "object",
            "properties": {
                "database_sizes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "database_name": {"type": "string"},
                            "total_size_gb": {"type": "number"},
                            "used_space_gb": {"type": "number"},
                            "recovery_model": {"type": "string"},
                        },
                        "required": [
                            "database_name",
                            "total_size_gb",
                            "used_space_gb",
                            "recovery_model",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["database_sizes"],
            "additionalProperties": False,
        },
    )


async def execute(db_client: DatabaseClient) -> dict[str, Any]:
    rows = await db_client.fetch_all(QUERY)
    databases = [_normalize_database_row(row) for row in rows]
    databases.sort(
        key=lambda row: (-row["total_size_gb"], row["database_name"].lower())
    )
    return {"database_sizes": databases}


def _normalize_database_row(row: dict[str, Any]) -> dict[str, Any]:
    total_size_gb = max(float(row["total_size_gb"]), 0.0)
    used_space_gb = min(max(float(row["used_space_gb"]), 0.0), total_size_gb)
    return {
        "database_name": str(row["database_name"]),
        "total_size_gb": round(total_size_gb, 2),
        "used_space_gb": round(used_space_gb, 2),
        "recovery_model": str(row["recovery_model"]),
    }
