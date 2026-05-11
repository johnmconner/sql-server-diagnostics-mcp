"""Tool registry and dispatcher helpers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import mcp.types as types

from sql_tshooter.db import DatabaseClient
from sql_tshooter.errors import ToolExecutionError
from sql_tshooter.triage_guidance import get_tool_description
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


ToolHandler = Callable[[DatabaseClient, dict[str, Any] | None], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ToolSpec:
    definition: types.Tool
    handler: ToolHandler
    accepts_arguments: bool = False


def _without_arguments(
    handler: Callable[[DatabaseClient], Awaitable[dict[str, Any]]],
) -> ToolHandler:
    async def wrapped(
        db_client: DatabaseClient,
        arguments: dict[str, Any] | None,
    ) -> dict[str, Any]:
        del arguments
        return await handler(db_client)

    return wrapped


def _with_guidance(tool: types.Tool) -> types.Tool:
    return tool.model_copy(update={"description": get_tool_description(tool.name, tool.description or "")})


def get_exposed_tool_specs() -> dict[str, ToolSpec]:
    return {
        server_info.TOOL_NAME: ToolSpec(
            definition=_with_guidance(server_info.build_tool()),
            handler=_without_arguments(server_info.execute),
        ),
        top_waits.TOOL_NAME: ToolSpec(
            definition=_with_guidance(top_waits.build_tool()),
            handler=_without_arguments(top_waits.execute),
        ),
        get_active_requests.TOOL_NAME: ToolSpec(
            definition=_with_guidance(get_active_requests.build_tool()),
            handler=_without_arguments(get_active_requests.execute),
        ),
        get_blocking_sessions.TOOL_NAME: ToolSpec(
            definition=_with_guidance(get_blocking_sessions.build_tool()),
            handler=_without_arguments(get_blocking_sessions.execute),
        ),
        get_blocking_details.TOOL_NAME: ToolSpec(
            definition=_with_guidance(get_blocking_details.build_tool()),
            handler=_without_arguments(get_blocking_details.execute),
        ),
        get_expensive_queries.TOOL_NAME: ToolSpec(
            definition=_with_guidance(get_expensive_queries.build_tool()),
            handler=_without_arguments(get_expensive_queries.execute),
        ),
        get_lock_summary.TOOL_NAME: ToolSpec(
            definition=_with_guidance(get_lock_summary.build_tool()),
            handler=_without_arguments(get_lock_summary.execute),
        ),
        get_database_sizes.TOOL_NAME: ToolSpec(
            definition=_with_guidance(get_database_sizes.build_tool()),
            handler=_without_arguments(get_database_sizes.execute),
        ),
        get_connection_pressure.TOOL_NAME: ToolSpec(
            definition=_with_guidance(get_connection_pressure.build_tool()),
            handler=_without_arguments(get_connection_pressure.execute),
        ),
        get_session_pressure.TOOL_NAME: ToolSpec(
            definition=_with_guidance(get_session_pressure.build_tool()),
            handler=_without_arguments(get_session_pressure.execute),
        ),
        get_failed_jobs.TOOL_NAME: ToolSpec(
            definition=_with_guidance(get_failed_jobs.build_tool()),
            handler=_without_arguments(get_failed_jobs.execute),
        ),
        get_memory_status.TOOL_NAME: ToolSpec(
            definition=_with_guidance(get_memory_status.build_tool()),
            handler=_without_arguments(get_memory_status.execute),
        ),
        get_waiting_tasks.TOOL_NAME: ToolSpec(
            definition=_with_guidance(get_waiting_tasks.build_tool()),
            handler=_without_arguments(get_waiting_tasks.execute),
        ),
        get_disk_latency.TOOL_NAME: ToolSpec(
            definition=_with_guidance(get_disk_latency.build_tool()),
            handler=_without_arguments(get_disk_latency.execute),
        ),
        get_query_memory_grants.TOOL_NAME: ToolSpec(
            definition=_with_guidance(get_query_memory_grants.build_tool()),
            handler=_without_arguments(get_query_memory_grants.execute),
        ),
        get_query_store_top_queries.TOOL_NAME: ToolSpec(
            definition=_with_guidance(get_query_store_top_queries.build_tool()),
            handler=_without_arguments(get_query_store_top_queries.execute),
        ),
        get_query_store_regressions.TOOL_NAME: ToolSpec(
            definition=_with_guidance(get_query_store_regressions.build_tool()),
            handler=_without_arguments(get_query_store_regressions.execute),
        ),
        get_tempdb_usage.TOOL_NAME: ToolSpec(
            definition=_with_guidance(get_tempdb_usage.build_tool()),
            handler=_without_arguments(get_tempdb_usage.execute),
        ),
        get_wait_stats_by_query.TOOL_NAME: ToolSpec(
            definition=_with_guidance(get_wait_stats_by_query.build_tool()),
            handler=_without_arguments(get_wait_stats_by_query.execute),
        ),
        get_plan_cache_summary.TOOL_NAME: ToolSpec(
            definition=_with_guidance(get_plan_cache_summary.build_tool()),
            handler=_without_arguments(get_plan_cache_summary.execute),
        ),
        get_table_scan_summary.TOOL_NAME: ToolSpec(
            definition=_with_guidance(get_table_scan_summary.build_tool()),
            handler=_without_arguments(get_table_scan_summary.execute),
        ),
        get_worker_backlog.TOOL_NAME: ToolSpec(
            definition=_with_guidance(get_worker_backlog.build_tool()),
            handler=_without_arguments(get_worker_backlog.execute),
        ),
        get_database_hotspots.TOOL_NAME: ToolSpec(
            definition=_with_guidance(get_database_hotspots.build_tool()),
            handler=_without_arguments(get_database_hotspots.execute),
        ),
        get_query_plan_summary.TOOL_NAME: ToolSpec(
            definition=_with_guidance(get_query_plan_summary.build_tool()),
            handler=get_query_plan_summary.execute,
            accepts_arguments=True,
        ),
        get_query_store_plan_variants.TOOL_NAME: ToolSpec(
            definition=_with_guidance(get_query_store_plan_variants.build_tool()),
            handler=get_query_store_plan_variants.execute,
            accepts_arguments=True,
        ),
        get_query_store_query_detail.TOOL_NAME: ToolSpec(
            definition=_with_guidance(get_query_store_query_detail.build_tool()),
            handler=get_query_store_query_detail.execute,
            accepts_arguments=True,
        ),
    }


async def invoke_tool(
    name: str,
    db_client: DatabaseClient,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    specs = get_exposed_tool_specs()
    spec = specs.get(name)
    if spec is None:
        raise ToolExecutionError(f"Unknown tool: {name}")

    normalized_arguments = arguments or {}
    if normalized_arguments and not spec.accepts_arguments:
        raise ToolExecutionError(f"{name} does not accept input arguments.")

    restriction = db_client.tool_restrictions.get(name)
    if restriction:
        raise ToolExecutionError(restriction)

    return await spec.handler(db_client, normalized_arguments if spec.accepts_arguments else None)
