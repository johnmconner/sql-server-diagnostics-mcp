import pytest

from sql_tshooter.config import Settings
from sql_tshooter.db import DatabaseClient
from sql_tshooter.server import (
    _serialize_tool_output_for_log,
    build_server,
    main_with_settings,
)
from sql_tshooter.toolkit import get_exposed_tool_specs, invoke_tool


PLAN_XML = """
<ShowPlanXML xmlns="http://schemas.microsoft.com/sqlserver/2004/07/showplan">
  <BatchSequence>
    <Batch>
      <Statements>
        <StmtSimple>
          <QueryPlan>
            <RelOp PhysicalOp="Index Seek" EstimatedTotalSubtreeCost="2.5" EstimateRows="5" Parallel="true">
              <IndexScan>
                <Object Database="[AppDb]" Schema="[dbo]" Table="[Orders]" Index="[IX_Orders_Id]" />
              </IndexScan>
            </RelOp>
          </QueryPlan>
        </StmtSimple>
      </Statements>
    </Batch>
  </BatchSequence>
</ShowPlanXML>
""".strip()

QUERY_STORE_PLAN_XML = """
<ShowPlanXML xmlns="http://schemas.microsoft.com/sqlserver/2004/07/showplan">
  <BatchSequence>
    <Batch>
      <Statements>
        <StmtSimple>
          <QueryPlan>
            <MissingIndexes>
              <MissingIndexGroup Impact="75.0" />
            </MissingIndexes>
            <RelOp PhysicalOp="Hash Match" EstimatedTotalSubtreeCost="8.5" EstimateRows="22" Parallel="true">
              <Hash />
            </RelOp>
          </QueryPlan>
        </StmtSimple>
      </Statements>
    </Batch>
  </BatchSequence>
</ShowPlanXML>
""".strip()


class StubDatabaseClient(DatabaseClient):
    def __init__(self):
        super().__init__(Settings(host="stub", auth_mode="windows"))

    async def fetch_all(self, query: str, params=None):
        if "sys.dm_os_sys_info" in query:
            return [
                {
                    "server_name": "prod-sql-01",
                    "sql_version": "16.0.1000.6",
                    "edition": "Developer Edition",
                    "uptime_seconds": 3600,
                    "max_server_memory_mb": 4096,
                    "cpu_count": 8,
                }
            ]
        if "sys.dm_exec_query_stats" in query or "sys.dm_exec_requests AS er" in query:
            return [
                {
                    "plan_source": "plan_cache",
                    "query_hash": "0x0000000000000001",
                    "query_text": "SELECT * FROM dbo.Orders WHERE Id = @Id",
                    "plan_xml": PLAN_XML,
                }
            ]
        if "sys.query_store_plan AS qsp" in query:
            return [
                {
                    "query_id": 101,
                    "query_hash": "0x0000000000000101",
                    "plan_id": 7001,
                    "is_forced_plan": False,
                    "plan_xml": QUERY_STORE_PLAN_XML,
                    "runtime_stats_row_count": 2,
                    "execution_count_1h": 12,
                    "avg_duration_ms_1h": 45.0,
                    "avg_cpu_ms_1h": 30.0,
                    "avg_logical_io_reads_1h": 100.0,
                    "last_execution_time_utc": "2026-05-09T12:00:00",
                }
            ]
        if "FROM query_detail" in query:
            return [
                {
                    "query_id": 101,
                    "query_hash": "0x0000000000000101",
                    "object_name": "[dbo].[usp_Report]",
                    "query_text": "EXEC dbo.usp_Report @Id = @P1",
                    "plan_count": 2,
                    "forced_plan_id": None,
                    "last_execution_time_utc": "2026-05-09T12:00:00",
                    "execution_count_1h": 12,
                    "avg_duration_ms_1h": 45.0,
                    "avg_cpu_ms_1h": 30.0,
                    "avg_logical_io_reads_1h": 100.0,
                    "execution_count_baseline": 60,
                    "avg_duration_ms_baseline": 20.0,
                    "avg_cpu_ms_baseline": 10.0,
                    "avg_logical_io_reads_baseline": 40.0,
                }
            ]
        return []


