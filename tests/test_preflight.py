import json

import pytest

from sql_tshooter.config import Settings
from sql_tshooter.errors import ConfigurationError, PreflightError
from sql_tshooter.preflight import (
    PreflightReport,
    ServerInspection,
    import_pyodbc_for_preflight,
    load_profile_settings,
    load_settings,
    main,
    run_preflight,
)


class FakePyodbc:
    @staticmethod
    def drivers():
        return ["ODBC Driver 18 for SQL Server"]


def test_load_settings_wraps_configuration_errors() -> None:
    with pytest.raises(PreflightError):
        load_settings()


def test_run_preflight_returns_warning_for_tool_limitations(monkeypatch) -> None:
    settings = Settings(host="db1", auth_mode="windows")

    monkeypatch.setattr(
        "sql_tshooter.preflight.import_pyodbc_for_preflight",
        lambda: FakePyodbc(),
    )
    monkeypatch.setattr(
        "sql_tshooter.preflight.inspect_server",
        lambda settings, pyodbc_module: ServerInspection(
            major_version=16,
            edition="Developer Edition",
            available_permissions={"VIEW SERVER PERFORMANCE STATE"},
            tool_warnings={"get_failed_jobs": "SQL Agent metadata is unavailable."},
        ),
    )

    report = run_preflight(settings)

    assert report.status == "warning"
    assert report.warnings["get_failed_jobs"] == "SQL Agent metadata is unavailable."


def test_run_preflight_propagates_query_store_tool_warnings(monkeypatch) -> None:
    settings = Settings(host="db1", auth_mode="windows")

    monkeypatch.setattr(
        "sql_tshooter.preflight.import_pyodbc_for_preflight",
        lambda: FakePyodbc(),
    )
    monkeypatch.setattr(
        "sql_tshooter.preflight.inspect_server",
        lambda settings, pyodbc_module: ServerInspection(
            major_version=16,
            edition="Developer Edition",
            available_permissions={"VIEW SERVER PERFORMANCE STATE"},
            tool_warnings={
                "get_query_store_top_queries": "Query Store is not enabled for the configured database."
            },
        ),
    )

    report = run_preflight(settings)

    assert report.status == "warning"
    assert "get_query_store_top_queries" in report.warnings


def test_run_preflight_fails_when_driver_missing(monkeypatch) -> None:
    settings = Settings(host="db1", auth_mode="windows")

    class MissingDriverPyodbc:
        @staticmethod
        def drivers():
            return ["SQL Server"]

    monkeypatch.setattr(
        "sql_tshooter.preflight.import_pyodbc_for_preflight",
        lambda: MissingDriverPyodbc(),
    )

    with pytest.raises(PreflightError) as exc_info:
        run_preflight(settings)

    assert "not installed" in str(exc_info.value)


def test_run_preflight_fails_when_required_permission_is_missing(monkeypatch) -> None:
    settings = Settings(host="db1", auth_mode="windows")

    monkeypatch.setattr(
        "sql_tshooter.preflight.import_pyodbc_for_preflight",
        lambda: FakePyodbc(),
    )
    monkeypatch.setattr(
        "sql_tshooter.preflight.inspect_server",
        lambda settings, pyodbc_module: ServerInspection(
            major_version=16,
            edition="Developer Edition",
            available_permissions=set(),
            tool_warnings={},
        ),
    )

    with pytest.raises(PreflightError) as exc_info:
        run_preflight(settings)

    assert "VIEW SERVER PERFORMANCE STATE" in str(exc_info.value)


def test_preflight_main_prints_json_report(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "sql_tshooter.preflight.load_settings",
        lambda: Settings(host="db1", auth_mode="windows"),
    )
    monkeypatch.setattr(
        "sql_tshooter.preflight.run_preflight",
        lambda settings: PreflightReport(
            status="ok",
            checks=[],
            warnings={},
            major_version=16,
            edition="Developer Edition",
        ),
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["edition"] == "Developer Edition"


def test_load_profile_settings_wraps_profile_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        "sql_tshooter.preflight.load_profile",
        lambda profile_name, profile_file=None: (_ for _ in ()).throw(
            ConfigurationError("bad profile")
        ),
    )

    with pytest.raises(PreflightError, match="bad profile"):
        load_profile_settings("prod")
