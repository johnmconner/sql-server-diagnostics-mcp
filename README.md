# SQL TShooter MCP

`sql-tshooter` is a local, read-only MCP server for SQL Server diagnostics. It is designed to run next to SQL Server and be launched by Codex as an `stdio` MCP server.

## What It Does

The server exposes curated diagnostic tools instead of arbitrary SQL execution. The current tool set includes:

- `get_server_info`
- `get_top_waits`
- `get_active_requests`
- `get_blocking_sessions`
- `get_blocking_details`
- `get_expensive_queries`
- `get_lock_summary`
- `get_database_sizes`
- `get_connection_pressure`
- `get_session_pressure`
- `get_failed_jobs`
- `get_memory_status`
- `get_waiting_tasks`
- `get_disk_latency`
- `get_query_memory_grants`
- `get_query_store_top_queries`
- `get_query_store_regressions`
- `get_tempdb_usage`
- `get_wait_stats_by_query`
- `get_plan_cache_summary`
- `get_table_scan_summary`
- `get_worker_backlog`
- `get_database_hotspots`
- `get_query_plan_summary`
- `get_query_store_plan_variants`
- `get_query_store_query_detail`

The project is read-only by design. It does not perform write operations, shell execution, or unrestricted SQL.

The newer performance-analysis tools stay summarized by default: bounded row counts, truncated query text, and a cached-plan or Query Store summary instead of raw XML unless explicitly extended later.

The server publishes staged-triage guidance through MCP tool descriptions so clients do not need to call every tool up front.

## Proof Of Concept

Example use case: we ran a simulated blocking incident where an open transaction in SSMS held locks on a row and the MCP tools were used to trace the issue.

Using the exposed telemetry, Codex correlated:

- active sessions
- blocking chains
- wait types
- locks
- active requests
- SQL text
- server health metrics

The result was a concise root-cause diagnosis: an uncommitted SSMS transaction was blocking application work.

## Requirements

- Python 3.11+
- Microsoft ODBC Driver 18 for SQL Server
- Access to a SQL Server instance
- A read-only SQL login or Windows-authenticated principal with the required diagnostic permissions

## SQL Server Permissions

For most tools, the practical permission model is:

1. Create a login.
2. Create a user in the target database.
3. Grant the baseline server diagnostic permission:
   - SQL Server 2019 and earlier: `VIEW SERVER STATE`
   - SQL Server 2022 and newer: `VIEW SERVER PERFORMANCE STATE`
4. Optionally grant `SQLAgentReaderRole` in `msdb` if you want `get_failed_jobs` to work.

Provisioning scripts are included here:

- [create-readonly-login.sql](/C:/Projects/sql-tshooter/sql/create-readonly-login.sql)
- [create-readonly-windows-login.sql](/C:/Projects/sql-tshooter/sql/create-readonly-windows-login.sql)
- [PERMISSIONS.md](/C:/Projects/sql-tshooter/PERMISSIONS.md)

## Configuration

Set these environment variables before starting the server:

- `SQL_TSHOOTER_HOST`
- `SQL_TSHOOTER_PORT` default `1433`
- `SQL_TSHOOTER_DATABASE` default `master`
- `SQL_TSHOOTER_AUTH_MODE` values `sql` or `windows`
- `SQL_TSHOOTER_USERNAME` required for `sql` auth
- `SQL_TSHOOTER_PASSWORD` required for `sql` auth
- `SQL_TSHOOTER_DRIVER` default `ODBC Driver 18 for SQL Server`
- `SQL_TSHOOTER_ENCRYPT` default `true`
- `SQL_TSHOOTER_TRUST_SERVER_CERTIFICATE` default `false`
- `SQL_TSHOOTER_CONNECTION_TIMEOUT_SECONDS` default `10`
- `SQL_TSHOOTER_QUERY_TIMEOUT_SECONDS` default `30`
- `SQL_TSHOOTER_LOG_PATH` optional log file override
- `SQL_TSHOOTER_MAX_LOGGED_TOOL_OUTPUT_CHARS` default `12000`

See [.env.example](/C:/Projects/sql-tshooter/.env.example) for a template.

For multi-target launches through Codex, you can define named profiles in a JSON file. The repo now includes a local starter file at [profiles.json](/C:/Projects/sql-tshooter/profiles.json), with [profiles.example.json](/C:/Projects/sql-tshooter/profiles.example.json) as a reference copy.

For Windows SQL-auth profiles, store `username` plus `credentialRef` in JSON and save the actual password into Windows Credential Manager. Plaintext `password` entries in `profiles.json` are rejected.

## Install

With `uv`:

```powershell
uv sync --extra dev
```

With `pip`:

```powershell
python -m pip install -e .[dev]
```

## Desktop GUI

The repository now includes a standalone desktop shell in [desktop/package.json](/C:/Projects/sql-tshooter/desktop/package.json:1). This app does not embed Codex Desktop. It runs the local `codex` CLI in headless `app-server` mode and binds each GUI tab to one SQL TShooter target profile.

Current desktop prerequisites:

- `codex` must already be installed and logged in
- Node.js and npm
- Rust plus Cargo for Tauri builds
- the Python package must be runnable via `python3 -m sql_tshooter.profiled_server` or another command exposed through `SQL_TSHOOTER_PYTHON_COMMAND`

Development startup:

```powershell
cd .\desktop
npm install
npm run tauri:dev
```

Useful environment overrides:

