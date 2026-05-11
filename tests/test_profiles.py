import json
from pathlib import Path

import pytest

from sql_tshooter.errors import ConfigurationError
from sql_tshooter.profiles import default_profiles_path, load_profile


def test_default_profiles_path_uses_appdata(monkeypatch) -> None:
    monkeypatch.chdir(Path.home())
    monkeypatch.setenv("APPDATA", r"C:\Users\me\AppData\Roaming")

    path = default_profiles_path()

    assert path.name == "profiles.json"
    assert path.parent.name == "sql-tshooter"


def test_default_profiles_path_prefers_repo_local_profiles_file(tmp_path, monkeypatch) -> None:
    local_profile = tmp_path / "profiles.json"
    local_profile.write_text('{"profiles": []}', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APPDATA", r"C:\Users\me\AppData\Roaming")

    path = default_profiles_path()

    assert path == local_profile


def test_load_profile_returns_settings_ready_profile(tmp_path) -> None:
    profile_path = tmp_path / "profiles.json"
    profile_path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "id": "prod",
                        "label": "Production",
                        "host": "prod-sql-01",
                        "port": 1444,
                        "authMode": "sql",
                        "username": "readonly",
                        "credentialRef": "prod-sql",
                        "database": "AppDb",
                        "databases": ["AppDb", "ReportingDb"],
                        "encrypt": True,
                        "trustServerCertificate": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    profile = load_profile("prod", profile_path)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("sql_tshooter.profiles.read_password", lambda credential_ref: "secret")
        settings = profile.resolve_settings()

    assert profile.profile_id == "prod"
    assert profile.label == "Production"
    assert profile.databases == ("AppDb", "ReportingDb")
    assert profile.credential_ref == "prod-sql"
    assert settings.host == "prod-sql-01"
    assert settings.port == 1444
    assert settings.database == "AppDb"


def test_load_profile_allows_database_override_when_listed(tmp_path) -> None:
    profile_path = tmp_path / "profiles.json"
    profile_path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "id": "prod",
                        "host": "prod-sql-01",
                        "authMode": "windows",
                        "databases": ["AppDb", "ReportingDb"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    profile = load_profile("prod", profile_path)
    settings = profile.resolve_settings("ReportingDb")

    assert settings.database == "ReportingDb"


def test_load_profile_rejects_database_override_outside_allowlist(tmp_path) -> None:
    profile_path = tmp_path / "profiles.json"
    profile_path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "id": "prod",
                        "host": "prod-sql-01",
                        "authMode": "windows",
                        "databases": ["AppDb"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    profile = load_profile("prod", profile_path)

    with pytest.raises(ConfigurationError, match="Allowed values: AppDb"):
        profile.resolve_settings("master")


def test_load_profile_requires_existing_profile_id(tmp_path) -> None:
    profile_path = tmp_path / "profiles.json"
    profile_path.write_text(json.dumps({"profiles": []}), encoding="utf-8")

    with pytest.raises(ConfigurationError, match="non-empty 'profiles' array"):
        load_profile("missing", profile_path)


def test_load_profile_rejects_plaintext_password(tmp_path) -> None:
    profile_path = tmp_path / "profiles.json"
    profile_path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "id": "prod",
                        "host": "prod-sql-01",
                        "authMode": "sql",
                        "username": "readonly",
                        "password": "secret",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="cannot define 'password'"):
        load_profile("prod", profile_path)


def test_load_profile_requires_credential_ref_for_sql_auth(tmp_path) -> None:
    profile_path = tmp_path / "profiles.json"
    profile_path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "id": "prod",
                        "host": "prod-sql-01",
                        "authMode": "sql",
                        "username": "readonly",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="must define 'credentialRef'"):
        load_profile("prod", profile_path)
