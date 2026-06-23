"""
Master launcher for step-1 raw pulls.

Behavior:
1) Clear target raw folders.
2) Run Huawei, Nokia, Metadata pull scripts in sequence.
3) Pull Nokia + Huawei neighbor exports (optional SFTP paths).
4) Load ``neighbor_kpis.db`` (Nokia neighbor tables only) and Huawei wide raw DB.
5) Print per-script and total duration summaries.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline.paths import PM_RATS, raw_path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _hourly_pm_raw_dirs() -> list[str]:
    dirs: list[str] = []
    for vendor in ("huawei", "nokia"):
        for domain in ("cells", "groups"):
            for tech in PM_RATS:
                dirs.append(raw_path(vendor, domain, tech, "hourly"))
            # Legacy staging folder (Huawei single-export split)
            dirs.append(raw_path(vendor, domain, "all", "hourly"))
    return dirs


TARGET_DIRS = _hourly_pm_raw_dirs() + [
    raw_path("huawei", "neighbor", "all", "hourly"),
    raw_path("nokia", "neighbor", "all", "hourly"),
    raw_path("metadata", "cells", "all", "snapshot"),
]


_SCR = ("scripts", "pipeline")
SCRIPTS = [
    ("Huawei", os.path.join(PROJECT_ROOT, *_SCR, "pull_huawei_raw.py")),
    ("Nokia", os.path.join(PROJECT_ROOT, *_SCR, "pull_nokia_raw.py")),
    ("Metadata", os.path.join(PROJECT_ROOT, *_SCR, "pull_metadata_raw.py")),
]

# Retry policy for transient SFTP/network failures.
_MAX_RETRIES_PER_SCRIPT = 2
_RETRY_DELAY_SECONDS = 8


def _clear_directory(path: str) -> None:
    os.makedirs(path, exist_ok=True)
    for name in os.listdir(path):
        full = os.path.join(path, name)
        try:
            if os.path.isdir(full):
                shutil.rmtree(full)
            else:
                os.remove(full)
        except OSError as ex:
            print(f"[clear] could not remove {full}: {ex}")


def _run_script(label: str, script_path: str, extra_args: list[str] | None = None):
    attempt = 0
    total_elapsed = 0.0
    while True:
        attempt += 1
        t0 = time.perf_counter()
        cmd = [sys.executable, script_path]
        if extra_args:
            cmd.extend(extra_args)
        res = subprocess.run(cmd, cwd=PROJECT_ROOT)
        elapsed_s = time.perf_counter() - t0
        total_elapsed += elapsed_s
        print(f"[run] {label} attempt {attempt} finished with code {res.returncode} in {elapsed_s:.2f}s")
        if res.returncode == 0:
            return 0, total_elapsed
        if attempt > _MAX_RETRIES_PER_SCRIPT:
            return res.returncode, total_elapsed
        print(f"[run] {label} retrying in {_RETRY_DELAY_SECONDS}s...")
        time.sleep(_RETRY_DELAY_SECONDS)


def main() -> int:
    print("[master] clearing raw folders...")
    for d in TARGET_DIRS:
        _clear_directory(d)
        print(f"[master] cleared: {d}")

    overall_t0 = time.perf_counter()
    rc = 0
    for label, script in SCRIPTS:
        code, _ = _run_script(label, script)
        if code != 0:
            rc = code
            break
    nbr = os.path.join(PROJECT_ROOT, "scripts", "pipeline", "pull_nokia_neighbor_raw.py")
    if os.path.isfile(nbr):
        code_nb, _ = _run_script("Nokia Neighbor", nbr)
        if code_nb != 0:
            print("[master] Nokia Neighbor pull failed (optional path); core PM pull rc unchanged.")
    nbr_h = os.path.join(PROJECT_ROOT, "scripts", "pipeline", "pull_huawei_neighbor_raw.py")
    if os.path.isfile(nbr_h):
        code_h, _ = _run_script("Huawei Neighbor", nbr_h)
        if code_h != 0:
            print("[master] Huawei Neighbor pull failed (optional path); core PM pull rc unchanged.")
    wide_h = os.path.join(PROJECT_ROOT, "scripts", "load_huawei_neighbor_wide_to_db.py")
    if os.path.isfile(wide_h):
        _run_script("Huawei Neighbor wide DB", wide_h)

    neighbor_load = os.path.join(PROJECT_ROOT, "scripts", "load_nokia_neighbor_raw_to_db.py")
    if os.path.isfile(neighbor_load):
        code_nk, _ = _run_script("Nokia Neighbor KPI DB", neighbor_load, extra_args=["--slim"])
        if code_nk != 0:
            print("[master] Nokia Neighbor KPI DB load failed (optional); check raw/nokia/neighbor).")

    load_script = os.path.join(PROJECT_ROOT, "scripts", "pipeline", "load_raw_csv_to_databases.py")
    if os.path.isfile(load_script):
        code_ld, _ = _run_script("Hourly PM + groups load", load_script, ["--scope", "hourly"])
        if code_ld != 0:
            rc = code_ld
            print("[master] hourly PM load failed after raw pull.")

    overall_s = time.perf_counter() - overall_t0
    print(f"[master] total elapsed: {overall_s:.2f}s")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
