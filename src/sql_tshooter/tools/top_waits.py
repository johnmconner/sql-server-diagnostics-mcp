"""Implementation of the get_top_waits tool."""

from __future__ import annotations

from typing import Any

import mcp.types as types

from sql_tshooter.db import DatabaseClient


TOOL_NAME = "get_top_waits"

BENIGN_WAITS = {
    "BROKER_EVENTHANDLER",
    "BROKER_RECEIVE_WAITFOR",
    "BROKER_TASK_STOP",
    "BROKER_TO_FLUSH",
    "BROKER_TRANSMITTER",
    "CHECKPOINT_QUEUE",
    "CHKPT",
    "CLR_AUTO_EVENT",
    "CLR_MANUAL_EVENT",
    "DIRTY_PAGE_POLL",
    "DISPATCHER_QUEUE_SEMAPHORE",
    "FT_IFTS_SCHEDULER_IDLE_WAIT",
    "HADR_FILESTREAM_IOMGR_IOCOMPLETION",
    "HADR_LOGCAPTURE_WAIT",
    "HADR_NOTIFICATION_DEQUEUE",
    "HADR_TIMER_TASK",
    "HADR_WORK_QUEUE",
    "KSOURCE_WAKEUP",
    "LAZYWRITER_SLEEP",
    "LOGMGR_QUEUE",
    "ONDEMAND_TASK_QUEUE",
    "PWAIT_ALL_COMPONENTS_INITIALIZED",
    "QDS_PERSIST_TASK_MAIN_LOOP_SLEEP",
    "QDS_ASYNC_QUEUE",
    "REQUEST_FOR_DEADLOCK_SEARCH",
    "RESOURCE_QUEUE",
    "SERVER_IDLE_CHECK",
    "SLEEP_BPOOL_FLUSH",
    "SLEEP_DBSTARTUP",
    "SLEEP_DCOMSTARTUP",
    "SLEEP_MASTERDBREADY",
    "SLEEP_MASTERMDREADY",
    "SLEEP_MASTERUPGRADED",
    "SLEEP_MSDBSTARTUP",
    "SLEEP_SYSTEMTASK",
    "SLEEP_TASK",
    "SLEEP_TEMPDBSTARTUP",
    "SNI_HTTP_ACCEPT",
    "SOS_WORK_DISPATCHER",
    "SP_SERVER_DIAGNOSTICS_SLEEP",
    "SQLTRACE_BUFFER_FLUSH",
    "WAIT_XTP_RECOVERY",
    "WAITFOR",
    "XE_DISPATCHER_JOIN",
    "XE_DISPATCHER_WAIT",
    "XE_TIMER_EVENT",
}

QUERY = """
SELECT TOP (50)
    wait_type,
    CAST(wait_time_ms / 1000.0 AS float) AS wait_seconds,
    CAST(signal_wait_time_ms AS bigint) AS signal_wait_time_ms,
    CAST(wait_time_ms - signal_wait_time_ms AS bigint) AS resource_wait_time_ms
FROM sys.dm_os_wait_stats
WHERE wait_time_ms > 0
ORDER BY wait_time_ms DESC;
""".strip()


def build_tool() -> types.Tool:
    return types.Tool(
        name=TOOL_NAME,
        description="Return the top five meaningful SQL wait statistics.",
        inputSchema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        outputSchema={
            "type": "object",
            "properties": {
                "top_waits": {
                    "type": "array",
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "properties": {
                            "wait_type": {"type": "string"},
                            "wait_seconds": {"type": "number"},
                            "signal_wait_percent": {"type": "number"},
                            "resource_wait_percent": {"type": "number"},
                        },
                        "required": [
                            "wait_type",
                            "wait_seconds",
                            "signal_wait_percent",
                            "resource_wait_percent",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["top_waits"],
            "additionalProperties": False,
        },
    )


async def execute(db_client: DatabaseClient) -> dict[str, Any]:
    rows = await db_client.fetch_all(QUERY)
    filtered = [
        _normalize_wait_row(row)
        for row in rows
        if str(row["wait_type"]).upper() not in BENIGN_WAITS
    ]
    return {"top_waits": filtered[:5]}


def _normalize_wait_row(row: dict[str, Any]) -> dict[str, Any]:
    signal_ms = max(int(row["signal_wait_time_ms"]), 0)
    resource_ms = max(int(row["resource_wait_time_ms"]), 0)
    total_ms = signal_ms + resource_ms

    signal_percent = round((signal_ms / total_ms) * 100, 2) if total_ms else 0.0
    resource_percent = round((resource_ms / total_ms) * 100, 2) if total_ms else 0.0

    return {
        "wait_type": str(row["wait_type"]),
        "wait_seconds": round(float(row["wait_seconds"]), 2),
        "signal_wait_percent": signal_percent,
        "resource_wait_percent": resource_percent,
    }

