"""
Load DAILY raw files into DAILY cells/groups databases.
"""

import os
import subprocess
import sys


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    script = os.path.join(PROJECT_ROOT, "scripts", "pipeline", "load_raw_csv_to_databases.py")
    cmd = [sys.executable, script, "--scope", "daily", "--skip-kpi-db"]
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT)
    return int(proc.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())
