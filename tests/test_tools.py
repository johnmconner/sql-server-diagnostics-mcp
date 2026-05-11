from datetime import datetime

import pytest

from sql_tshooter.config import Settings
from sql_tshooter.db import DatabaseClient
from sql_tshooter.errors import ToolExecutionError
from sql_tshooter.toolkit import get_exposed_tool_specs
from sql_tshooter.tools import (
    get_active_requests,
    get_blocking_details,
    get_blocking_sessions,
    get_connection_pressure,
    get_database_hotspots,
    get_database_sizes,
    get_disk_latency,
    get_expensive_queries,
    get_failed_jobs,
    get_lock_summary,
    get_memory_status,
    get_plan_cache_summary,
    get_query_memory_grants,
    get_query_plan_summary,
    get_query_store_plan_variants,
    get_query_store_query_detail,
    get_query_store_regressions,
    get_query_store_top_queries,
    get_session_pressure,
    get_table_scan_summary,
    get_tempdb_usage,
    get_wait_stats_by_query,
    get_waiting_tasks,
    get_worker_backlog,
    server_info,
    top_waits,
)


class StubDatabaseClient(DatabaseClient):
    def __init__(self, rows):
        super().__init__(Settings(host="stub", auth_mode="windows"))
        self._rows = rows

    async def fetch_all(self, query: str, params=None):
        return list(self._rows)


PLAN_XML = """
<ShowPlanXML xmlns="http://schemas.microsoft.com/sqlserver/2004/07/showplan">
  <BatchSequence>
    <Batch>
      <Statements>
        <StmtSimple>
          <QueryPlan>
            <MissingIndexes>
              <MissingIndexGroup Impact="98.0" />
            </MissingIndexes>
            <RelOp PhysicalOp="Index Scan" EstimatedTotalSubtreeCost="7.5" EstimateRows="120" Parallel="true">
              <IndexScan>
                <Object Database="[AppDb]" Schema="[dbo]" Table="[Orders]" Index="[IX_Orders_Status]" />
              </IndexScan>
            </RelOp>
            <RelOp PhysicalOp="Hash Match" EstimatedTotalSubtreeCost="4.1" EstimateRows="12">
              <Hash />
            </RelOp>
            <RelOp PhysicalOp="Sort" EstimatedTotalSubtreeCost="2.3" EstimateRows="12">
              <Sort />
            </RelOp>
            <RelOp PhysicalOp="Table Scan" EstimatedTotalSubtreeCost="1.2" EstimateRows="50">
              <TableScan>
                <Object Database="[AppDb]" Schema="[dbo]" Table="[Audit]" />
              </TableScan>
            </RelOp>
          </QueryPlan>
        </StmtSimple>
      </Statements>
    </Batch>
  </BatchSequence>
</ShowPlanXML>
""".strip()


async def test_get_server_info_normalizes_output() -> None:
    db_client = StubDatabaseClient(
        [
            {
                "server_name": "prod-sql-01",
                "sql_version": "16.0.1000.6",
                "edition": "Developer Edition",
                "uptime_seconds": 3600,
                "max_server_memory_mb": 4096,
                "cpu_count": 8,
            }
        ]
    )

    result = await server_info.execute(db_client)

    assert result == {
        "server_name": "prod-sql-01",
        "sql_version": "16.0.1000.6",
        "edition": "Developer Edition",
        "uptime_seconds": 3600,
        "max_server_memory_mb": 4096,
        "cpu_count": 8,
    }


def test_primary_tool_descriptions_include_triage_guidance() -> None:
    specs = get_exposed_tool_specs()

    assert "Primary live triage" in (specs["get_active_requests"].definition.description or "")
    assert "Primary instance health" in (specs["get_server_info"].definition.description or "")
    assert "Historical or follow-up" in (specs["get_plan_cache_summary"].definition.description or "")
    assert "Do not call this early for vague symptoms." in (
        specs["get_query_plan_summary"].definition.description or ""
    )


