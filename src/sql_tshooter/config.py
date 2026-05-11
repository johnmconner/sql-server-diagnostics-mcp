"""Environment-backed runtime configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from sql_tshooter.errors import ConfigurationError


TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class Settings:
    host: str
    port: int = 1433
    database: str = "master"
    auth_mode: str = "sql"
    username: str | None = None
    password: str | None = None
    driver: str = "ODBC Driver 18 for SQL Server"
    encrypt: bool = True
    trust_server_certificate: bool = False
    connection_timeout_seconds: int = 10
    query_timeout_seconds: int = 30
    log_path: str | None = None
    max_logged_tool_output_chars: int = 12000

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        allow_missing_sql_password: bool = False,
    ) -> "Settings":
        source = os.environ if env is None else env
        host = _require(source, "SQL_TSHOOTER_HOST")
        auth_mode = source.get("SQL_TSHOOTER_AUTH_MODE", "sql").strip().lower()
        if auth_mode not in {"sql", "windows"}:
            raise ConfigurationError(
                "SQL_TSHOOTER_AUTH_MODE must be either 'sql' or 'windows'."
            )

        username = _optional(source, "SQL_TSHOOTER_USERNAME")
        password = _optional(source, "SQL_TSHOOTER_PASSWORD")
        if auth_mode == "sql" and not username:
            raise ConfigurationError(
                "SQL authentication requires SQL_TSHOOTER_USERNAME."
            )
        if auth_mode == "sql" and not password and not allow_missing_sql_password:
            raise ConfigurationError(
                "SQL authentication requires SQL_TSHOOTER_PASSWORD."
            )

        return cls(
            host=host,
            port=_parse_positive_int(source, "SQL_TSHOOTER_PORT", default=1433),
            database=source.get("SQL_TSHOOTER_DATABASE", "master").strip() or "master",
            auth_mode=auth_mode,
            username=username,
            password=password,
            driver=source.get("SQL_TSHOOTER_DRIVER", "ODBC Driver 18 for SQL Server").strip()
            or "ODBC Driver 18 for SQL Server",
            encrypt=_parse_bool(source, "SQL_TSHOOTER_ENCRYPT", default=True),
            trust_server_certificate=_parse_bool(
                source,
                "SQL_TSHOOTER_TRUST_SERVER_CERTIFICATE",
                default=False,
            ),
            connection_timeout_seconds=_parse_positive_int(
                source,
                "SQL_TSHOOTER_CONNECTION_TIMEOUT_SECONDS",
                default=10,
            ),
            query_timeout_seconds=_parse_positive_int(
                source,
                "SQL_TSHOOTER_QUERY_TIMEOUT_SECONDS",
                default=30,
            ),
            log_path=_optional(source, "SQL_TSHOOTER_LOG_PATH"),
            max_logged_tool_output_chars=_parse_positive_int(
                source,
                "SQL_TSHOOTER_MAX_LOGGED_TOOL_OUTPUT_CHARS",
                default=12000,
            ),
        )


def _require(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise ConfigurationError(f"Missing required environment variable: {key}")
    return value


def _optional(env: Mapping[str, str], key: str) -> str | None:
    value = env.get(key, "").strip()
    return value or None


def _parse_bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ConfigurationError(f"{key} must be a boolean value.")


def _parse_positive_int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{key} must be an integer.") from exc
    if value <= 0:
        raise ConfigurationError(f"{key} must be greater than zero.")
    return value
