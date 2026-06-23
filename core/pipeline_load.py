"""Run PM raw → SQLite load subprocesses."""

from __future__ import annotations

import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_pm_load(
    *,
    scope: str = "hourly",
    category: str = "all",
    vendor: str = "all",
    skip_kpi_db: bool = False,
) -> int:
    """
    Invoke ``load_raw_csv_to_databases.py``.

    ``vendor``: ``all`` | ``nokia`` | ``huawei``
    """
    script = os.path.join(PROJECT_ROOT, "scripts", "pipeline", "load_raw_csv_to_databases.py")
    if not os.path.isfile(script):
        print(f"[pipeline-load] missing script: {script}")
        return 1

    cmd = [sys.executable, script, "--scope", scope, "--category", category]
    if vendor and vendor != "all":
        cmd.extend(["--vendor", vendor])
    if skip_kpi_db:
        cmd.append("--skip-kpi-db")
    print(f"[pipeline-load] run: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT)
    return int(proc.returncode or 0)