async def test_get_top_waits_filters_benign_rows_and_limits_results() -> None:
    db_client = StubDatabaseClient(
        [
            {
                "wait_type": "LAZYWRITER_SLEEP",
                "wait_seconds": 999.0,
                "signal_wait_time_ms": 10,
                "resource_wait_time_ms": 90,
            },
            {
                "wait_type": "PAGEIOLATCH_SH",
                "wait_seconds": 40.0,
                "signal_wait_time_ms": 100,
                "resource_wait_time_ms": 900,
            },
            {
                "wait_type": "CXCONSUMER",
                "wait_seconds": 35.0,
                "signal_wait_time_ms": 200,
                "resource_wait_time_ms": 800,
            },
            {
                "wait_type": "LCK_M_X",
                "wait_seconds": 30.0,
                "signal_wait_time_ms": 50,
                "resource_wait_time_ms": 950,
            },
            {
                "wait_type": "WRITELOG",
                "wait_seconds": 25.0,
                "signal_wait_time_ms": 250,
                "resource_wait_time_ms": 750,
            },
            {
                "wait_type": "SOS_SCHEDULER_YIELD",
                "wait_seconds": 20.0,
                "signal_wait_time_ms": 600,
                "resource_wait_time_ms": 400,
            },
            {
                "wait_type": "ASYNC_NETWORK_IO",
                "wait_seconds": 15.0,
                "signal_wait_time_ms": 300,
                "resource_wait_time_ms": 700,
            },
        ]
    )

    result = await top_waits.execute(db_client)

    assert len(result["top_waits"]) == 5
    assert all(row["wait_type"] != "LAZYWRITER_SLEEP" for row in result["top_waits"])
    assert result["top_waits"][0] == {
        "wait_type": "PAGEIOLATCH_SH",
        "wait_seconds": 40.0,
        "signal_wait_percent": 10.0,
        "resource_wait_percent": 90.0,
    }


async def test_get_active_requests_normalizes_and_truncates_rows() -> None:
    long_text = "SELECT * FROM dbo.WorkQueue " * 30
    db_client = StubDatabaseClient(
        [
            {
                "session_id": 58,
                "blocking_session_id": 61,
                "status": "running",
                "command": "SELECT",
                "database_name": "AppDb",
                "wait_type": "LCK_M_S",
                "wait_seconds": 2.0,
                "cpu_time_ms": 150,
                "logical_reads": 2200,
                "elapsed_seconds": 15.678,
                "host_name": "app01",
                "login_name": "svc_app",
                "program_name": "worker",
                "query_text": long_text,
            },
            {
                "session_id": 59,
                "blocking_session_id": 0,
                "status": None,
                "command": None,
                "database_name": None,
                "wait_type": None,
                "wait_seconds": 0.0,
                "cpu_time_ms": 50,
                "logical_reads": 100,
                "elapsed_seconds": 5.0,
                "host_name": None,
                "login_name": None,
                "program_name": None,
                "query_text": "SELECT 1",
            },
        ]
    )

    result = await get_active_requests.execute(db_client)

    assert result["active_requests"][0]["session_id"] == 58
    assert result["active_requests"][0]["duration_seconds"] == 15.68
    assert result["active_requests"][0]["truncated_query_text"].endswith("...")
    assert result["active_requests"][1] == {
        "session_id": 59,
        "blocking_session_id": 0,
        "status": "unknown",
        "command": "unknown",
        "database_name": "unknown",
        "wait_type": "NONE",
        "duration_seconds": 5.0,
        "cpu_time_ms": 50,
        "logical_reads": 100,
        "host_name": "",
        "login_name": "",
        "program_name": "",
        "truncated_query_text": "SELECT 1",
    }


async def test_get_blocking_sessions_filters_non_blocking_rows_and_limits_results() -> None:
    db_client = StubDatabaseClient(
        [
            {
                "blocking_session_id": 55,
                "blocked_session_id": 81,
                "duration_seconds": 14.321,
                "wait_type": "LCK_M_X",
                "database_name": "Sales",
            },
            {
                "blocking_session_id": 0,
                "blocked_session_id": 82,
                "duration_seconds": 99.0,
                "wait_type": "CXPACKET",
                "database_name": None,
            },
        ]
        + [
            {
                "blocking_session_id": 100 + index,
                "blocked_session_id": 200 + index,
                "duration_seconds": float(index),
                "wait_type": "LCK_M_S",
                "database_name": "AppDb",
            }
            for index in range(1, 12)
        ]
    )

    result = await get_blocking_sessions.execute(db_client)

    assert len(result["blocking_sessions"]) == 10
    assert all(row["blocking_session_id"] > 0 for row in result["blocking_sessions"])
    assert result["blocking_sessions"][0] == {
        "blocking_session_id": 55,
        "blocked_session_id": 81,
        "duration_seconds": 14.32,
        "wait_type": "LCK_M_X",
        "database_name": "Sales",
    }


