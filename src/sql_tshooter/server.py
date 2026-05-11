"""Low-level MCP server entrypoint."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import mcp.server.stdio
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from sql_tshooter import __version__
from sql_tshooter.config import Settings
from sql_tshooter.db import DatabaseClient
from sql_tshooter.errors import PreflightError, SqlTshooterError
from sql_tshooter.logging_config import configure_logging
from sql_tshooter.preflight import load_settings, run_preflight
from sql_tshooter.toolkit import get_exposed_tool_specs, invoke_tool


LOGGER = logging.getLogger("sql_tshooter")
SERVER_NAME = "sql-tshooter-mcp"


def _serialize_tool_output_for_log(
    result: dict[str, Any],
    max_logged_tool_output_chars: int,
) -> str:
    serialized = json.dumps(result, sort_keys=True, default=str)
    if len(serialized) > max_logged_tool_output_chars:
        return serialized[: max_logged_tool_output_chars - 3] + "..."
    return serialized


def build_server(db_client: DatabaseClient | None = None) -> Server:
    settings = db_client.settings if db_client else Settings.from_env()
    client = db_client or DatabaseClient(settings)
    server = Server(SERVER_NAME)

    @server.list_tools()
    async def list_tools():
        return [spec.definition for spec in get_exposed_tool_specs().values()]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        started_at = time.perf_counter()
        try:
            result = await invoke_tool(name, client, arguments)
            LOGGER.info(
                "Tool completed successfully.",
                extra={
                    "event": "tool_invocation",
                    "tool_name": name,
                    "status": "ok",
                    "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    "host": client.settings.host,
                    "tool_output": _serialize_tool_output_for_log(
                        result,
                        client.settings.max_logged_tool_output_chars,
                    ),
                },
            )
            return result
        except SqlTshooterError as exc:
            LOGGER.exception(
                "Tool execution failed.",
                extra={
                    "event": "tool_invocation",
                    "tool_name": name,
                    "status": "error",
                    "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    "host": client.settings.host,
                },
            )
            raise ValueError(str(exc)) from exc

    return server


async def run_stdio_server(db_client: DatabaseClient | None = None) -> None:
    server = build_server(db_client)
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name=SERVER_NAME,
                server_version=__version__,
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def main_with_settings(settings: Settings) -> None:
    try:
        log_path = configure_logging(settings.log_path)
        LOGGER.info(
            "Configured structured logging.",
            extra={"event": "startup", "status": "ok", "path": str(log_path)},
        )
        report = run_preflight(settings)
        LOGGER.info(
            "Startup preflight completed.",
            extra={
                "event": "preflight",
                "status": report.status,
                "host": settings.host,
            },
        )
        for check in report.checks:
            LOGGER.info(
                check.message,
                extra={
                    "event": "preflight_check",
                    "component": check.component,
                    "status": check.status,
                    "host": settings.host,
                },
            )
        db_client = DatabaseClient(settings, tool_restrictions=report.warnings)
        asyncio.run(run_stdio_server(db_client))
    except PreflightError as exc:
        logging.getLogger("sql_tshooter").error(
            "Startup preflight failed.",
            extra={"event": "startup", "status": "error"},
            exc_info=exc,
        )
        raise SystemExit(1) from exc
    except SqlTshooterError as exc:
        logging.getLogger("sql_tshooter").error(
            "Server startup failed.",
            extra={"event": "startup", "status": "error"},
            exc_info=exc,
        )
        raise SystemExit(1) from exc


def main() -> None:
    try:
        settings = load_settings()
    except PreflightError as exc:
        logging.getLogger("sql_tshooter").error(
            "Startup preflight failed.",
            extra={"event": "startup", "status": "error"},
            exc_info=exc,
        )
        raise SystemExit(1) from exc
    main_with_settings(settings)
