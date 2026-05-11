import json
import logging
from pathlib import Path

from sql_tshooter.logging_config import configure_logging


def test_configure_logging_writes_structured_json(tmp_path: Path) -> None:
    log_path = tmp_path / "sql-tshooter.log"
    configure_logging(str(log_path))

    logger = logging.getLogger("sql_tshooter")
    logger.info(
        "Tool completed successfully.",
        extra={
            "event": "tool_invocation",
            "tool_name": "get_server_info",
            "status": "ok",
            "duration_ms": 12.5,
            "tool_output": '{"server_name":"prod-sql-01"}',
        },
    )

    payload = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert payload["event"] == "tool_invocation"
    assert payload["tool_name"] == "get_server_info"
    assert payload["status"] == "ok"
    assert payload["duration_ms"] == 12.5
    assert payload["tool_output"] == '{"server_name":"prod-sql-01"}'