async def test_get_blocking_details_includes_context_and_limits_results() -> None:
    db_client = StubDatabaseClient(
        [
            {
                "blocking_session_id": 55,
                "blocked_session_id": 81,
                "wait_type": "LCK_M_X",
                "wait_seconds": 14.321,
                "database_name": "Sales",
                "resource_description": "KEY: 5:7205759401",
                "lock_mode": "X",
                "blocker_host_name": "sql01",
                "blocker_login_name": "sa",
                "blocker_program_name": "sqlcmd",
                "blocked_host_name": "app01",
                "blocked_login_name": "svc_app",
                "blocked_program_name": "worker",
                "blocker_query_text": "UPDATE dbo.Orders SET Status = 1",
                "blocked_query_text": "SELECT * FROM dbo.Orders WHERE Id = 1",
            },
            {
                "blocking_session_id": 0,
                "blocked_session_id": 82,
                "wait_type": "CXPACKET",
                "wait_seconds": 99.0,
                "database_name": None,
                "resource_description": None,
                "lock_mode": None,
                "blocker_host_name": None,
                "blocker_login_name": None,
                "blocker_program_name": None,
                "blocked_host_name": None,
                "blocked_login_name": None,
                "blocked_program_name": None,
                "blocker_query_text": None,
                "blocked_query_text": None,
            },
        ]
        + [
            {
                "blocking_session_id": 100 + index,
                "blocked_session_id": 200 + index,
                "wait_type": "LCK_M_S",
                "wait_seconds": float(index),
                "database_name": "AppDb",
                "resource_description": "",
                "lock_mode": "S",
                "blocker_host_name": "",
                "blocker_login_name": "",
                "blocker_program_name": "",
                "blocked_host_name": "",
                "blocked_login_name": "",
                "blocked_program_name": "",
                "blocker_query_text": "",
                "blocked_query_text": "",
            }
            for index in range(1, 12)
        ]
    )

    result = await get_blocking_details.execute(db_client)

    assert len(result["blocking_details"]) == 10
    assert result["blocking_details"][0]["blocking_session_id"] == 55
    assert result["blocking_details"][0]["lock_mode"] == "X"
    assert result["blocking_details"][0]["blocked_program_name"] == "worker"


async def test_get_expensive_queries_computes_averages_and_truncates_text() -> None:
    long_text = "SELECT * FROM dbo.BigTable " * 40
    db_client = StubDatabaseClient(
        [
            {
                "query_hash": 123456789,
                "total_worker_time": 500000,
                "total_elapsed_time": 1200000,
                "total_logical_reads": 1000,
                "execution_count": 5,
                "query_text": long_text,
            },
            {
                "query_hash": 987654321,
                "total_worker_time": 1000,
                "total_elapsed_time": 1000,
                "total_logical_reads": 10,
                "execution_count": 0,
                "query_text": "SELECT 1",
            },
        ]
    )

    result = await get_expensive_queries.execute(db_client)

    assert result["expensive_queries"][0]["query_hash"] == "123456789"
    assert result["expensive_queries"][0]["avg_cpu_ms"] == 100.0
    assert result["expensive_queries"][0]["avg_duration_ms"] == 240.0
    assert result["expensive_queries"][0]["truncated_query_text"].endswith("...")
    assert len(result["expensive_queries"][0]["truncated_query_text"]) == 300
    assert result["expensive_queries"][1]["avg_cpu_ms"] == 0.0


async def test_get_lock_summary_aggregates_and_sorts_rows() -> None:
    db_client = StubDatabaseClient(
        [
            {
                "session_id": 57,
                "database_name": "AppDb",
                "resource_type": "KEY",
                "request_mode": "X",
                "lock_count": 12,
                "host_name": "app01",
                "login_name": "svc_app",
                "program_name": "worker",
            },
            {
                "session_id": 12,
                "database_name": None,
                "resource_type": None,
                "request_mode": None,
                "lock_count": 2,
                "host_name": None,
                "login_name": None,
                "program_name": None,
            },
        ]
    )

    result = await get_lock_summary.execute(db_client)

    assert result["lock_summary"] == [
        {
            "session_id": 57,
            "database_name": "AppDb",
            "resource_type": "KEY",
            "request_mode": "X",
            "lock_count": 12,
            "host_name": "app01",
            "login_name": "svc_app",
            "program_name": "worker",
        },
        {
            "session_id": 12,
            "database_name": "unknown",
            "resource_type": "UNKNOWN",
            "request_mode": "UNKNOWN",
            "lock_count": 2,
            "host_name": "",
            "login_name": "",
            "program_name": "",
        },
    ]


