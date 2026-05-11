"""Startup validation and deployment preflight."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from typing import Any

from sql_tshooter.config import Settings
from sql_tshooter.db import build_connection_string, import_pyodbc
from sql_tshooter.errors import ConfigurationError, PreflightError
from sql_tshooter.profiles import load_profile
from sql_tshooter.tools.query_store_common import QUERY_STORE_TOOL_NAMES


@dataclass(frozen=True)
class PreflightCheck:
    component: str
    status: str
    message: str


@dataclass(frozen=True)
class ServerInspection:
    major_version: int
    edition: str
    available_permissions: set[str]
    tool_warnings: dict[str, str]


@dataclass(frozen=True)
class PreflightReport:
    status: str
    checks: list[PreflightCheck]
    warnings: dict[str, str]
    major_version: int | None = None
    edition: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checks": [asdict(check) for check in self.checks],
            "warnings": dict(self.warnings),
            "major_version": self.major_version,
            "edition": self.edition,
        }


def run_preflight(settings: Settings) -> PreflightReport:
    checks = [PreflightCheck("configuration", "ok", "Environment configuration is valid.")]

    pyodbc = import_pyodbc_for_preflight()
    driver_names = list_odbc_drivers(pyodbc)
    if settings.driver not in driver_names:
        raise PreflightError(
            f"Configured ODBC driver '{settings.driver}' is not installed on this host."
        )
    checks.append(PreflightCheck("odbc_driver", "ok", f"Found ODBC driver '{settings.driver}'."))

    inspection = inspect_server(settings, pyodbc)
    checks.append(
        PreflightCheck(
            "connectivity",
            "ok",
            f"Connected to SQL Server and detected edition '{inspection.edition}'.",
        )
    )

    required_permission = (
        "VIEW SERVER PERFORMANCE STATE"
        if inspection.major_version >= 16
        else "VIEW SERVER STATE"
    )
    if required_permission not in inspection.available_permissions:
        raise PreflightError(
            f"SQL login is missing required server permission '{required_permission}'."
        )
    checks.append(
        PreflightCheck(
            "baseline_permissions",
            "ok",
            f"Verified required permission '{required_permission}'.",
        )
    )

    status = "warning" if inspection.tool_warnings else "ok"
    for tool_name, message in inspection.tool_warnings.items():
        checks.append(
            PreflightCheck(
                tool_name,
                "warning",
                message,
            )
        )

    return PreflightReport(
        status=status,
        checks=checks,
        warnings=inspection.tool_warnings,
        major_version=inspection.major_version,
        edition=inspection.edition,
    )


def import_pyodbc_for_preflight():
    try:
        return import_pyodbc()
    except Exception as exc:
        raise PreflightError("pyodbc is not installed in the active Python environment.") from exc


def list_odbc_drivers(pyodbc_module: Any) -> list[str]:
    return [str(driver) for driver in pyodbc_module.drivers()]


def inspect_server(settings: Settings, pyodbc_module: Any) -> ServerInspection:
    connection_string = build_connection_string(settings)
    try:
        with pyodbc_module.connect(
            connection_string,
            timeout=settings.connection_timeout_seconds,
        ) as connection:
            connection.timeout = settings.query_timeout_seconds
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT
                    CAST(SERVERPROPERTY('ProductMajorVersion') AS int) AS major_version,
                    CAST(SERVERPROPERTY('Edition') AS nvarchar(128)) AS edition;
                """
            )
            row = cursor.fetchone()
            if row is None:
                raise PreflightError("Unable to determine SQL Server version and edition.")

            cursor.execute(
                """
                SELECT CAST(permission_name AS nvarchar(128)) AS permission_name
                FROM sys.fn_my_permissions(NULL, 'SERVER');
                """
            )
            permission_rows = cursor.fetchall()
            permissions = {str(permission_row[0]) for permission_row in permission_rows}

            tool_warnings: dict[str, str] = {}
            edition = str(row[1])
            if "express" in edition.lower():
                tool_warnings["get_failed_jobs"] = (
                    "SQL Server Express does not include SQL Server Agent; "
                    "get_failed_jobs may not return useful results."
                )
            else:
                try:
                    cursor.execute("SELECT TOP (1) 1 FROM msdb.dbo.sysjobs;")
                    cursor.fetchall()
                except Exception:
                    tool_warnings["get_failed_jobs"] = (
                        "get_failed_jobs requires access to SQL Agent metadata in msdb, "
                        "for example SQLAgentReaderRole."
                    )

            if int(row[0]) < 13:
                query_store_warning = (
                    "Query Store requires SQL Server 2016 or newer and is unavailable on this instance."
                )
                for tool_name in QUERY_STORE_TOOL_NAMES:
                    tool_warnings[tool_name] = query_store_warning
            else:
                query_store_warning = _inspect_query_store(cursor)
                if query_store_warning:
                    for tool_name in QUERY_STORE_TOOL_NAMES:
                        tool_warnings[tool_name] = query_store_warning
    except PreflightError:
        raise
    except Exception as exc:
        raise PreflightError(
            "Unable to connect to SQL Server or query startup diagnostics with the configured settings."
        ) from exc

    return ServerInspection(
        major_version=int(row[0]),
        edition=edition,
        available_permissions=permissions,
        tool_warnings=tool_warnings,
    )


def _inspect_query_store(cursor: Any) -> str | None:
    try:
        cursor.execute(
            """
            SELECT
                CAST(actual_state_desc AS nvarchar(60)) AS actual_state_desc
            FROM sys.database_query_store_options;
            """
        )
        row = cursor.fetchone()
    except Exception:
        return (
            "Query Store metadata is unavailable in the configured database, so Query Store tools cannot be used."
        )

    if row is None:
        return (
            "Query Store metadata is unavailable in the configured database, so Query Store tools cannot be used."
        )

    actual_state_desc = str(row[0] or "").upper()
    if actual_state_desc in {"OFF", "ERROR"}:
        return (
            "Query Store is not enabled for the configured database, so Query Store tools are unavailable."
        )
    return None


def load_settings() -> Settings:
    try:
        return Settings.from_env()
    except ConfigurationError as exc:
        raise PreflightError(str(exc)) from exc


def load_profile_settings(
    profile_name: str,
    profile_file: str | None = None,
    database: str | None = None,
) -> Settings:
    try:
        profile = load_profile(profile_name=profile_name, profile_file=profile_file)
        return profile.resolve_settings(database_override=database)
    except ConfigurationError as exc:
        raise PreflightError(str(exc)) from exc


def main() -> None:
    try:
        settings = load_settings()
        report = run_preflight(settings)
    except PreflightError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
