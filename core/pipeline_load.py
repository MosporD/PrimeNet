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


def run_neighbor_pull() -> int:
    """Pull Nokia + Huawei neighbor exports from SFTP into raw/."""
    rc = 0
    for rel in (
        "scripts/pipeline/pull_nokia_neighbor_raw.py",
        "scripts/pipeline/pull_huawei_neighbor_raw.py",
    ):
        path = os.path.join(PROJECT_ROOT, rel)
        if not os.path.isfile(path):
            continue
        cmd = [sys.executable, path]
        print(f"[pipeline-load] run: {' '.join(cmd)}")
        proc = subprocess.run(cmd, cwd=PROJECT_ROOT)
        rc = max(rc, int(proc.returncode or 0))
    return rc


def run_neighbor_load(*, slim: bool = True) -> int:
    """
    Full-replace neighbor SQLite from raw exports (Nokia slim + Huawei wide).

    Each loader drops and recreates its tables; no incremental append.
    """
    rc = 0
    nokia = os.path.join(PROJECT_ROOT, "scripts", "load_nokia_neighbor_raw_to_db.py")
    if os.path.isfile(nokia):
        cmd = [sys.executable, nokia]
        if slim:
            cmd.append("--slim")
        print(f"[pipeline-load] run: {' '.join(cmd)}")
        proc = subprocess.run(cmd, cwd=PROJECT_ROOT)
        rc = max(rc, int(proc.returncode or 0))

    huawei = os.path.join(PROJECT_ROOT, "scripts", "load_huawei_neighbor_wide_to_db.py")
    if os.path.isfile(huawei):
        cmd = [sys.executable, huawei]
        print(f"[pipeline-load] run: {' '.join(cmd)}")
        proc = subprocess.run(cmd, cwd=PROJECT_ROOT)
        rc = max(rc, int(proc.returncode or 0))

    return rc