async def test_get_database_sizes_normalizes_rows_without_state_filtering() -> None:
    db_client = StubDatabaseClient(
        [
            {
                "database_name": "MainDb",
                "total_size_gb": 25.234,
                "used_space_gb": 30.0,
                "recovery_model": "FULL",
            },
            {
                "database_name": "ArchiveDb",
                "total_size_gb": 10.0,
                "used_space_gb": 7.125,
                "recovery_model": "SIMPLE",
            },
        ]
    )

    result = await get_database_sizes.execute(db_client)

    assert result["database_sizes"] == [
        {
            "database_name": "MainDb",
            "total_size_gb": 25.23,
            "used_space_gb": 25.23,
            "recovery_model": "FULL",
        },
        {
            "database_name": "ArchiveDb",
            "total_size_gb": 10.0,
            "used_space_gb": 7.12,
            "recovery_model": "SIMPLE",
        },
    ]


async def test_get_connection_pressure_summarizes_session_concentration() -> None:
    db_client = StubDatabaseClient(
        [
            {
                "session_id": 51,
                "status": "sleeping",
                "login_name": "svc_app",
                "host_name": "app01",
                "program_name": "worker",
                "is_user_process": True,
            },
            {
                "session_id": 52,
                "status": "sleeping",
                "login_name": "svc_app",
                "host_name": "app01",
                "program_name": "worker",
                "is_user_process": True,
            },
            {
                "session_id": 53,
                "status": "running",
                "login_name": "svc_report",
                "host_name": "app02",
                "program_name": "reporter",
                "is_user_process": True,
            },
            {
                "session_id": 54,
                "status": "sleeping",
                "login_name": "sa",
                "host_name": "sql01",
                "program_name": "SSMS",
                "is_user_process": False,
            },
        ]
    )

    result = await get_connection_pressure.execute(db_client)

    assert result["total_user_sessions"] == 3
    assert result["active_user_sessions"] == 1
    assert result["sleeping_user_sessions"] == 2
    assert result["top_programs"][0] == {"name": "worker", "session_count": 2}


async def test_get_session_pressure_filters_trivial_sleepers_and_sorts_notable_rows() -> None:
    db_client = StubDatabaseClient(
        [
            {
                "session_id": 61,
                "status": "sleeping",
                "login_name": "svc_app",
                "host_name": "app01",
                "program_name": "worker",
                "database_name": "AppDb",
                "open_transaction_count": 1,
                "idle_seconds": 300,
                "request_status": None,
                "blocking_session_id": 0,
                "query_text": None,
            },
            {
                "session_id": 62,
                "status": "running",
                "login_name": "svc_report",
                "host_name": "app02",
                "program_name": "reporter",
                "database_name": "ReportDb",
                "open_transaction_count": 0,
                "idle_seconds": 0,
                "request_status": "suspended",
                "blocking_session_id": 71,
                "query_text": "SELECT * FROM dbo.ReportQueue",
            },
            {
                "session_id": 63,
                "status": "sleeping",
                "login_name": "svc_app",
                "host_name": "app03",
                "program_name": "worker",
                "database_name": "AppDb",
                "open_transaction_count": 0,
                "idle_seconds": 20,
                "request_status": None,
                "blocking_session_id": 0,
                "query_text": None,
            },
        ]
    )

    result = await get_session_pressure.execute(db_client)

    assert [row["session_id"] for row in result["notable_sessions"]] == [61, 62]
    assert result["notable_sessions"][0]["open_transaction_count"] == 1
    assert result["notable_sessions"][1]["blocking_session_id"] == 71


async def test_get_worker_backlog_derives_pressure_and_limits_hot_schedulers() -> None:
    db_client = StubDatabaseClient(
        [
            {
                "scheduler_id": 0,
                "runnable_tasks_count": 5,
                "active_workers_count": 20,
                "current_workers_count": 21,
                "pending_disk_io_count": 0,
                "status": "VISIBLE ONLINE",
            },
            {
                "scheduler_id": 1,
                "runnable_tasks_count": 4,
                "active_workers_count": 19,
                "current_workers_count": 20,
                "pending_disk_io_count": 0,
                "status": "VISIBLE ONLINE",
            },
            {
                "scheduler_id": 2,
                "runnable_tasks_count": 0,
                "active_workers_count": 5,
                "current_workers_count": 10,
                "pending_disk_io_count": 0,
                "status": "VISIBLE OFFLINE",
            },
        ]
    )

    result = await get_worker_backlog.execute(db_client)

    assert result["pressure_level"] == "high"
    assert result["online_scheduler_count"] == 2
    assert result["total_runnable_tasks"] == 9
    assert result["hot_schedulers"][0]["scheduler_id"] == 0


