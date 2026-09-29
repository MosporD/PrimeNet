"""
Daily full orchestrator (safe transition wrapper).
"""

from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pipeline.paths import PROJECT_ROOT, ensure_taxonomy_dirs


def _run(script_name: str) -> int:
    script = os.path.join(PROJECT_ROOT, script_name)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.run(
        [sys.executable, "-u", script],
        cwd=PROJECT_ROOT,
        env=env,
    )
    return int(proc.returncode or 0)


def main() -> int:
    from core.etl_gate import require_etl_enabled

    if not require_etl_enabled():
        return 0
    ensure_taxonomy_dirs()
    pull_rc = _run(os.path.join("pipeline", "pull", "daily", "pull_all.py"))
    # pull_rc == 2 => partial pull (some vendors failed). Still load whatever
    # arrived so a single-vendor miss does not stall all ingestion.
    if pull_rc not in (0, 2):
        print(
            f"[daily] pull failed rc={pull_rc} "
            "(both Nokia and Huawei daily pulls failed — check SFTP / raw paths)",
            file=sys.stderr,
        )
        return pull_rc
    load_rc = _run(os.path.join("pipeline", "load", "daily", "load_all.py"))
    if load_rc != 0:
        print(
            f"[daily] load failed rc={load_rc} "
            "(see [done] failed_files / per-file errors above)",
            file=sys.stderr,
        )
    if load_rc == 0 and pull_rc == 2:
        return 2
    return load_rc


if __name__ == "__main__":
    raise SystemExit(main())
