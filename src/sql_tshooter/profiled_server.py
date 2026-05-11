"""Launch the SQL TShooter MCP server from a named target profile."""

from __future__ import annotations

import argparse

from sql_tshooter.preflight import load_profile_settings
from sql_tshooter.server import main_with_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sql-tshooter-profiled-mcp",
        description="Launch the SQL TShooter MCP server from a named profile.",
    )
    parser.add_argument(
        "--profile-file",
        help="Path to the JSON profile file. Defaults to the standard sql-tshooter profile path.",
    )
    parser.add_argument(
        "--profile",
        required=True,
        help="Profile id to launch.",
    )
    parser.add_argument(
        "--database",
        help="Override the configured default database for this launch.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    settings = load_profile_settings(
        profile_name=args.profile,
        profile_file=args.profile_file,
        database=args.database,
    )
    main_with_settings(settings)
