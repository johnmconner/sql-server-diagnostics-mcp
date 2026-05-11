from sql_tshooter.config import Settings
from sql_tshooter.db import build_connection_string


def test_build_connection_string_for_sql_auth() -> None:
    settings = Settings(
        host="db1",
        auth_mode="sql",
        username="readonly",
        password="secret",
    )

    connection_string = build_connection_string(settings)

    assert "SERVER=db1,1433" in connection_string
    assert "UID=readonly" in connection_string
    assert "PWD=secret" in connection_string
    assert "Trusted_Connection=yes" not in connection_string
    assert "Connection Timeout=10" in connection_string


def test_build_connection_string_for_windows_auth() -> None:
    settings = Settings(
        host="db1",
        auth_mode="windows",
    )

    connection_string = build_connection_string(settings)

    assert "Trusted_Connection=yes" in connection_string
    assert "UID=" not in connection_string
    assert "PWD=" not in connection_string

