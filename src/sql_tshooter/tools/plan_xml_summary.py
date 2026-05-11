"""Shared XML plan summarization helpers."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from sql_tshooter.errors import ToolExecutionError
from sql_tshooter.tools.common import truncate_identifier


OBJECT_NAME_MAX_LENGTH = 180
SHOWPLAN_NS = {"sp": "http://schemas.microsoft.com/sqlserver/2004/07/showplan"}


def summarize_plan_xml(plan_xml: str) -> dict[str, Any]:
    try:
        root = ET.fromstring(plan_xml)
    except ET.ParseError as exc:
        raise ToolExecutionError("Unable to parse the cached execution plan.") from exc

    relops = root.findall(".//sp:RelOp", SHOWPLAN_NS)
    top_costly_operators = sorted(
        (_normalize_relop(relop) for relop in relops),
        key=lambda item: -item["estimated_subtree_cost"],
    )[:5]
    return {
        "parallelism_detected": any(
            str(relop.get("Parallel") or "").lower() in {"1", "true"} for relop in relops
        )
        or any(relop.get("PhysicalOp") == "Parallelism" for relop in relops),
        "missing_index_detected": bool(root.findall(".//sp:MissingIndexGroup", SHOWPLAN_NS)),
        "scan_summary": {
            "table_scans": sum(1 for relop in relops if relop.get("PhysicalOp") == "Table Scan"),
            "index_scans": sum(1 for relop in relops if relop.get("PhysicalOp") == "Index Scan"),
            "index_seeks": sum(1 for relop in relops if relop.get("PhysicalOp") == "Index Seek"),
        },
        "operator_flags": {
            "hash_operator_detected": any(
                "Hash" in (relop.get("PhysicalOp") or "") for relop in relops
            ),
            "sort_operator_detected": any(relop.get("PhysicalOp") == "Sort" for relop in relops),
            "spill_warning_detected": None,
        },
        "row_mismatch_summary": None,
        "total_estimated_subtree_cost": round(
            max(
                (float(relop.get("EstimatedTotalSubtreeCost", "0")) for relop in relops),
                default=0.0,
            ),
            4,
        ),
        "top_costly_operators": top_costly_operators,
        "top_operator_names": [row["operator_name"] for row in top_costly_operators[:3]],
    }


def _normalize_relop(relop: ET.Element) -> dict[str, Any]:
    object_name = "unknown"
    object_node = relop.find(".//sp:Object", SHOWPLAN_NS)
    if object_node is not None:
        parts = [
            object_node.get("Database"),
            object_node.get("Schema"),
            object_node.get("Table") or object_node.get("Index"),
        ]
        object_name = ".".join(part for part in parts if part)

    return {
        "operator_name": str(relop.get("PhysicalOp") or "UNKNOWN"),
        "estimated_subtree_cost": round(
            float(relop.get("EstimatedTotalSubtreeCost", "0") or 0.0), 4
        ),
        "estimated_rows": round(float(relop.get("EstimateRows", "0") or 0.0), 2),
        "object_name": truncate_identifier(object_name, OBJECT_NAME_MAX_LENGTH),
    }
