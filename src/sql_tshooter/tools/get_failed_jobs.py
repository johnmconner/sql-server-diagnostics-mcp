"""Implementation of the get_failed_jobs tool."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import mcp.types as types

from sql_tshooter.db import DatabaseClient


TOOL_NAME = "get_failed_jobs"

QUERY = """
SELECT TOP (10)
    CAST(j.name AS nvarchar(128)) AS job_name,
    msdb.dbo.agent_datetime(h.run_date, h.run_time) AS last_run_time,
    CAST(h.message AS nvarchar(4000)) AS failure_message
FROM msdb.dbo.sysjobs AS j
JOIN msdb.dbo.sysjobhistory AS h
    ON j.job_id = h.job_id
WHERE h.step_id = 0
  AND h.run_status = 0
ORDER BY msdb.dbo.agent_datetime(h.run_date, h.run_time) DESC;
""".strip()


def build_tool() -> types.Tool:
    return types.Tool(
        name=TOOL_NAME,
        description="Return the most recent failed SQL Agent jobs.",
        inputSchema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        outputSchema={
            "type": "object",
            "properties": {
                "failed_jobs": {
                    "type": "array",
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "properties": {
                            "job_name": {"type": "string"},
                            "last_run_time": {"type": "string"},
                            "failure_message": {"type": "string"},
                        },
                        "required": [
                            "job_name",
                            "last_run_time",
                            "failure_message",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["failed_jobs"],
            "additionalProperties": False,
        },
    )


async def execute(db_client: DatabaseClient) -> dict[str, Any]:
    rows = await db_client.fetch_all(QUERY)
    failed_jobs = [_normalize_failed_job_row(row) for row in rows]
    return {"failed_jobs": failed_jobs[:10]}


def _normalize_failed_job_row(row: dict[str, Any]) -> dict[str, Any]:
    failure_message = str(row["failure_message"] or "").strip()
    return {
        "job_name": str(row["job_name"]),
        "last_run_time": _normalize_datetime(row["last_run_time"]),
        "failure_message": failure_message or "No failure message recorded",
    }


def _normalize_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)