def test_list_tools_exposes_all_implemented_tools() -> None:
    tool_names = list(get_exposed_tool_specs())
    assert tool_names == [
        "get_server_info",
        "get_top_waits",
        "get_active_requests",
        "get_blocking_sessions",
        "get_blocking_details",
        "get_expensive_queries",
        "get_lock_summary",
        "get_database_sizes",
        "get_connection_pressure",
        "get_session_pressure",
        "get_failed_jobs",
        "get_memory_status",
        "get_waiting_tasks",
        "get_disk_latency",
        "get_query_memory_grants",
        "get_query_store_top_queries",
        "get_query_store_regressions",
        "get_tempdb_usage",
        "get_wait_stats_by_query",
        "get_plan_cache_summary",
        "get_table_scan_summary",
        "get_worker_backlog",
        "get_database_hotspots",
        "get_query_plan_summary",
        "get_query_store_plan_variants",
        "get_query_store_query_detail",
    ]


async def test_unknown_tool_returns_controlled_error() -> None:
    db_client = StubDatabaseClient()

    with pytest.raises(Exception) as exc_info:
        await invoke_tool("does_not_exist", db_client)

    assert "Unknown tool" in str(exc_info.value)


async def test_tool_arguments_are_rejected_for_exposed_tools() -> None:
    db_client = StubDatabaseClient()

    with pytest.raises(Exception) as exc_info:
        await invoke_tool("get_memory_status", db_client, {"limit": 5})

    assert "does not accept input arguments" in str(exc_info.value)


async def test_query_plan_summary_accepts_selector_arguments() -> None:
    db_client = StubDatabaseClient()

    result = await invoke_tool("get_query_plan_summary", db_client, {"query_hash": "0x1"})

    assert result["plan_source"] == "plan_cache"
    assert result["parallelism_detected"] is True


async def test_query_store_drilldowns_accept_query_id_arguments() -> None:
    db_client = StubDatabaseClient()

    plan_variants = await invoke_tool("get_query_store_plan_variants", db_client, {"query_id": 101})
    query_detail = await invoke_tool("get_query_store_query_detail", db_client, {"query_id": 101})

    assert plan_variants["query_id"] == 101
    assert query_detail["query_id"] == 101


async def test_tool_restrictions_are_enforced_before_execution() -> None:
    db_client = DatabaseClient(
        Settings(host="stub", auth_mode="windows"),
        tool_restrictions={"get_failed_jobs": "SQL Agent metadata is unavailable."},
    )

    with pytest.raises(Exception) as exc_info:
        await invoke_tool("get_failed_jobs", db_client)

    assert "SQL Agent metadata is unavailable." in str(exc_info.value)


def test_build_server_returns_mcp_server() -> None:
    server = build_server(StubDatabaseClient())
    assert server is not None


def test_serialize_tool_output_for_log_truncates_large_payloads() -> None:
    max_logged_tool_output_chars = 200
    payload = {"value": "x" * (max_logged_tool_output_chars + 100)}

    serialized = _serialize_tool_output_for_log(payload, max_logged_tool_output_chars)

    assert len(serialized) == max_logged_tool_output_chars
    assert serialized.endswith("...")


def test_main_with_settings_runs_server_startup_pipeline(monkeypatch) -> None:
    events: list[str] = []

    monkeypatch.setattr(
        "sql_tshooter.server.configure_logging",
        lambda log_path: events.append("logging") or "log-path",
    )
    monkeypatch.setattr(
        "sql_tshooter.server.run_preflight",
        lambda settings: events.append("preflight")
        or type(
            "Report",
            (),
            {
                "status": "ok",
                "warnings": {},
                "checks": [],
            },
        )(),
    )
    monkeypatch.setattr(
        "sql_tshooter.server.DatabaseClient",
        lambda settings, tool_restrictions=None: events.append("db-client") or object(),
    )
    monkeypatch.setattr(
        "sql_tshooter.server.asyncio.run",
        lambda coroutine: events.append("asyncio-run"),
    )
    monkeypatch.setattr(
        "sql_tshooter.server.run_stdio_server",
        lambda db_client=None: "coroutine",
    )

    main_with_settings(Settings(host="stub", auth_mode="windows"))

    assert events == ["logging", "preflight", "db-client", "asyncio-run"]
