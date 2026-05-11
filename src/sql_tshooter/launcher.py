"""Dual-mode launcher for Codex CLI and Codex Desktop."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from sql_tshooter.profiles import default_profiles_path


SERVER_NAME = "sql-tshooter"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sql-tshooter-launch",
        description="Launch Codex CLI or Codex Desktop with a selected sql-tshooter target profile.",
    )
    parser.add_argument(
        "--mode",
        choices=("cli", "desktop"),
        default="cli",
        help="Whether to launch Codex CLI or Codex Desktop.",
    )
    parser.add_argument(
        "--profile-file",
        default=str(default_profiles_path()),
        help="Path to the JSON profile file.",
    )
    parser.add_argument(
        "--profile",
        required=True,
        help="Profile id to attach to this Codex launch.",
    )
    parser.add_argument(
        "--database",
        help="Override the default database for the selected profile.",
    )
    parser.add_argument(
        "--workspace",
        default=".",
        help="Workspace path for Codex.",
    )
    parser.add_argument(
        "--codex-command",
        default="codex",
        help="Codex executable to launch.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved Codex command instead of launching it.",
    )
    parser.add_argument(
        "codex_args",
        nargs=argparse.REMAINDER,
        help="Additional arguments passed through to Codex. Prefix them with '--'.",
    )
    return parser


def build_codex_command(args: argparse.Namespace) -> list[str]:
    workspace = str(Path(args.workspace).resolve())
    profile_file = str(Path(args.profile_file).resolve())
    mcp_args = [
        "-m",
        "sql_tshooter.profiled_server",
        "--profile-file",
        profile_file,
        "--profile",
        args.profile,
    ]
    if args.database:
        mcp_args.extend(["--database", args.database])

    command = [args.codex_command]
    command.extend(
        [
            "-c",
            f'mcp_servers.{SERVER_NAME}.command={json.dumps(sys.executable)}',
            "-c",
            f"mcp_servers.{SERVER_NAME}.args={json.dumps(mcp_args)}",
        ]
    )

    passthrough = list(args.codex_args)
    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]

    if args.mode == "desktop":
        command.append("app")
        command.extend(passthrough)
        command.append(workspace)
        return command

    command.extend(["-C", workspace])
    command.extend(passthrough)
    return command


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = build_codex_command(args)
    if args.dry_run:
        print(" ".join(command))
        return 0
    completed = subprocess.run(command, check=False)
    return int(completed.returncode)