async def test_get_database_hotspots_aggregates_and_sorts_hot_databases() -> None:
    db_client = StubDatabaseClient(
        [
            {
                "database_name": "AppDb",
                "active_request_count": 5,
                "waiting_task_count": 3,
                "memory_grant_count": 2,
                "tempdb_internal_object_mb": 64.0,
                "tempdb_user_object_mb": 16.0,
                "dominant_wait_type": "LCK_M_X",
            },
            {
                "database_name": "ReportDb",
                "active_request_count": 2,
                "waiting_task_count": 1,
                "memory_grant_count": 4,
                "tempdb_internal_object_mb": 10.0,
                "tempdb_user_object_mb": 4.0,
                "dominant_wait_type": "RESOURCE_SEMAPHORE",
            },
            {
                "database_name": "master",
                "active_request_count": 0,
                "waiting_task_count": 0,
                "memory_grant_count": 0,
                "tempdb_internal_object_mb": 0.0,
                "tempdb_user_object_mb": 0.0,
                "dominant_wait_type": "NONE",
            },
        ]
    )

    result = await get_database_hotspots.execute(db_client)

    assert [row["database_name"] for row in result["database_hotspots"]] == ["AppDb", "ReportDb"]
    assert result["database_hotspots"][0]["dominant_wait_type"] == "LCK_M_X"


async def test_get_failed_jobs_formats_datetime_and_falls_back_message() -> None:
    db_client = StubDatabaseClient(
        [
            {
                "job_name": "Nightly ETL",
                "last_run_time": datetime(2026, 5, 8, 1, 2, 3),
                "failure_message": "Step failed",
            },
            {
                "job_name": "Cleanup",
                "last_run_time": "2026-05-08T02:00:00",
                "failure_message": "   ",
            },
        ]
    )

    result = await get_failed_jobs.execute(db_client)

    assert result["failed_jobs"] == [
        {
            "job_name": "Nightly ETL",
            "last_run_time": "2026-05-08T01:02:03",
            "failure_message": "Step failed",
        },
        {
            "job_name": "Cleanup",
            "last_run_time": "2026-05-08T02:00:00",
            "failure_message": "No failure message recorded",
        },
    ]


async def test_get_memory_status_normalizes_output() -> None:
    db_client = StubDatabaseClient(
        [
            {
                "target_memory_mb": 8192,
                "total_memory_mb": 6144,
                "page_life_expectancy": 700,
                "memory_grants_pending": 2,
            }
        ]
    )

    result = await get_memory_status.execute(db_client)

    assert result == {
        "target_memory_mb": 8192,
        "total_memory_mb": 6144,
        "page_life_expectancy": 700,
        "memory_grants_pending": 2,
    }


async def test_get_waiting_tasks_filters_benign_waits_and_truncates_text() -> None:
    long_text = "SELECT * FROM dbo.BlockedRows " * 20
    db_client = StubDatabaseClient(
        [
            {
                "session_id": 61,
                "blocking_session_id": 57,
                "wait_type": "LCK_M_U",
                "wait_seconds": 8.756,
                "resource_description": "OBJECT: 5:12345:0 ",
                "database_name": "AppDb",
                "status": "suspended",
                "host_name": "app01",
                "login_name": "svc_app",
                "program_name": "worker",
                "query_text": long_text,
            },
            {
                "session_id": 62,
                "blocking_session_id": 0,
                "wait_type": "LAZYWRITER_SLEEP",
                "wait_seconds": 900.0,
                "resource_description": "",
                "database_name": None,
                "status": None,
                "host_name": None,
                "login_name": None,
                "program_name": None,
                "query_text": None,
            },
        ]
    )

    result = await get_waiting_tasks.execute(db_client)

    assert len(result["waiting_tasks"]) == 1
    assert result["waiting_tasks"][0]["session_id"] == 61
    assert result["waiting_tasks"][0]["duration_seconds"] == 8.76
    assert result["waiting_tasks"][0]["truncated_query_text"].endswith("...")


async def test_get_memory_status_raises_on_unexpected_row_count() -> None:
    db_client = StubDatabaseClient([])

    with pytest.raises(ToolExecutionError):
        await get_memory_status.execute(db_client)


