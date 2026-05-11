"""SQL Server access helpers."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import Any, Iterator, Mapping, Sequence

from sql_tshooter.config import Settings
from sql_tshooter.errors import DatabaseExecutionError


class DatabaseClient:
    """Minimal read-only database client for curated queries."""

    def __init__(
        self,
        settings: Settings,
        tool_restrictions: Mapping[str, str] | None = None,
    ) -> None:
        self._settings = settings
        self._tool_restrictions = dict(tool_restrictions or {})

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def tool_restrictions(self) -> dict[str, str]:
        return dict(self._tool_restrictions)

    async def fetch_all(
        self,
        query: str,
        params: Sequence[Any] | None = None,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._fetch_all_sync, query, params or ())

    def _fetch_all_sync(
        self,
        query: str,
        params: Sequence[Any],
    ) -> list[dict[str, Any]]:
        try:
            with connect(self._settings) as connection:
                cursor = connection.cursor()
                cursor.execute(query, params)

                if cursor.description is None:
                    return []

                columns = [column[0] for column in cursor.description]
                rows = cursor.fetchall()
        except Exception as exc:  # pragma: no cover - driver-specific failures
            raise DatabaseExecutionError(
                "Unable to execute the diagnostic query against SQL Server."
            ) from exc

        return [dict(zip(columns, row, strict=True)) for row in rows]


def import_pyodbc():
    try:
        import pyodbc  # type: ignore
    except ImportError as exc:
        raise DatabaseExecutionError("pyodbc is required to query SQL Server.") from exc
    return pyodbc


@contextmanager
def connect(settings: Settings) -> Iterator[Any]:
    pyodbc = import_pyodbc()
    connection = None
    try:
        connection = pyodbc.connect(
            build_connection_string(settings),
            timeout=settings.connection_timeout_seconds,
        )
    except Exception as exc:  # pragma: no cover - driver-specific failures
        raise DatabaseExecutionError(
            "Unable to connect to SQL Server with the configured settings."
        ) from exc
    try:
        connection.timeout = settings.query_timeout_seconds
        yield connection
    finally:
        connection.close()


def build_connection_string(settings: Settings) -> str:
    parts = [
        f"DRIVER={{{settings.driver}}}",
        f"SERVER={settings.host},{settings.port}",
        f"DATABASE={settings.database}",
        f"Encrypt={'yes' if settings.encrypt else 'no'}",
        (
            "TrustServerCertificate=yes"
            if settings.trust_server_certificate
            else "TrustServerCertificate=no"
        ),
        f"Connection Timeout={settings.connection_timeout_seconds}",
    ]

    if settings.auth_mode == "windows":
        parts.append("Trusted_Connection=yes")
    else:
        parts.extend(
            [
                f"UID={settings.username}",
                f"PWD={settings.password}",
            ]
        )

    return ";".join(parts) + ";"
