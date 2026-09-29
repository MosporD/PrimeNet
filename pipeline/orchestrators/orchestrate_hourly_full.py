"""
Hourly full orchestrator (safe transition wrapper).

Current behavior:
1) Run legacy raw pull master.
2) Run legacy hourly DB loader.
"""

from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pipeline.paths import PROJECT_ROOT, ensure_taxonomy_dirs


def _run(script_name: str, args: list[str] | None = None) -> int:
    script = os.path.join(PROJECT_ROOT, script_name)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    cmd = [sys.executable, "-u", script] + (args or [])
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT, env=env)
    return int(proc.returncode or 0)


def main() -> int:
    from core.etl_gate import require_etl_enabled

    if not require_etl_enabled():
        return 0
    ensure_taxonomy_dirs()
    pull_rc = _run(os.path.join("pipeline", "pull", "hourly", "pull_all.py"))
    # pull_rc == 2 => partial pull (some vendors failed). Still load whatever
    # arrived so a single-vendor miss does not stall all ingestion.
    if pull_rc not in (0, 2):
        print(
            f"[hourly] pull failed rc={pull_rc} "
            "(both Nokia and Huawei hourly pulls failed — check SFTP / raw paths)",
            file=sys.stderr,
        )
        return pull_rc
    load_rc = _run(os.path.join("pipeline", "load", "hourly", "load_all.py"))
    if load_rc != 0:
        print(
            f"[hourly] load failed rc={load_rc} "
            "(see [done] failed_files / per-file errors above)",
            file=sys.stderr,
        )
    # Surface the partial-pull signal upward when the load itself succeeded.
    if load_rc == 0 and pull_rc == 2:
        return 2
    return load_rc


if __name__ == "__main__":
    raise SystemExit(main())