async def test_get_disk_latency_computes_averages_and_limits_results() -> None:
    db_client = StubDatabaseClient(
        [
            {
                "database_name": "Warehouse",
                "total_read_stall_ms": 900.0,
                "total_reads": 30,
                "total_write_stall_ms": 400.0,
                "total_writes": 20,
            },
            {
                "database_name": "EmptyDb",
                "total_read_stall_ms": 50.0,
                "total_reads": 0,
                "total_write_stall_ms": 25.0,
                "total_writes": 0,
            },
        ]
        + [
            {
                "database_name": f"Db{index}",
                "total_read_stall_ms": float(index * 10),
                "total_reads": 5,
                "total_write_stall_ms": float(index * 5),
                "total_writes": 5,
            }
            for index in range(1, 9)
        ]
    )

    result = await get_disk_latency.execute(db_client)

    assert len(result["disk_latency"]) == 10
    assert result["disk_latency"][0] == {
        "database_name": "Warehouse",
        "avg_read_ms": 30.0,
        "avg_write_ms": 20.0,
    }
    assert any(row["database_name"] == "EmptyDb" for row in result["disk_latency"])


async def test_get_query_memory_grants_filters_small_grants_and_truncates_text() -> None:
    long_text = "SELECT * FROM dbo.Worktable WHERE Status = 1 " * 20
    db_client = StubDatabaseClient(
        [
            {
                "session_id": 71,
                "requested_memory_mb": 64.0,
                "granted_memory_mb": 32.0,
                "used_memory_mb": 20.0,
                "wait_time_ms": 1500,
                "grant_status": "waiting",
                "query_text": long_text,
            },
            {
                "session_id": 72,
                "requested_memory_mb": 4.0,
                "granted_memory_mb": 4.0,
                "used_memory_mb": 3.0,
                "wait_time_ms": 10,
                "grant_status": "granted",
                "query_text": "SELECT 1",
            },
        ]
    )

    result = await get_query_memory_grants.execute(db_client)

    assert len(result["memory_grants"]) == 1
    assert result["memory_grants"][0]["session_id"] == 71
    assert result["memory_grants"][0]["grant_status"] == "waiting"
    assert result["memory_grants"][0]["truncated_query_text"].endswith("...")


async def test_get_query_store_top_queries_limits_and_truncates_rows() -> None:
    long_text = "SELECT * FROM dbo.History WHERE Col = 1 " * 20
    db_client = StubDatabaseClient(
        [
            {
                "query_id": 101,
                "query_hash": "0x101",
                "object_name": "[dbo].[usp_Report]",
                "query_text": long_text,
                "execution_count_1h": 10,
                "avg_duration_ms_1h": 120.123,
                "avg_cpu_ms_1h": 50.456,
                "avg_logical_io_reads_1h": 400.0,
                "execution_count_24h": 250,
                "plan_count": 2,
                "last_execution_time_utc": "2026-05-09T12:00:00",
            }
        ]
    )

    result = await get_query_store_top_queries.execute(db_client)

    assert result["top_queries"][0]["query_id"] == 101
    assert result["top_queries"][0]["avg_duration_ms_1h"] == 120.12
    assert result["top_queries"][0]["truncated_query_text"].endswith("...")


async def test_get_query_store_regressions_filters_low_signal_rows() -> None:
    db_client = StubDatabaseClient(
        [
            {
                "query_id": 201,
                "query_hash": "0x201",
                "query_text": "SELECT * FROM dbo.Orders",
                "execution_count_1h": 6,
                "execution_count_baseline": 30,
                "avg_duration_ms_1h": 300.0,
                "avg_duration_ms_baseline": 100.0,
                "avg_cpu_ms_1h": 120.0,
                "avg_cpu_ms_baseline": 60.0,
                "avg_logical_io_reads_1h": 1000.0,
                "avg_logical_io_reads_baseline": 400.0,
                "plan_count_recent": 2,
                "plan_count_baseline": 1,
            },
            {
                "query_id": 202,
                "query_hash": "0x202",
                "query_text": "SELECT 1",
                "execution_count_1h": 1,
                "execution_count_baseline": 2,
                "avg_duration_ms_1h": 10.0,
                "avg_duration_ms_baseline": 9.0,
                "avg_cpu_ms_1h": 5.0,
                "avg_cpu_ms_baseline": 5.0,
                "avg_logical_io_reads_1h": 1.0,
                "avg_logical_io_reads_baseline": 1.0,
                "plan_count_recent": 1,
                "plan_count_baseline": 1,
            },
        ]
    )

    result = await get_query_store_regressions.execute(db_client)

    assert len(result["regressions"]) == 1
    assert result["regressions"][0]["query_id"] == 201
    assert result["regressions"][0]["new_plan_detected"] is True
    assert result["regressions"][0]["regression_type"] == "mixed"


