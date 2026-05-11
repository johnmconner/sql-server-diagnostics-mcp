# SQL TShooter MCP Roadmap

## Purpose

This document captures the next implementation phases after the initial MVP scaffold. The goal is to move the project from a working local MCP server into a deployment-ready, production-usable tool for local SQL Server diagnostics.

The intended near-term deployment model remains:

- Codex runs locally on the SQL Server host or a nearby utility VM
- the MCP server runs locally as a child process over `stdio`
- SQL access stays read-only

This roadmap does not assume a centralized HTTP service yet. Transport changes should only happen when there is a clear operational need.

## Current State

The repository currently has:

- a Python MCP server using the official MCP SDK
- a read-only SQL Server diagnostics surface
- environment-based configuration
- local launcher scripts
- automated tests for the current tool set

The project is functional, but not yet hardened for repeatable production-style deployment.

## Guiding Decisions

- Keep `stdio` as the primary transport for the current local-first deployment model.
- Improve deployment, validation, logging, and reliability before adding more tools.
- Keep transport concerns thin so HTTP or service hosting can be added later without rewriting diagnostic logic.
- Treat operational safety and repeatability as higher priority than expanding feature count.

## Phase 1: Harden Local Deployment

### Goal

Make the current MCP server reliable and easy to deploy on a single Windows host next to SQL Server.

### Deliverables

- Startup validation for required environment variables and authentication mode
- Driver and connection preflight checks with clear failure messages
- Structured logging for startup, tool invocation, duration, and failure outcomes
- Consistent error mapping from ODBC and SQL failures into safe MCP tool errors
- One supported Windows deployment path with a documented launcher strategy
- A deployment bootstrap script for installing dependencies and validating the runtime
- A documented permission matrix for the current tool set

### Success Criteria

- A new host can be prepared with minimal manual troubleshooting
- Common misconfigurations fail at startup instead of during tool execution
- Tool failures are actionable without leaking sensitive connection details
- The deployment flow is repeatable across test VMs

## Phase 2: Production Usability on a Single Host

### Goal

Make the server operationally trustworthy for real use on a local SQL-adjacent host.

### Deliverables

- Audit logging for tool execution metadata
- Stronger response guardrails for every tool
- Standardized timeout, row-limit, and payload-limit enforcement
- Dedicated connection, session, and worker-pressure diagnostics
- Integration testing against a real SQL Server environment
- Release packaging for repeatable installation on another host
- A supportable upgrade path for new versions
- Documentation for operational checks, troubleshooting, and rollback

Recommended operations-focused additions in this phase:

- `get_connection_pressure`
  Return a summarized view of current connection pressure, including total user sessions, recent connection growth if derivable, sleeping versus active counts, and concentration by login, host, and program name. This should help surface leaked pools, bursty report clients, or one application tier dominating connections.
- `get_session_pressure`
  Return the top notable sessions with fields such as session id, login, host, program, status, open transaction count, idle duration, and last request timing. The goal is to highlight long-lived idle sessions, abandoned sessions, or sessions holding open work without doing useful activity.
- `get_worker_backlog`
  Return scheduler and worker backlog signals such as runnable task counts, pending work, active workers, and any clear indicators of worker starvation or scheduler pressure. This is meant to answer whether SQL Server itself is saturated at the worker or scheduler layer, rather than just running a few slow queries.
- `get_database_hotspots`
  Return a lightweight per-database summary showing where active requests, waits, memory grants, or TempDB-heavy activity are concentrated. This should help on shared instances where the main question is which database or application area is driving the current pressure.

Design constraints for these additions:

- keep them triage-oriented and summarized, not full DMV dumps
- prefer bounded top offenders and rollup counts over exhaustive session listings
- optimize for answering whether SQL is the current bottleneck, not for broad tuning recommendations
- make the outputs strong enough to distinguish SQL pressure from app-side pool exhaustion or leaked idle connections

### Success Criteria

- Deployments can be repeated without hand-editing the environment
- Logs show what tool ran, how long it took, and whether it failed
- Behavior is consistent across local test and production-like environments
- A real SQL Server instance is part of the validation path
- The toolset can help rule SQL in or out when applications show connection exhaustion or timeout symptoms
- The operations-focused surface can identify or rule out the most common real-time SQL pressure categories without drifting into broad tuning workflows

## Phase 3: Architecture Expansion

### Goal

Prepare the codebase for broader deployment models without disrupting the local-first path.

### Deliverables

- Separation between diagnostic core logic and MCP transport wiring
- A transport abstraction that keeps tool logic independent of `stdio` vs HTTP
- Optional HTTP or SSE transport only if a real deployment case requires it
- Support for multiple server profiles if one Codex instance needs to inspect multiple SQL hosts
- Evaluation of service hosting only when local process launching becomes a constraint

### Success Criteria

- The diagnostic logic can be reused across transports
- Adding HTTP does not require rewriting tool implementations
- The local `stdio` deployment path remains the simplest supported option

## Non-Goals for These Phases

- Expanding into write operations
- Autonomous remediation
- Converting the project into a centralized shared service by default
- Adding HTTP transport before local deployment is operationally solid
- Growing the tool count before the existing platform is hardened

## Recommended Order

1. Complete Phase 1 first.
2. Add connection and session pressure diagnostics plus real integration validation from Phase 2.
3. Add packaging and upgrade support after the operational triage surface is proven.
4. Revisit transport expansion only after the local deployment path is stable.

## Immediate Next Step

The highest-value next implementation step is to harden startup and deployment:

- add startup validation
- add structured logging
- add a deployment/bootstrap script
- add a clear permission and connectivity preflight

That work improves real-world usability more than adding another diagnostic tool.
