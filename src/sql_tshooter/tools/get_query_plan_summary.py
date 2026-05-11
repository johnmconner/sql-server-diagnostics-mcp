"""Implementation of the get_query_plan_summary tool."""

from __future__ import annotations

from typing import Any

import mcp.types as types

from sql_tshooter.db import DatabaseClient
from sql_tshooter.errors import ToolExecutionError
from sql_tshooter.tools.common import collected_at_utc, truncate_text
from sql_tshooter.tools.plan_xml_summary import summarize_plan_xml


TOOL_NAME = "get_query_plan_summary"
QUERY_TEXT_MAX_LENGTH = 220
QUERY_BY_SESSION = """
SELECT TOP (1)
    CAST('active_session' AS nvarchar(40)) AS plan_source,
    CONVERT(varchar(18), er.query_hash, 1) AS query_hash,
    CAST(st.text AS nvarchar(max)) AS query_text,
    CAST(CONVERT(nvarchar(max), qp.query_plan) AS nvarchar(max)) AS plan_xml
FROM sys.dm_exec_requests AS er
OUTER APPLY sys.dm_exec_sql_text(er.sql_handle) AS st
OUTER APPLY sys.dm_exec_query_plan(er.plan_handle) AS qp
WHERE er.session_id = ?
ORDER BY er.total_elapsed_time DESC;
""".strip()

QUERY_BY_QUERY_HASH = """
SELECT TOP (1)
    CAST('plan_cache' AS nvarchar(40)) AS plan_source,
    CONVERT(varchar(18), qs.query_hash, 1) AS query_hash,
    CAST(st.text AS nvarchar(max)) AS query_text,
    CAST(CONVERT(nvarchar(max), qp.query_plan) AS nvarchar(max)) AS plan_xml
FROM sys.dm_exec_query_stats AS qs
CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) AS st
CROSS APPLY sys.dm_exec_query_plan(qs.plan_handle) AS qp
WHERE CONVERT(varchar(18), qs.query_hash, 1) = ?
ORDER BY qs.total_worker_time DESC, qs.execution_count DESC;
""".strip()


def build_tool() -> types.Tool:
    return types.Tool(
        name=TOOL_NAME,
        description="Return a summarized cached execution plan for a query hash or active session.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {"type": "integer"},
                "query_hash": {"type": "string"},
            },
            "additionalProperties": False,
        },
        outputSchema={
            "type": "object",
            "properties": {
                "collected_at_utc": {"type": "string"},
                "plan_source": {"type": "string"},
                "query_hash": {"type": "string"},
                "total_estimated_subtree_cost": {"type": "number"},
                "parallelism_detected": {"type": "boolean"},
                "missing_index_detected": {"type": "boolean"},
                "scan_summary": {
                    "type": "object",
                    "properties": {
                        "table_scans": {"type": "integer"},
                        "index_scans": {"type": "integer"},
                        "index_seeks": {"type": "integer"},
                    },
                    "required": ["table_scans", "index_scans", "index_seeks"],
                    "additionalProperties": False,
                },
                "operator_flags": {
                    "type": "object",
                    "properties": {
                        "hash_operator_detected": {"type": "boolean"},
                        "sort_operator_detected": {"type": "boolean"},
                        "spill_warning_detected": {"type": ["boolean", "null"]},
                    },
                    "required": [
                        "hash_operator_detected",
                        "sort_operator_detected",
                        "spill_warning_detected",
                    ],
                    "additionalProperties": False,
                },
                "row_mismatch_summary": {"type": ["string", "null"]},
                "top_costly_operators": {
                    "type": "array",
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "properties": {
                            "operator_name": {"type": "string"},
                            "estimated_subtree_cost": {"type": "number"},
                            "estimated_rows": {"type": "number"},
                            "object_name": {"type": "string"},
                        },
                        "required": [
                            "operator_name",
                            "estimated_subtree_cost",
                            "estimated_rows",
                            "object_name",
                        ],
                        "additionalProperties": False,
                    },
                },
                "truncated_query_text": {"type": "string"},
                "interpretation_hint": {"type": "string"},
            },
            "required": [
                "collected_at_utc",
                "plan_source",
                "query_hash",
                "total_estimated_subtree_cost",
                "parallelism_detected",
                "missing_index_detected",
                "scan_summary",
                "operator_flags",
                "row_mismatch_summary",
                "top_costly_operators",
                "truncated_query_text",
                "interpretation_hint",
            ],
            "additionalProperties": False,
        },
    )


async def execute(db_client: DatabaseClient, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    selector = _validate_selector(arguments or {})
    if "session_id" in selector:
        rows = await db_client.fetch_all(QUERY_BY_SESSION, (selector["session_id"],))
    else:
        rows = await db_client.fetch_all(QUERY_BY_QUERY_HASH, (selector["query_hash"],))

    if not rows:
        raise ToolExecutionError("No cached execution plan matched the supplied selector.")

    row = rows[0]
    return _normalize_plan_summary_row(row)


def _validate_selector(arguments: dict[str, Any]) -> dict[str, Any]:
    has_session_id = "session_id" in arguments and arguments["session_id"] is not None
    has_query_hash = "query_hash" in arguments and arguments["query_hash"] is not None
    if has_session_id == has_query_hash:
        raise ToolExecutionError("Provide exactly one of session_id or query_hash.")
    if has_session_id:
        try:
            return {"session_id": int(arguments["session_id"])}
        except (TypeError, ValueError) as exc:
            raise ToolExecutionError("session_id must be an integer.") from exc
    query_hash = str(arguments["query_hash"]).strip()
    if not query_hash:
        raise ToolExecutionError("query_hash must be a non-empty string.")
    return {"query_hash": query_hash}


def _normalize_plan_summary_row(row: dict[str, Any]) -> dict[str, Any]:
    summary = summarize_plan_xml(str(row["plan_xml"]))

    return {
        "collected_at_utc": collected_at_utc(),
        "plan_source": str(row["plan_source"] or "unknown"),
        "query_hash": str(row["query_hash"] or "unknown"),
        "total_estimated_subtree_cost": summary["total_estimated_subtree_cost"],
        "parallelism_detected": summary["parallelism_detected"],
        "missing_index_detected": summary["missing_index_detected"],
        "scan_summary": summary["scan_summary"],
        "operator_flags": summary["operator_flags"],
        "row_mismatch_summary": summary["row_mismatch_summary"],
        "top_costly_operators": summary["top_costly_operators"],
        "truncated_query_text": truncate_text(row["query_text"], QUERY_TEXT_MAX_LENGTH),
        "interpretation_hint": (
            "This summary is based on a cached plan, so estimated operator costs are more reliable than actual row or spill diagnostics."
        ),
    }
