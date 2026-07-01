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
    cmd = [sys.executable, script] + (args or [])
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT)
    return int(proc.returncode or 0)


def main() -> int:
    ensure_taxonomy_dirs()
    pull_rc = _run(os.path.join("pipeline", "pull", "hourly", "pull_all.py"))
    # pull_rc == 2 => partial pull (some vendors failed). Still load whatever
    # arrived so a single-vendor miss does not stall all ingestion.
    if pull_rc not in (0, 2):
        return pull_rc
    load_rc = _run(os.path.join("pipeline", "load", "hourly", "load_all.py"))
    # Surface the partial-pull signal upward when the load itself succeeded.
    if load_rc == 0 and pull_rc == 2:
        return 2
    return load_rc


if __name__ == "__main__":
    raise SystemExit(main())
