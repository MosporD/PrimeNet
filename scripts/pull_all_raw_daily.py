"""
Master launcher for DAILY raw pulls.

Behavior:
1) Clear DAILY target raw folders.
2) Run Huawei + Nokia DAILY pull scripts in sequence (always run both — a Huawei
   failure or “no files” must not skip Nokia, or the DB load step never runs).
3) Exit 0 if at least one vendor pull succeeded; exit non-zero only if both failed.
4) Print per-script and total duration summaries.
"""

import os
import shutil
import subprocess
import sys
import time


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


TARGET_DIRS = [
    os.path.join(PROJECT_ROOT, "raw", "daily", "huawei", "cells"),
    os.path.join(PROJECT_ROOT, "raw", "daily", "huawei", "groups"),
    os.path.join(PROJECT_ROOT, "raw", "daily", "nokia", "cells"),
    os.path.join(PROJECT_ROOT, "raw", "daily", "nokia", "groups"),
]


SCRIPTS = [
    ("Huawei Daily", os.path.join(PROJECT_ROOT, "scripts", "pull_huawei_raw_daily.py")),
    ("Nokia Daily", os.path.join(PROJECT_ROOT, "scripts", "pull_nokia_raw_daily.py")),
]


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
            print(f"[daily/clear] could not remove {full}: {ex}")


def _run_script(label: str, script_path: str):
    t0 = time.perf_counter()
    res = subprocess.run([sys.executable, script_path], cwd=PROJECT_ROOT)
    elapsed_s = time.perf_counter() - t0
    print(f"[daily/run] {label} finished with code {res.returncode} in {elapsed_s:.2f}s")
    return res.returncode, elapsed_s


def main() -> int:
    print("[daily/master] clearing raw folders...")
    for d in TARGET_DIRS:
        _clear_directory(d)
        print(f"[daily/master] cleared: {d}")

    overall_t0 = time.perf_counter()
    codes: list[int] = []
    for label, script in SCRIPTS:
        code, _ = _run_script(label, script)
        codes.append(int(code or 0))
    overall_s = time.perf_counter() - overall_t0
    print(f"[daily/master] total elapsed: {overall_s:.2f}s")
    # Run *both* vendors even if the first fails (e.g. Huawei empty path must not skip Nokia).
    ok_any = any(c == 0 for c in codes)
    final_rc = 0 if ok_any else (codes[-1] if codes else 1)
    print(f"[daily/master] per-script exit codes: {dict(zip([s[0] for s in SCRIPTS], codes))} -> {final_rc}")
    return final_rc


if __name__ == "__main__":
    raise SystemExit(main())
