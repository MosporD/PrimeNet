"""
Master launcher for step-1 raw pulls.

Behavior:
1) Clear target raw folders.
2) Run Huawei, Nokia, Metadata pull scripts in sequence.
3) Print per-script and total duration summaries.
"""

import os
import shutil
import subprocess
import sys
import time


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


TARGET_DIRS = [
    os.path.join(PROJECT_ROOT, "raw", "huawei", "cells"),
    os.path.join(PROJECT_ROOT, "raw", "huawei", "groups"),
    os.path.join(PROJECT_ROOT, "raw", "nokia", "cells"),
    os.path.join(PROJECT_ROOT, "raw", "nokia", "groups"),
    os.path.join(PROJECT_ROOT, "raw", "nokia", "neighbor"),
    os.path.join(PROJECT_ROOT, "raw", "metadata", "cells"),
]


SCRIPTS = [
    ("Huawei", os.path.join(PROJECT_ROOT, "scripts", "pull_huawei_raw.py")),
    ("Nokia", os.path.join(PROJECT_ROOT, "scripts", "pull_nokia_raw.py")),
    ("Metadata", os.path.join(PROJECT_ROOT, "scripts", "pull_metadata_raw.py")),
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


def _run_script(label: str, script_path: str):
    attempt = 0
    total_elapsed = 0.0
    while True:
        attempt += 1
        t0 = time.perf_counter()
        res = subprocess.run([sys.executable, script_path], cwd=PROJECT_ROOT)
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
    nbr = os.path.join(PROJECT_ROOT, "scripts", "pull_nokia_neighbor_raw.py")
    if os.path.isfile(nbr):
        code_nb, _ = _run_script("Nokia Neighbor", nbr)
        if code_nb != 0:
            print("[master] Nokia Neighbor pull failed (optional path); core PM pull rc unchanged.")
    overall_s = time.perf_counter() - overall_t0
    print(f"[master] total elapsed: {overall_s:.2f}s")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
