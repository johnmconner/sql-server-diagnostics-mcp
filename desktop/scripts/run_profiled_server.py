from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    repo_src = repo_root / "src"
    sys.path.insert(0, str(repo_src))

    from sql_tshooter.profiled_server import main as profiled_main

    profiled_main(sys.argv[1:])


if __name__ == "__main__":
    main()
