"""Shared helpers for Query Store tool implementations."""

from __future__ import annotations

from typing import Any

from sql_tshooter.errors import ToolExecutionError


RECENT_WINDOW_HOURS = 1
BASELINE_WINDOW_HOURS = 24
QUERY_STORE_TOOL_NAMES = (
    "get_query_store_top_queries",
    "get_query_store_regressions",
    "get_query_store_plan_variants",
    "get_query_store_query_detail",
)


def validate_query_id(arguments: dict[str, Any]) -> int:
    query_id = arguments.get("query_id")
    if query_id is None:
        raise ToolExecutionError("query_id is required.")
    try:
        value = int(query_id)
    except (TypeError, ValueError) as exc:
        raise ToolExecutionError("query_id must be an integer.") from exc
    if value <= 0:
        raise ToolExecutionError("query_id must be greater than zero.")
    return value
