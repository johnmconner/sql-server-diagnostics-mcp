"""Shared staged-triage guidance for tool descriptions."""

from __future__ import annotations

PRIMARY_HEALTH_TOOLS = (
    "get_server_info",
    "get_connection_pressure",
    "get_memory_status",
    "get_worker_backlog",
)
PRIMARY_LIVE_TOOLS = (
    "get_active_requests",
    "get_blocking_sessions",
    "get_blocking_details",
    "get_waiting_tasks",
    "get_lock_summary",
)
SECONDARY_PRESSURE_TOOLS = (
    "get_top_waits",
    "get_wait_stats_by_query",
    "get_query_memory_grants",
    "get_tempdb_usage",
    "get_disk_latency",
    "get_session_pressure",
    "get_database_hotspots",
)
HISTORICAL_TOOLS = (
    "get_expensive_queries",
    "get_plan_cache_summary",
    "get_table_scan_summary",
    "get_query_plan_summary",
    "get_query_store_top_queries",
    "get_query_store_regressions",
    "get_query_store_plan_variants",
    "get_query_store_query_detail",
)

_DESCRIPTION_OVERRIDES = {
    "get_server_info": (
        "Primary instance health. Use first for vague SQL symptoms to confirm version, uptime, and "
        "basic instance context. Do not use as a contention or historical-performance tool."
    ),
    "get_top_waits": (
        "Secondary live pressure. Use after first-pass health and active-request checks when you need "
        "instance-wide wait context. Do not rely on this as the first step for vague symptoms because "
        "it is cumulative and less specific than live session tools."
    ),
    "get_active_requests": (
        "Primary live triage. Use early when users report hangs, timeouts, slow pages, or login issues "
        "that may reflect current SQL activity. Prefer before cached-plan or historical tools."
    ),
    "get_blocking_sessions": (
        "Primary live triage. Use early when requests may be stuck or timing out and you need to know "
        "whether active blockers exist. Use before plan-cache or Query Store analysis."
    ),
    "get_blocking_details": (
        "Primary live triage. Use after blocking sessions are suspected to identify the exact blocker, "
        "login, host, program, and SQL text. Prefer before cached-workload tools."
    ),
    "get_expensive_queries": (
        "Historical or follow-up. Use only after live health, blocking, and active-request tools are "
        "inconclusive, or when investigating recent high-resource patterns. On quiet or test servers, "
        "diagnostic queries may dominate results."
    ),
    "get_lock_summary": (
        "Primary live triage. Use when blocking or transaction contention is suspected and you need a "
        "quick lock-level view by session and resource. Prefer before heavier historical tools."
    ),
    "get_database_sizes": (
        "Reference context. Use when storage footprint or recovery model matters to the investigation, "
        "but not as an initial pressure triage tool."
    ),
    "get_connection_pressure": (
        "Primary instance health. Use first for vague symptoms or login issues to see whether sessions "
        "are concentrating around one app, host, or login. Prefer before historical workload tools."
    ),
    "get_session_pressure": (
        "Secondary live pressure. Use after first-pass health checks when you suspect leaked idle "
        "connections, long-lived sessions, or open transactions. Do not use as the only first step for "
        "generic slowness."
    ),
    "get_failed_jobs": (
        "Operational follow-up. Use when scheduled job failures are part of the incident hypothesis. Not "
        "a first-step SQL triage tool for vague runtime symptoms."
    ),
    "get_memory_status": (
        "Primary instance health. Use first for vague SQL symptoms to see whether memory pressure is "
        "obvious before drilling into grants or historical workload behavior."
    ),
    "get_waiting_tasks": (
        "Primary live triage. Use early for hangs, timeouts, and spinning requests to identify current "
        "meaningful waits. Prefer before top-waits and cached-workload tools."
    ),
    "get_disk_latency": (
        "Secondary live pressure. Use after first-pass health and active-request checks when storage "
        "latency is a plausible bottleneck. Not a first-step tool for vague symptoms."
    ),
    "get_query_memory_grants": (
        "Secondary live pressure. Use after basic health checks when memory-grant pressure is suspected. "
        "Prefer after server info, memory status, worker backlog, and active requests."
    ),
    "get_query_store_top_queries": (
        "Historical or follow-up. Use only after live-state tools are inconclusive or when users report "
        "the issue happened earlier. Query Store is more useful for 'it was slow recently' than 'it is "
        "slow this second.'"
    ),
    "get_query_store_regressions": (
        "Historical or follow-up. Use after lighter tools when you need to know what got worse recently. "
        "Do not start here for vague active symptoms."
    ),
    "get_tempdb_usage": (
        "Secondary live pressure. Use after first-pass health checks when TempDB-heavy spills or "
        "workspace pressure are plausible. Not a default opening tool."
    ),
    "get_wait_stats_by_query": (
        "Secondary live pressure. Use after health and active-request checks when you need to correlate "
        "current waits to active user queries. Prefer after live triage tools."
    ),
    "get_plan_cache_summary": (
        "Historical or follow-up. Use only after live blocking, waits, and active-request checks do not "
        "explain the issue, or when investigating recent high-CPU patterns. On quiet or test servers, "
        "diagnostic queries may dominate results."
    ),
    "get_table_scan_summary": (
        "Historical or follow-up. Use after lighter live-state checks are inconclusive and you need to "
        "look for expensive cached scans. On low-activity servers, admin or diagnostic queries can skew "
        "results."
    ),
    "get_worker_backlog": (
        "Primary instance health. Use first for vague slowness or login issues to see whether SQL is "
        "backed up at the scheduler or worker layer. Prefer before historical analysis."
    ),
    "get_database_hotspots": (
        "Secondary live pressure. Use after initial health checks when you need to know whether one "
        "database is dominating pressure on a shared instance. Not a mandatory first step."
    ),
    "get_query_plan_summary": (
        "Historical or follow-up. Use only as a targeted drilldown after another tool identifies a "
        "specific session or query hash. Do not call this early for vague symptoms."
    ),
    "get_query_store_plan_variants": (
        "Historical or follow-up. Use only after Query Store summaries identify a query_id worth "
        "drilling into. Do not use before lighter live-state tools."
    ),
    "get_query_store_query_detail": (
        "Historical or follow-up. Use only after Query Store summaries identify a query_id that needs "
        "recent-versus-baseline detail. Not a first-step tool."
    ),
}


def get_tool_description(tool_name: str, fallback: str) -> str:
    return _DESCRIPTION_OVERRIDES.get(tool_name, fallback)
