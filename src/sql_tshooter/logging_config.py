"""Structured logging setup."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from sql_tshooter.paths import default_log_path


class JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in (
            "event",
            "component",
            "status",
            "tool_name",
            "duration_ms",
            "path",
            "host",
            "tool_output",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True)


def configure_logging(log_path: str | None = None) -> Path:
    resolved_path = Path(log_path) if log_path else default_log_path()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = JsonFormatter()
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)

    file_handler = logging.FileHandler(resolved_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stderr_handler = logging.StreamHandler()
    stderr_handler.setFormatter(formatter)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(stderr_handler)
    return resolved_path
