from argparse import Namespace

from sql_tshooter.launcher import build_codex_command


def test_build_codex_command_for_cli_mode() -> None:
    args = Namespace(
        mode="cli",
        profile_file="/tmp/profiles.json",
        profile="prod",
        database="AppDb",
        workspace=".",
        codex_command="codex",
        codex_args=["--", "--search", "investigate slow queries"],
    )

    command = build_codex_command(args)

    assert command[0] == "codex"
    assert "-C" in command
    assert "--search" in command
    assert "investigate slow queries" in command
    assert any("mcp_servers.sql-tshooter.command=" in part for part in command)
    assert any("sql_tshooter.profiled_server" in part for part in command)
    assert any('"--database", "AppDb"' in part for part in command)


def test_build_codex_command_for_desktop_mode() -> None:
    args = Namespace(
        mode="desktop",
        profile_file="/tmp/profiles.json",
        profile="prod",
        database=None,
        workspace=".",
        codex_command="codex",
        codex_args=["--", "--disable", "some-feature"],
    )

    command = build_codex_command(args)

    assert command[0] == "codex"
    assert "app" in command
    assert "-C" not in command
    assert "--disable" in command
    assert "some-feature" in command
