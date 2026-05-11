"""Path helpers for repo-local runtime artifacts."""

from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_log_path() -> Path:
    return repo_root() / "logs" / "sql-tshooter.log"

