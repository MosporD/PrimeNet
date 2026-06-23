"""
Run full DAILY pipeline:
1) pull daily raw files
2) load daily raw files into daily DBs
"""

import os
import subprocess
import sys


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(script_name: str) -> int:
    script = os.path.join(PROJECT_ROOT, "scripts", script_name)
    proc = subprocess.run([sys.executable, script], cwd=PROJECT_ROOT)
    return int(proc.returncode or 0)


def main() -> int:
    rc = _run("pull_all_raw_daily.py")
    if rc != 0:
        return rc
    return _run(os.path.join("pipeline", "load_raw_daily_to_databases.py"))


if __name__ == "__main__":
    raise SystemExit(main())