- `SQL_TSHOOTER_PROFILE_FILE` to point the GUI at a non-default profile JSON file
- `SQL_TSHOOTER_WORKSPACE_ROOT` to force the Codex workspace root used for threads
- `SQL_TSHOOTER_PYTHON_COMMAND` to override Python resolution for the profiled MCP server
- `CODEX_COMMAND` to override which `codex` executable the GUI launches

Example Codex provider configuration for Azure Foundry / Azure OpenAI Responses-compatible endpoints:

```toml
model = "YOUR_MODEL_NAME"
model_provider = "azure_foundry"
model_reasoning_effort = "medium"
personality = "pragmatic"

[model_providers.azure_foundry]
name = "Azure Foundry"
base_url = "https://YOUR-RESOURCE-NAME.cognitiveservices.azure.com/openai"
wire_api = "responses"
query_params = { api-version = "YOUR_API_VERSION" }
env_http_headers = { "api-key" = "AZURE_OPENAI_API_KEY" }
```

Set the API key in the environment before launching Codex or the desktop app:

```powershell
$env:AZURE_OPENAI_API_KEY = "YOUR_REAL_API_KEY"
```

Notes:

- `base_url` should be the base `/openai` path, not a full `/responses?...` URL
- `wire_api = "responses"` tells Codex to use the Responses API
- `query_params` is where the Azure `api-version` goes
- `env_http_headers` maps the HTTP header name to the environment variable name, not the literal secret value
- if you set the variable after launching Codex or the desktop app, restart the process so it inherits the updated environment

Desktop profile bootstrap behavior:

- when running from this repo, the desktop app prefers `[repo]/profiles.json`
- if the resolved `profiles.json` file does not exist, the app creates a placeholder file at that exact path
- on macOS and Linux, the default desktop path is platform-native via the user config directory, not `APPDATA`
- if the chosen profile file exists but is invalid, the GUI shows a minimal picker/path prompt instead of failing at startup

## Bootstrap and Preflight

The supported Windows setup flow is:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap-sql-tshooter.ps1
```

This script:

- installs dependencies
- requires a local `.env`
- runs startup preflight
- prints a Codex MCP config snippet

You can also run preflight directly:

```powershell
python -m sql_tshooter.preflight
```

Startup preflight validates:

- environment configuration
- `pyodbc` availability
- configured ODBC driver presence
- SQL Server connectivity
- baseline server-state permissions

If a global prerequisite is missing, the server exits before exposing tools. Tool-specific limitations are reported as warnings and become sanitized runtime errors only for the affected tools.

## Running the Server

In normal use, Codex launches the server. You do not typically start it manually first.

Codex should be configured to launch either:

- the console entrypoint `sql-tshooter-mcp`
- or a Python command that runs [run_sql_tshooter_mcp.py](/C:/Projects/sql-tshooter/scripts/run_sql_tshooter_mcp.py)

Manual local launch is still available:

```powershell
sql-tshooter-mcp
```

or:

```powershell
python -m sql_tshooter.server
```

You can also launch a named profile directly:

```powershell
sql-tshooter-profiled-mcp --profile-file C:\Users\me\AppData\Roaming\sql-tshooter\profiles.json --profile prod-app
```

or override the configured default database for that launch:

```powershell
sql-tshooter-profiled-mcp --profile-file C:\Users\me\AppData\Roaming\sql-tshooter\profiles.json --profile prod-app --database ReportingDb
```

## Codex MCP Configuration

Codex should treat this as an `stdio` MCP server. In practice, that means Codex launches a local command and communicates with it over standard input and output.

A typical `config.toml` entry looks like this:

```toml
[mcp_servers.sql-tshooter]
command = 'C:\Path\To\python.exe'
args = ['C:\Path\To\sql-tshooter\scripts\run_sql_tshooter_mcp.py']
```

If `sql-tshooter-mcp` is on `PATH`, you can point Codex at that command instead.

You can also register the server from the CLI:

```powershell
codex mcp add sql-tshooter -- python C:\Path\To\sql-tshooter\scripts\run_sql_tshooter_mcp.py
```

If you want Codex to launch a specific profile without editing your global Codex config, use the new launcher:

```powershell
sql-tshooter-launch --mode cli --profile-file C:\Users\me\AppData\Roaming\sql-tshooter\profiles.json --profile prod-app --database AppDb -- --search
```

That command starts the normal interactive Codex CLI and injects a session-local MCP configuration that launches `sql_tshooter.profiled_server` for the selected target.

To open Codex Desktop against the same target:

```powershell
sql-tshooter-launch --mode desktop --profile-file C:\Users\me\AppData\Roaming\sql-tshooter\profiles.json --profile prod-app
```

For a standard custom MCP server, no experimental MCP feature flags should be required.

## Logs and Troubleshooting

By default, structured logs are written to `logs\sql-tshooter.log`. Set `SQL_TSHOOTER_LOG_PATH` to override the location.

Successful tool calls also log a serialized snapshot of the returned tool output. Set `SQL_TSHOOTER_MAX_LOGGED_TOOL_OUTPUT_CHARS` to control how much of that payload is retained per invocation.

If tools do not appear in Codex:

- confirm the `mcp_servers.sql-tshooter` entry exists or `codex mcp list` shows the server
- confirm the configured command launches successfully outside Codex
- confirm the environment variables are present
- check the log file for startup preflight failures

If SQL connectivity fails:

- verify SQL Server is reachable on the configured host and port
- verify the login or Windows principal works independently
- confirm the required baseline permission was granted

## Development

Run tests with:

```powershell
python -m pytest
```