async def test_get_tempdb_usage_summarizes_totals_and_spill_indicators() -> None:
    db_client = StubDatabaseClient(
        [
            {
                "session_id": 81,
                "internal_object_mb": 140.25,
                "user_object_mb": 10.0,
                "wait_type": "RESOURCE_SEMAPHORE",
                "query_text": "SELECT * FROM #BigTemp",
            },
            {
                "session_id": 82,
                "internal_object_mb": 12.0,
                "user_object_mb": 8.5,
                "wait_type": "",
                "query_text": "SELECT * FROM #SmallTemp",
            },
        ]
    )

    result = await get_tempdb_usage.execute(db_client)

    assert result["total_internal_object_mb"] == 152.25
    assert result["total_user_object_mb"] == 18.5
    assert result["tempdb_usage"][0]["spill_indicator"] == "likely"


async def test_get_wait_stats_by_query_aggregates_matching_active_waits() -> None:
    db_client = StubDatabaseClient(
        [
            {
                "session_id": 55,
                "wait_type": "LCK_M_X",
                "wait_time_ms": 500,
                "cpu_time_ms": 40,
                "logical_reads": 100,
                "query_text": "SELECT * FROM dbo.Orders WHERE Id = @Id",
            },
            {
                "session_id": 56,
                "wait_type": "LCK_M_X",
                "wait_time_ms": 700,
                "cpu_time_ms": 60,
                "logical_reads": 200,
                "query_text": "SELECT * FROM dbo.Orders WHERE Id = @Id",
            },
            {
                "session_id": 57,
                "wait_type": "LAZYWRITER_SLEEP",
                "wait_time_ms": 999,
                "cpu_time_ms": 0,
                "logical_reads": 0,
                "query_text": "system wait",
            },
            {
                "session_id": 58,
                "wait_type": "LCK_M_S",
                "wait_time_ms": 1500,
                "cpu_time_ms": 20,
                "logical_reads": 50,
                "query_text": None,
            },
        ]
    )

    result = await get_wait_stats_by_query.execute(db_client)

    assert result["waits_by_query"] == [
        {
            "session_id": 55,
            "dominant_wait_type": "LCK_M_X",
            "total_wait_ms": 1200,
            "cpu_time_ms": 100,
            "logical_reads": 300,
            "truncated_query_text": "SELECT * FROM dbo.Orders WHERE Id = @Id",
        }
    ]


async def test_get_plan_cache_summary_sorts_rows_and_truncates_text() -> None:
    long_text = "EXEC dbo.usp_ProcessOrders @BatchId = 1 " * 20
    db_client = StubDatabaseClient(
        [
            {
                "query_hash": "0x1",
                "execution_count": 5,
                "total_elapsed_time": 500000,
                "total_worker_time": 300000,
                "total_logical_reads": 2500,
                "plan_reuse_count": 3,
                "query_text": long_text,
            },
            {
                "query_hash": "0x2",
                "execution_count": 1,
                "total_elapsed_time": 100000,
                "total_worker_time": 50000,
                "total_logical_reads": 100,
                "plan_reuse_count": 1,
                "query_text": "SELECT 1",
            },
        ]
    )

    result = await get_plan_cache_summary.execute(db_client)

    assert result["plan_cache_summary"][0]["query_hash"] == "0x1"
    assert result["plan_cache_summary"][0]["avg_duration_ms"] == 100.0
    assert result["plan_cache_summary"][0]["total_cpu_ms"] == 300.0
    assert result["plan_cache_summary"][0]["truncated_query_text"].endswith("...")


