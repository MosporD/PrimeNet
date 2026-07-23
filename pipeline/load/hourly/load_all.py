"""
Canonical hourly load entrypoint.

PM/groups only — neighbor SQLite is loaded on its own schedule (see orchestrate_neighbor_sync.py).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def main() -> int:
    parser = argparse.ArgumentParser(description="Hourly loader wrapper")
    parser.add_argument("--category", action="append", choices=["cells", "groups"])
    args = parser.parse_args()
    script = os.path.join(PROJECT_ROOT, "scripts", "pipeline", "load_raw_csv_to_databases.py")
    cmd = [sys.executable, script, "--scope", "hourly"]
    for category in args.category or []:
        cmd.extend(["--category", category])
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT)
    return int(proc.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())
