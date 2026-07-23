"""
Neighbor-only orchestrator: SFTP pull then full-replace SQLite load.

Scheduled separately from the main PM pipeline (default: every 3 h at :30).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.pipeline_load import run_neighbor_load, run_neighbor_pull  # noqa: E402
from pipeline.paths import ensure_taxonomy_dirs  # noqa: E402


def main() -> int:
    ensure_taxonomy_dirs()
    pull_rc = run_neighbor_pull()
    load_rc = run_neighbor_load(slim=True)
    if pull_rc != 0 and load_rc != 0:
        return max(pull_rc, load_rc)
    if pull_rc != 0:
        # Pull failed but load still ran (full-replace from last raw on disk).
        return 2
    return load_rc


if __name__ == "__main__":
    raise SystemExit(main())
