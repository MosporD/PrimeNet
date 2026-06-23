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
    rc = _run(os.path.join("pipeline", "pull", "hourly", "pull_all.py"))
    if rc != 0:
        return rc
    return _run(os.path.join("pipeline", "load", "hourly", "load_all.py"))


if __name__ == "__main__":
    raise SystemExit(main())
