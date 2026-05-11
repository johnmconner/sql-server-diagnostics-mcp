"""Profile-backed target selection for Codex and MCP launchers."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sql_tshooter.config import Settings
from sql_tshooter.errors import ConfigurationError
from sql_tshooter.secret_store import read_password


DEFAULT_PROFILES_FILENAME = "profiles.json"


@dataclass(frozen=True)
class SqlTargetProfile:
    profile_id: str
    label: str
    host: str
    port: int
    auth_mode: str
    username: str | None
    credential_ref: str | None
    default_database: str | None
    databases: tuple[str, ...]
    driver: str
    encrypt: bool
    trust_server_certificate: bool
    connection_timeout_seconds: int
    query_timeout_seconds: int
    log_path: str | None
    max_logged_tool_output_chars: int

    def resolve_settings(self, database_override: str | None = None) -> Settings:
        selected_database = _resolve_database_name(
            self.default_database,
            self.databases,
            database_override,
        )
        return Settings(
            host=self.host,
            port=self.port,
            database=selected_database,
            auth_mode=self.auth_mode,
            username=self.username,
            password=_resolve_profile_password(self),
            driver=self.driver,
            encrypt=self.encrypt,
            trust_server_certificate=self.trust_server_certificate,
            connection_timeout_seconds=self.connection_timeout_seconds,
            query_timeout_seconds=self.query_timeout_seconds,
            log_path=self.log_path,
            max_logged_tool_output_chars=self.max_logged_tool_output_chars,
        )


def default_profiles_path() -> Path:
    local_path = _find_local_profiles_path()
    if local_path is not None:
        return local_path

    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        return Path(appdata) / "sql-tshooter" / DEFAULT_PROFILES_FILENAME
    return Path.home() / ".sql-tshooter" / DEFAULT_PROFILES_FILENAME


def _find_local_profiles_path() -> Path | None:
    current_dir = Path.cwd().resolve()

    for candidate in (current_dir, *current_dir.parents):
        if (candidate / DEFAULT_PROFILES_FILENAME).exists():
            return candidate / DEFAULT_PROFILES_FILENAME
        if (candidate / "pyproject.toml").exists():
            return candidate / DEFAULT_PROFILES_FILENAME

    return None


def load_profile(profile_name: str, profile_file: str | Path | None = None) -> SqlTargetProfile:
    profile_path = Path(profile_file) if profile_file else default_profiles_path()
    payload = _load_payload(profile_path)
    profile_entries = payload.get("profiles")
    if not isinstance(profile_entries, list) or not profile_entries:
        raise ConfigurationError(
            f"Profile file '{profile_path}' must define a non-empty 'profiles' array."
        )

    for entry in profile_entries:
        if isinstance(entry, dict) and str(entry.get("id", "")).strip() == profile_name:
            return _parse_profile(entry, profile_path)

    raise ConfigurationError(
        f"Profile '{profile_name}' was not found in profile file '{profile_path}'."
    )


def _load_payload(profile_path: Path) -> dict[str, Any]:
    try:
        raw = profile_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Profile file '{profile_path}' does not exist.") from exc
    except OSError as exc:
        raise ConfigurationError(f"Unable to read profile file '{profile_path}'.") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"Profile file '{profile_path}' is not valid JSON.") from exc

    if not isinstance(payload, dict):
        raise ConfigurationError(f"Profile file '{profile_path}' must contain a JSON object.")
    return payload


def _parse_profile(entry: dict[str, Any], profile_path: Path) -> SqlTargetProfile:
    settings = Settings.from_env(
        _build_profile_env(entry, profile_path),
        allow_missing_sql_password=True,
    )
    profile_id = _require_string(entry, "id", profile_path)
    label = str(entry.get("label", "")).strip() or profile_id
    default_database = _optional_string(entry, "database")
    credential_ref = _optional_string(entry, "credentialRef")
    configured_databases = _parse_database_list(entry, profile_path)
    if default_database and configured_databases and default_database not in configured_databases:
        raise ConfigurationError(
            f"Profile '{profile_id}' in '{profile_path}' defines database '{default_database}' "
            "that is not present in 'databases'."
        )
    if settings.auth_mode == "sql" and not credential_ref:
        raise ConfigurationError(
            f"Profile '{profile_id}' in '{profile_path}' must define 'credentialRef' for SQL authentication."
        )

    return SqlTargetProfile(
        profile_id=profile_id,
        label=label,
        host=settings.host,
        port=settings.port,
        auth_mode=settings.auth_mode,
        username=settings.username,
        credential_ref=credential_ref,
        default_database=default_database,
        databases=configured_databases,
        driver=settings.driver,
        encrypt=settings.encrypt,
        trust_server_certificate=settings.trust_server_certificate,
        connection_timeout_seconds=settings.connection_timeout_seconds,
        query_timeout_seconds=settings.query_timeout_seconds,
        log_path=settings.log_path,
        max_logged_tool_output_chars=settings.max_logged_tool_output_chars,
    )


def _build_profile_env(entry: dict[str, Any], profile_path: Path) -> dict[str, str]:
    auth_mode = _optional_string(entry, "authMode") or "sql"
    if "password" in entry and str(entry["password"]).strip():
        profile_id = str(entry.get("id", "<unknown>")).strip() or "<unknown>"
        raise ConfigurationError(
            f"Profile '{profile_id}' in '{profile_path}' cannot define 'password'; use 'credentialRef' and Windows Credential Manager instead."
        )
    values = {
        "SQL_TSHOOTER_HOST": _require_string(entry, "host", profile_path),
        "SQL_TSHOOTER_AUTH_MODE": auth_mode,
    }
    if "port" in entry:
        values["SQL_TSHOOTER_PORT"] = str(entry["port"])
    if "database" in entry and str(entry["database"]).strip():
        values["SQL_TSHOOTER_DATABASE"] = str(entry["database"]).strip()
    if "username" in entry and str(entry["username"]).strip():
        values["SQL_TSHOOTER_USERNAME"] = str(entry["username"]).strip()
    if "driver" in entry and str(entry["driver"]).strip():
        values["SQL_TSHOOTER_DRIVER"] = str(entry["driver"]).strip()
    if "encrypt" in entry:
        values["SQL_TSHOOTER_ENCRYPT"] = _stringify_json_scalar(entry["encrypt"], "encrypt")
    if "trustServerCertificate" in entry:
        values["SQL_TSHOOTER_TRUST_SERVER_CERTIFICATE"] = _stringify_json_scalar(
            entry["trustServerCertificate"],
            "trustServerCertificate",
        )
    if "connectionTimeoutSeconds" in entry:
        values["SQL_TSHOOTER_CONNECTION_TIMEOUT_SECONDS"] = _stringify_json_scalar(
            entry["connectionTimeoutSeconds"],
            "connectionTimeoutSeconds",
        )
    if "queryTimeoutSeconds" in entry:
        values["SQL_TSHOOTER_QUERY_TIMEOUT_SECONDS"] = _stringify_json_scalar(
            entry["queryTimeoutSeconds"],
            "queryTimeoutSeconds",
        )
    if "logPath" in entry and str(entry["logPath"]).strip():
        values["SQL_TSHOOTER_LOG_PATH"] = str(entry["logPath"]).strip()
    if "maxLoggedToolOutputChars" in entry:
        values["SQL_TSHOOTER_MAX_LOGGED_TOOL_OUTPUT_CHARS"] = _stringify_json_scalar(
            entry["maxLoggedToolOutputChars"],
            "maxLoggedToolOutputChars",
        )
    return values


def _resolve_profile_password(profile: SqlTargetProfile) -> str | None:
    if profile.auth_mode != "sql":
        return None
    if not profile.credential_ref:
        raise ConfigurationError(
            f"Profile '{profile.profile_id}' must define 'credentialRef' for SQL authentication."
        )
    return read_password(profile.credential_ref)


def _parse_database_list(entry: dict[str, Any], profile_path: Path) -> tuple[str, ...]:
    raw = entry.get("databases")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ConfigurationError(
            f"Profile '{entry.get('id', '<unknown>')}' in '{profile_path}' must use a list for "
            "'databases'."
        )

    databases: list[str] = []
    seen: set[str] = set()
    for item in raw:
        name = str(item).strip()
        if not name:
            raise ConfigurationError(
                f"Profile '{entry.get('id', '<unknown>')}' in '{profile_path}' contains an empty "
                "database name."
            )
        if name not in seen:
            databases.append(name)
            seen.add(name)
    return tuple(databases)


def _resolve_database_name(
    default_database: str | None,
    databases: tuple[str, ...],
    database_override: str | None,
) -> str:
    selected = (database_override or "").strip()
    if selected:
        if databases and selected not in databases:
            allowed = ", ".join(databases)
            raise ConfigurationError(
                f"Database '{selected}' is not allowed for this profile. Allowed values: {allowed}."
            )
        return selected
    if default_database:
        return default_database
    if databases:
        return databases[0]
    return "master"


def _require_string(entry: dict[str, Any], key: str, profile_path: Path) -> str:
    value = str(entry.get(key, "")).strip()
    if not value:
        profile_id = str(entry.get("id", "<unknown>")).strip() or "<unknown>"
        raise ConfigurationError(
            f"Profile '{profile_id}' in '{profile_path}' is missing required field '{key}'."
        )
    return value


def _optional_string(entry: dict[str, Any], key: str) -> str | None:
    value = str(entry.get(key, "")).strip()
    return value or None


def _stringify_json_scalar(value: Any, key: str) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value.strip()
    raise ConfigurationError(f"Profile field '{key}' must be a string, integer, or boolean.")
