from sql_tshooter.config import Settings
from sql_tshooter.errors import ConfigurationError


def test_sql_auth_config_loads() -> None:
    settings = Settings.from_env(
        {
            "SQL_TSHOOTER_HOST": "db1",
            "SQL_TSHOOTER_AUTH_MODE": "sql",
            "SQL_TSHOOTER_USERNAME": "readonly",
            "SQL_TSHOOTER_PASSWORD": "secret",
        }
    )

    assert settings.host == "db1"
    assert settings.auth_mode == "sql"
    assert settings.username == "readonly"
    assert settings.password == "secret"
    assert settings.database == "master"


def test_windows_auth_config_loads() -> None:
    settings = Settings.from_env(
        {
            "SQL_TSHOOTER_HOST": "db1",
            "SQL_TSHOOTER_AUTH_MODE": "windows",
        }
    )

    assert settings.auth_mode == "windows"
    assert settings.username is None
    assert settings.password is None


def test_sql_auth_requires_credentials() -> None:
    try:
        Settings.from_env(
            {
                "SQL_TSHOOTER_HOST": "db1",
                "SQL_TSHOOTER_AUTH_MODE": "sql",
            }
        )
    except ConfigurationError as exc:
        assert "requires" in str(exc)
    else:  # pragma: no cover - defensive guard
        raise AssertionError("Expected SQL auth validation to fail.")


def test_invalid_boolean_raises() -> None:
    try:
        Settings.from_env(
            {
                "SQL_TSHOOTER_HOST": "db1",
                "SQL_TSHOOTER_AUTH_MODE": "windows",
                "SQL_TSHOOTER_ENCRYPT": "sometimes",
            }
        )
    except ConfigurationError as exc:
        assert "boolean" in str(exc)
    else:  # pragma: no cover - defensive guard
        raise AssertionError("Expected boolean parsing to fail.")


def test_timeout_values_are_parsed() -> None:
    settings = Settings.from_env(
        {
            "SQL_TSHOOTER_HOST": "db1",
            "SQL_TSHOOTER_AUTH_MODE": "windows",
            "SQL_TSHOOTER_CONNECTION_TIMEOUT_SECONDS": "12",
            "SQL_TSHOOTER_QUERY_TIMEOUT_SECONDS": "22",
            "SQL_TSHOOTER_TRUST_SERVER_CERTIFICATE": "yes",
            "SQL_TSHOOTER_LOG_PATH": r"C:\logs\sql-tshooter.log",
            "SQL_TSHOOTER_MAX_LOGGED_TOOL_OUTPUT_CHARS": "8000",
        }
    )

    assert settings.connection_timeout_seconds == 12
    assert settings.query_timeout_seconds == 22
    assert settings.trust_server_certificate is True
    assert settings.log_path == r"C:\logs\sql-tshooter.log"
    assert settings.max_logged_tool_output_chars == 8000