async def test_get_table_scan_summary_groups_tables_and_filters_tiny_rows() -> None:
    db_client = StubDatabaseClient(
        [
            {
                "object_name": "AppDb.dbo.Orders",
                "physical_op": "Index Scan",
                "execution_count": 8,
                "total_logical_reads": 12000,
                "query_text": "SELECT * FROM dbo.Orders WHERE Status = 1",
            },
            {
                "object_name": "AppDb.dbo.Orders",
                "physical_op": "Table Scan",
                "execution_count": 4,
                "total_logical_reads": 3000,
                "query_text": "SELECT * FROM dbo.Orders",
            },
            {
                "object_name": "AppDb.dbo.TinyLookup",
                "physical_op": "Table Scan",
                "execution_count": 1,
                "total_logical_reads": 100,
                "query_text": "SELECT * FROM dbo.TinyLookup",
            },
        ]
    )

    result = await get_table_scan_summary.execute(db_client)

    assert result["table_scan_summary"] == [
        {
            "table_name": "AppDb.dbo.Orders",
            "scan_count": 12,
            "logical_reads": 15000,
            "associated_query_count": 2,
            "seek_possible_indicator": "possible",
            "sample_query_text": "SELECT * FROM dbo.Orders WHERE Status = 1",
        }
    ]


async def test_get_query_plan_summary_requires_exactly_one_selector() -> None:
    db_client = StubDatabaseClient([])

    with pytest.raises(ToolExecutionError, match="Provide exactly one of session_id or query_hash."):
        await get_query_plan_summary.execute(db_client, {})


async def test_get_query_store_plan_variants_requires_query_id() -> None:
    db_client = StubDatabaseClient([])

    with pytest.raises(ToolExecutionError, match="query_id is required."):
        await get_query_store_plan_variants.execute(db_client, {})


async def test_get_query_store_plan_variants_summarizes_plans() -> None:
    db_client = StubDatabaseClient(
        [
            {
                "query_id": 301,
                "query_hash": "0x301",
                "plan_id": 9001,
                "is_forced_plan": False,
                "plan_xml": PLAN_XML,
                "runtime_stats_row_count": 3,
                "execution_count_1h": 8,
                "avg_duration_ms_1h": 40.0,
                "avg_cpu_ms_1h": 25.0,
                "avg_logical_io_reads_1h": 120.0,
                "last_execution_time_utc": "2026-05-09T12:00:00",
            }
        ]
    )

    result = await get_query_store_plan_variants.execute(db_client, {"query_id": 301})

    assert result["query_id"] == 301
    assert result["plans"][0]["plan_summary"]["parallelism_detected"] is True
    assert result["plans"][0]["has_runtime_stats"] is True


async def test_get_query_store_query_detail_requires_query_id() -> None:
    db_client = StubDatabaseClient([])

    with pytest.raises(ToolExecutionError, match="query_id is required."):
        await get_query_store_query_detail.execute(db_client, {})


async def test_get_query_store_query_detail_returns_recent_and_baseline_metrics() -> None:
    db_client = StubDatabaseClient(
        [
            {
                "query_id": 401,
                "query_hash": "0x401",
                "object_name": "[dbo].[usp_Report]",
                "query_text": "EXEC dbo.usp_Report @Id = @P1",
                "plan_count": 2,
                "forced_plan_id": None,
                "last_execution_time_utc": "2026-05-09T12:00:00",
                "execution_count_1h": 10,
                "avg_duration_ms_1h": 90.0,
                "avg_cpu_ms_1h": 45.0,
                "avg_logical_io_reads_1h": 500.0,
                "execution_count_baseline": 50,
                "avg_duration_ms_baseline": 30.0,
                "avg_cpu_ms_baseline": 15.0,
                "avg_logical_io_reads_baseline": 200.0,
            }
        ]
    )

    result = await get_query_store_query_detail.execute(db_client, {"query_id": 401})

    assert result["query_id"] == 401
    assert result["avg_duration_ms_1h"] == 90.0
    assert "regression" in result["interpretation_hint"].lower()


async def test_get_query_plan_summary_summarizes_cached_plan_xml() -> None:
    db_client = StubDatabaseClient(
        [
            {
                "plan_source": "plan_cache",
                "query_hash": "0x0000000000000001",
                "query_text": "SELECT * FROM dbo.Orders WHERE Status = @Status",
                "plan_xml": PLAN_XML,
            }
        ]
    )

    result = await get_query_plan_summary.execute(db_client, {"query_hash": "0x1"})

    assert result["plan_source"] == "plan_cache"
    assert result["missing_index_detected"] is True
    assert result["parallelism_detected"] is True
    assert result["scan_summary"] == {
        "table_scans": 1,
        "index_scans": 1,
        "index_seeks": 0,
    }
    assert result["operator_flags"]["hash_operator_detected"] is True
    assert result["operator_flags"]["sort_operator_detected"] is True
    assert result["top_costly_operators"][0]["operator_name"] == "Index Scan"
