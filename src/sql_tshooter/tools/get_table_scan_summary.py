"""Implementation of the get_table_scan_summary tool."""

from __future__ import annotations

from typing import Any

import mcp.types as types

from sql_tshooter.db import DatabaseClient
from sql_tshooter.tools.common import collected_at_utc, truncate_identifier, truncate_text


TOOL_NAME = "get_table_scan_summary"
QUERY_TEXT_MAX_LENGTH = 220
TABLE_NAME_MAX_LENGTH = 180

QUERY = """
WITH XMLNAMESPACES (DEFAULT 'http://schemas.microsoft.com/sqlserver/2004/07/showplan')
SELECT TOP (50)
    CAST(
        COALESCE(
            obj.value('@Database', 'nvarchar(128)') + N'.', N''
        )
        + COALESCE(
            obj.value('@Schema', 'nvarchar(128)') + N'.', N''
        )
        + COALESCE(
            obj.value('@Table', 'nvarchar(256)'),
            obj.value('@Index', 'nvarchar(256)'),
            N'unknown'
        ) AS nvarchar(512)
    ) AS object_name,
    CAST(relop.value('@PhysicalOp', 'nvarchar(60)') AS nvarchar(60)) AS physical_op,
    CAST(qs.execution_count AS bigint) AS execution_count,
    CAST(qs.total_logical_reads AS bigint) AS total_logical_reads,
    CAST(st.text AS nvarchar(max)) AS query_text
FROM sys.dm_exec_query_stats AS qs
CROSS APPLY sys.dm_exec_query_plan(qs.plan_handle) AS qp
CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) AS st
CROSS APPLY qp.query_plan.nodes('//RelOp[@PhysicalOp="Table Scan" or @PhysicalOp="Index Scan"]') AS scanop(relop)
OUTER APPLY relop.nodes('.//Object') AS objnode(obj)
ORDER BY qs.total_logical_reads DESC, qs.execution_count DESC;
""".strip()


def build_tool() -> types.Tool:
    return types.Tool(
        name=TOOL_NAME,
        description="Return summarized expensive table and index scan offenders from cached plans.",
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
                "table_scan_summary": {
                    "type": "array",
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "properties": {
                            "table_name": {"type": "string"},
                            "scan_count": {"type": "integer"},
                            "logical_reads": {"type": "integer"},
                            "associated_query_count": {"type": "integer"},
                            "seek_possible_indicator": {"type": "string"},
                            "sample_query_text": {"type": "string"},
                        },
                        "required": [
                            "table_name",
                            "scan_count",
                            "logical_reads",
                            "associated_query_count",
                            "seek_possible_indicator",
                            "sample_query_text",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["collected_at_utc", "interpretation_hint", "table_scan_summary"],
            "additionalProperties": False,
        },
    )


async def execute(db_client: DatabaseClient) -> dict[str, Any]:
    rows = await db_client.fetch_all(QUERY)
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        table_name = truncate_identifier(row["object_name"], TABLE_NAME_MAX_LENGTH)
        scan_reads = max(int(row["total_logical_reads"]), 0)
        execution_count = max(int(row["execution_count"]), 0)
        if scan_reads < 1000 and execution_count < 5:
            continue
        entry = grouped.setdefault(
            table_name,
            {
                "table_name": table_name,
                "scan_count": 0,
                "logical_reads": 0,
                "associated_query_count": 0,
                "seek_possible_indicator": "unknown",
                "sample_query_text": truncate_text(row["query_text"], QUERY_TEXT_MAX_LENGTH),
            },
        )
        entry["scan_count"] += execution_count
        entry["logical_reads"] += scan_reads
        entry["associated_query_count"] += 1
        physical_op = str(row["physical_op"] or "").lower()
        if physical_op == "index scan":
            entry["seek_possible_indicator"] = "possible"
        elif entry["seek_possible_indicator"] == "unknown":
            entry["seek_possible_indicator"] = "unlikely"

    table_scan_summary = list(grouped.values())
    table_scan_summary.sort(
        key=lambda row: (-row["logical_reads"], -row["scan_count"], row["table_name"].lower())
    )
    return {
        "collected_at_utc": collected_at_utc(),
        "interpretation_hint": (
            "Repeated high-read scans in cached plans can point to missing predicates or indexing issues."
        ),
        "table_scan_summary": table_scan_summary[:10],
    }

