# SQL TShooter Permission Matrix

This document lists the SQL permissions and edition caveats for the currently exposed tools.

Provisioning scripts are available in:

- [create-readonly-login.sql](/C:/Projects/sql-tshooter/sql/create-readonly-login.sql)
- [create-readonly-windows-login.sql](/C:/Projects/sql-tshooter/sql/create-readonly-windows-login.sql)

## Baseline Requirement

All currently exposed tools depend on server-level diagnostic visibility:

- SQL Server 2019 and earlier: `VIEW SERVER STATE`
- SQL Server 2022 and newer: `VIEW SERVER PERFORMANCE STATE`

If the configured login does not have the required baseline permission, startup preflight should fail and the server should not start.

## Tool Matrix

| Tool | Primary objects | Required permissions | Notes |
| --- | --- | --- | --- |
| `get_server_info` | `sys.dm_os_sys_info`, `sys.configurations` | Baseline server visibility | Returns instance metadata and memory configuration. |
| `get_top_waits` | `sys.dm_os_wait_stats` | Baseline server visibility | Filters benign waits in application code. |
| `get_active_requests` | `sys.dm_exec_requests`, `sys.dm_exec_sessions`, `sys.dm_exec_sql_text` | Baseline server visibility | Includes truncated SQL text. |
| `get_blocking_sessions` | `sys.dm_exec_requests` | Baseline server visibility | Returns active blockers only. |
| `get_blocking_details` | `sys.dm_exec_requests`, `sys.dm_exec_sessions`, `sys.dm_os_waiting_tasks`, `sys.dm_tran_locks`, `sys.dm_exec_sql_text` | Baseline server visibility | Includes lock metadata and truncated SQL text. |
| `get_expensive_queries` | `sys.dm_exec_query_stats`, `sys.dm_exec_sql_text` | Baseline server visibility | Uses cached query statistics only. |
| `get_lock_summary` | `sys.dm_tran_locks`, `sys.dm_exec_sessions` | Baseline server visibility | Groups locks by session and resource. |
| `get_database_sizes` | `sys.databases`, `sys.master_files` | Baseline server visibility | Only online databases are returned. |
| `get_connection_pressure` | `sys.dm_exec_sessions`, `sys.dm_exec_connections` | Baseline server visibility | Summarizes user-session concentration by login, host, and program. |
| `get_session_pressure` | `sys.dm_exec_sessions`, `sys.dm_exec_requests`, `sys.dm_exec_sql_text` | Baseline server visibility | Highlights long-idle or open-transaction sessions rather than every user session. |
| `get_memory_status` | `sys.dm_os_sys_info`, `sys.dm_os_performance_counters` | Baseline server visibility | Returns one summarized memory row. |
| `get_waiting_tasks` | `sys.dm_os_waiting_tasks`, `sys.dm_exec_requests`, `sys.dm_exec_sessions`, `sys.dm_exec_sql_text` | Baseline server visibility | Filters benign waits in application code. |
| `get_disk_latency` | `sys.dm_io_virtual_file_stats` | Baseline server visibility | Returns the worst average read/write latency rows. |
| `get_query_memory_grants` | `sys.dm_exec_query_memory_grants`, `sys.dm_exec_requests`, `sys.dm_exec_sql_text` | Baseline server visibility | Summarizes large memory grants and waiters only. |
| `get_query_store_top_queries` | `sys.query_store_query`, `sys.query_store_query_text`, `sys.query_store_plan`, `sys.query_store_runtime_stats`, `sys.query_store_runtime_stats_interval` | Baseline server visibility plus Query Store enabled for the configured database | Historical top-query summary scoped to `SQL_TSHOOTER_DATABASE`. |
| `get_query_store_regressions` | `sys.query_store_query`, `sys.query_store_query_text`, `sys.query_store_plan`, `sys.query_store_runtime_stats`, `sys.query_store_runtime_stats_interval` | Baseline server visibility plus Query Store enabled for the configured database | Compares the last hour to the prior 24-hour baseline. |
| `get_tempdb_usage` | `sys.dm_db_session_space_usage`, `sys.dm_exec_requests`, `sys.dm_exec_sql_text` | Baseline server visibility | TempDB spill indicators are heuristic and intentionally summarized. |
| `get_wait_stats_by_query` | `sys.dm_exec_requests`, `sys.dm_exec_sql_text` | Baseline server visibility | Correlates active waits to currently running statements only. |
| `get_plan_cache_summary` | `sys.dm_exec_query_stats`, `sys.dm_exec_cached_plans`, `sys.dm_exec_sql_text` | Baseline server visibility | Uses cached plan statistics and excludes raw plan XML. |
| `get_table_scan_summary` | `sys.dm_exec_query_stats`, `sys.dm_exec_query_plan`, `sys.dm_exec_sql_text` | Baseline server visibility | Scan detection is based on cached plans and high-read offenders only. |
| `get_worker_backlog` | `sys.dm_os_schedulers` | Baseline server visibility | Uses visible scheduler state to derive worker-pressure heuristics. |
| `get_database_hotspots` | `sys.dm_exec_requests`, `sys.dm_exec_sessions`, `sys.dm_os_waiting_tasks`, `sys.dm_exec_query_memory_grants`, `sys.dm_db_session_space_usage` | Baseline server visibility | Rolls current request, wait, memory-grant, and TempDB concentration into one per-database view. |
| `get_query_plan_summary` | `sys.dm_exec_requests`, `sys.dm_exec_query_stats`, `sys.dm_exec_query_plan`, `sys.dm_exec_sql_text` | Baseline server visibility | Returns cached-plan summaries for either an active session or a query hash selector. |
| `get_query_store_plan_variants` | `sys.query_store_query`, `sys.query_store_plan`, `sys.query_store_runtime_stats`, `sys.query_store_runtime_stats_interval` | Baseline server visibility plus Query Store enabled for the configured database | Drilldown by `query_id` across recent plan variants. |
| `get_query_store_query_detail` | `sys.query_store_query`, `sys.query_store_query_text`, `sys.query_store_plan`, `sys.query_store_runtime_stats`, `sys.query_store_runtime_stats_interval` | Baseline server visibility plus Query Store enabled for the configured database | Drilldown by `query_id` with recent-versus-baseline history. |
| `get_failed_jobs` | `msdb.dbo.sysjobs`, `msdb.dbo.sysjobhistory` | Baseline server visibility plus access to SQL Agent metadata in `msdb` | Commonly requires `SQLAgentReaderRole` or equivalent metadata access. |

## Edition Caveats

- `get_failed_jobs` is warning-only on SQL Server Express because SQL Server Agent is not available there.
- If the server edition supports SQL Server Agent but the login cannot read `msdb` job metadata, startup preflight should warn and runtime invocation should fail with a sanitized message.

## Practical Permission Model

For this project, deployment is intentionally not hyper-granular per DMV. The practical model is:

1. Create a login.
2. Create a user in the target database configured by `SQL_TSHOOTER_DATABASE`.
3. Grant the baseline server diagnostic permission.
4. Optionally grant `SQLAgentReaderRole` in `msdb` if you want `get_failed_jobs` to work.

That is the exact model used by the SQL provisioning scripts above.
