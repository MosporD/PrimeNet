"""
Canonical daily load entrypoint.

Safe-transition wrapper that delegates to the existing daily loader script.
"""

from __future__ import annotations

import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def main() -> int:
    script = os.path.join(PROJECT_ROOT, "scripts", "pipeline", "load_raw_daily_to_databases.py")
    proc = subprocess.run([sys.executable, script], cwd=PROJECT_ROOT)
    return int(proc.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())
