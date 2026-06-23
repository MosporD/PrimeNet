"""
Watcher one-cycle orchestrator.
"""

from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pipeline.paths import PROJECT_ROOT, ensure_taxonomy_dirs


def main() -> int:
    ensure_taxonomy_dirs()
    script = os.path.join(PROJECT_ROOT, "scripts", "pipeline", "watch_remote_new_files_and_pull.py")
    proc = subprocess.run([sys.executable, script, "--once"], cwd=PROJECT_ROOT)
    return int(proc.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())
