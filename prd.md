# SQL AI Diagnostics MCP - MVP PRD

## Overview

Build a lightweight MCP server that allows Codex to safely analyze and troubleshoot Microsoft SQL Server environments using read-only access.

The system should expose curated diagnostic tools instead of unrestricted SQL execution.

### Goal

Allow an AI agent to investigate SQL performance and operational issues through structured tools with constrained outputs.

---

# Core Principles

## Read-Only First

The AI must NEVER have write access to SQL Server.

Initial MVP is strictly:
- Read-only SQL login
- DMV queries
- Metadata inspection
- Operational analysis

### No:
- Schema changes
- Updates/deletes
- Index creation
- SQL Agent modifications
- OS-level changes

---

# Architecture

```text
Codex
  ↓
Local MCP Server (Python)
  ↓
pyodbc / SQL Client
  ↓
Remote SQL Server
```

The MCP server:
- Exposes diagnostic tools
- Runs curated SQL queries
- Summarizes results
- Returns structured JSON

---

# Tech Stack

## Preferred
- Python 3.12+
- MCP Python SDK
- pyodbc
- ODBC Driver 18 for SQL Server

## Optional
- FastMCP
- Pydantic
- Docker packaging later

---

# Authentication

Support:
- SQL Authentication
- Windows Authentication

Credentials should come from:
- Environment variables
- Local config file

Never hardcode credentials.

---

# Security Requirements

## Required
- Read-only SQL login
- No arbitrary shell execution
- No unrestricted SQL execution
- Tool output limits
- Query timeout limits
- Connection timeout limits

## Optional Later
- Query allowlists
- Approval workflows
- Audit logging
- Tool execution logs

---

# MVP Tooling

## 1. get_server_info

### Purpose
Return basic SQL Server metadata.

### Returns
- Server name
- SQL version
- Uptime
- Edition
- Memory configuration
- CPU count

### Limit
Single summarized object.

---

## 2. get_top_waits

### Purpose
Return top SQL wait statistics.

### Returns
Top 5 waits only.

### Exclude
- Benign waits
- Idle waits

### Fields
- wait_type
- wait_seconds
- signal_wait_percent
- resource_wait_percent

---

## 3. get_blocking_sessions

### Purpose
Detect active blocking.

### Returns
Top blocking chains only.

### Fields
- blocking_session_id
- blocked_session_id
- duration_seconds
- wait_type
- database_name

### Limit
Top 10 rows maximum.

---

## 4. get_expensive_queries

### Purpose
Identify highest resource-consuming queries.

### Returns
Top 10 queries by:
- CPU
- Logical reads
- Elapsed time

### Fields
- query_hash
- avg_cpu_ms
- avg_duration_ms
- execution_count
- truncated_query_text

### Notes
Do NOT return full query plans initially.

---

## 5. get_database_sizes

### Purpose
Return database size information.

### Fields
- database_name
- total_size_gb
- used_space_gb
- recovery_model

---

## 6. get_failed_jobs

### Purpose
Return recent failed SQL Agent jobs.

### Fields
- job_name
- last_run_time
- failure_message

### Limit
Last 10 failures.

---

## 7. get_memory_status

### Purpose
Summarize SQL memory usage.

### Fields
- target_memory_mb
- total_memory_mb
- page_life_expectancy
- memory_grants_pending

---

## 8. get_disk_latency

### Purpose
Summarize SQL IO latency.

### Fields
- database_name
- avg_read_ms
- avg_write_ms

### Limit
Top worst databases only.

---

# Output Requirements

All tools must return:
- Concise JSON
- Summarized outputs
- Bounded datasets

Never dump raw DMV tables.

## Example

```json
{
  "top_waits": [
    {
      "wait_type": "CXPACKET",
      "wait_seconds": 8421,
      "signal_wait_percent": 42
    }
  ]
}
```

---

# Non-Goals (MVP)

Do NOT implement:
- Autonomous remediation
- Write operations
- Index creation
- Arbitrary SQL execution
- Query plan visualization
- Shell access
- GUI automation
- SSMS automation

---

# Prompting Guidance

The AI agent should:
- Use tools iteratively
- Correlate findings
- Summarize likely root causes
- Recommend next investigative steps
- Avoid certainty when confidence is low

## Example Workflow

1. Check top waits
2. Check blocking
3. Check expensive queries
4. Correlate memory pressure
5. Generate summary

---

# Performance Constraints

All tools should:
- Timeout within 30 seconds
- Limit result counts
- Avoid full table scans
- Avoid expensive cross joins

The MCP server should remain lightweight enough to:
- Run locally
- Run on a utility VM
- Eventually run in Docker

---

# Future Enhancements

## Phase 2
- Query Store analysis
- Deadlock analysis
- Execution plan summaries
- Anomaly detection
- Historical baselines

## Phase 3
- Guarded SQL execution
- Approval workflows
- Automated remediation
- Multi-server orchestration
- Azure SQL support
- Observability integrations

---

# Success Criteria

The MVP is successful if:
- Codex can connect safely to SQL Server
- Diagnostic tools work reliably
- Outputs are concise and useful
- The AI can identify common SQL issues
- Deployment is simple
- No write access exists anywhere