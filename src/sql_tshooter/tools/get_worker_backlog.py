"""Implementation of the get_worker_backlog tool."""

from __future__ import annotations

from typing import Any

import mcp.types as types

from sql_tshooter.db import DatabaseClient
from sql_tshooter.tools.common import collected_at_utc


TOOL_NAME = "get_worker_backlog"

QUERY = """
SELECT
    CAST(s.scheduler_id AS int) AS scheduler_id,
    CAST(s.runnable_tasks_count AS int) AS runnable_tasks_count,
    CAST(s.active_workers_count AS int) AS active_workers_count,
    CAST(s.current_workers_count AS int) AS current_workers_count,
    CAST(s.pending_disk_io_count AS int) AS pending_disk_io_count,
    CAST(s.status AS nvarchar(60)) AS status
FROM sys.dm_os_schedulers AS s
WHERE s.status IN ('VISIBLE ONLINE', 'VISIBLE OFFLINE')
  AND s.scheduler_id < 255
ORDER BY s.scheduler_id ASC;
""".strip()


def build_tool() -> types.Tool:
    return types.Tool(
        name=TOOL_NAME,
        description="Return scheduler and worker backlog signals for real-time SQL pressure triage.",
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
                "pressure_level": {"type": "string"},
                "online_scheduler_count": {"type": "integer"},
                "total_runnable_tasks": {"type": "integer"},
                "max_runnable_tasks_on_single_scheduler": {"type": "integer"},
                "total_active_workers": {"type": "integer"},
                "total_current_workers": {"type": "integer"},
                "pending_disk_io_count": {"type": "integer"},
                "hot_schedulers": {
                    "type": "array",
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "properties": {
                            "scheduler_id": {"type": "integer"},
                            "runnable_tasks_count": {"type": "integer"},
                            "active_workers_count": {"type": "integer"},
                            "current_workers_count": {"type": "integer"},
                            "pending_disk_io_count": {"type": "integer"},
                        },
                        "required": [
                            "scheduler_id",
                            "runnable_tasks_count",
                            "active_workers_count",
                            "current_workers_count",
                            "pending_disk_io_count",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "collected_at_utc",
                "interpretation_hint",
                "pressure_level",
                "online_scheduler_count",
                "total_runnable_tasks",
                "max_runnable_tasks_on_single_scheduler",
                "total_active_workers",
                "total_current_workers",
                "pending_disk_io_count",
                "hot_schedulers",
            ],
            "additionalProperties": False,
        },
    )


async def execute(db_client: DatabaseClient) -> dict[str, Any]:
    rows = await db_client.fetch_all(QUERY)
    normalized_rows = [_normalize_scheduler_row(row) for row in rows]
    online_rows = [row for row in normalized_rows if row["status"] == "VISIBLE ONLINE"]

    total_runnable_tasks = sum(row["runnable_tasks_count"] for row in online_rows)
    max_runnable = max((row["runnable_tasks_count"] for row in online_rows), default=0)
    total_active_workers = sum(row["active_workers_count"] for row in online_rows)
    total_current_workers = sum(row["current_workers_count"] for row in online_rows)
    pending_disk_io_count = sum(row["pending_disk_io_count"] for row in online_rows)
    online_scheduler_count = len(online_rows)

    hot_schedulers = sorted(
        online_rows,
        key=lambda row: (
            -row["runnable_tasks_count"],
            -row["active_workers_count"],
            -row["pending_disk_io_count"],
            row["scheduler_id"],
        ),
    )[:5]

    pressure_level = _derive_pressure_level(
        online_scheduler_count,
        total_runnable_tasks,
        max_runnable,
        total_active_workers,
        total_current_workers,
        pending_disk_io_count,
    )

    return {
        "collected_at_utc": collected_at_utc(),
        "interpretation_hint": (
            "Runnable task buildup across visible online schedulers is a stronger pressure signal than isolated slow queries."
        ),
        "pressure_level": pressure_level,
        "online_scheduler_count": online_scheduler_count,
        "total_runnable_tasks": total_runnable_tasks,
        "max_runnable_tasks_on_single_scheduler": max_runnable,
        "total_active_workers": total_active_workers,
        "total_current_workers": total_current_workers,
        "pending_disk_io_count": pending_disk_io_count,
        "hot_schedulers": [
            {
                "scheduler_id": row["scheduler_id"],
                "runnable_tasks_count": row["runnable_tasks_count"],
                "active_workers_count": row["active_workers_count"],
                "current_workers_count": row["current_workers_count"],
                "pending_disk_io_count": row["pending_disk_io_count"],
            }
            for row in hot_schedulers
        ],
    }


def _normalize_scheduler_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "scheduler_id": int(row["scheduler_id"]),
        "runnable_tasks_count": max(int(row.get("runnable_tasks_count") or 0), 0),
        "active_workers_count": max(int(row.get("active_workers_count") or 0), 0),
        "current_workers_count": max(int(row.get("current_workers_count") or 0), 0),
        "pending_disk_io_count": max(int(row.get("pending_disk_io_count") or 0), 0),
        "status": str(row.get("status") or "UNKNOWN").upper(),
    }


def _derive_pressure_level(
    online_scheduler_count: int,
    total_runnable_tasks: int,
    max_runnable: int,
    total_active_workers: int,
    total_current_workers: int,
    pending_disk_io_count: int,
) -> str:
    worker_utilization = (
        total_active_workers / total_current_workers if total_current_workers else 0.0
    )
    if (
        total_runnable_tasks >= max(8, online_scheduler_count * 2)
        or max_runnable >= 4
        or (worker_utilization >= 0.9 and total_runnable_tasks > 0)
    ):
        return "high"
    if total_runnable_tasks > 0 or pending_disk_io_count > 0 or worker_utilization >= 0.75:
        return "medium"
    return "low"
