from __future__ import annotations

import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
)


def main() -> int:
    script = os.path.join(PROJECT_ROOT, "scripts", "pipeline", "load_raw_csv_to_databases.py")
    proc = subprocess.run(
        [sys.executable, script, "--scope", "hourly", "--category", "cells", "--category", "groups"],
        cwd=PROJECT_ROOT,
    )
    return int(proc.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())
