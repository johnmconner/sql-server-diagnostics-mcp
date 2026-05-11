from __future__ import annotations

import os
import sys
from pathlib import Path


def load_dotenv(env_path: Path) -> None:
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip()


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    env_path = repo_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    os.environ.setdefault(
        "SQL_TSHOOTER_LOG_PATH",
        str(repo_root / "logs" / "sql-tshooter.log"),
    )

    src_path = str(repo_root / "src")
    sys.path.insert(0, src_path)

    from sql_tshooter.server import main as server_main

    server_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
