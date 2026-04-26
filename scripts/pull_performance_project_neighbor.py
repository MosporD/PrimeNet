"""
Pull latest Nokia neighbor exports for 2G, 3G, and 4G from NetAct SFTP.

Remote base (NetAct):
  /d/oss/global/var/pm/shared/content3/scheduler/exportCustom/Malek/Performance Project Neighbor

Expected under that folder: 2G/, 3G/, 4G/ (each may contain dated subfolders when descend is on).

Local output:
  <project>/raw/nokia/neighbor/2G/
  <project>/raw/nokia/neighbor/3G/
  <project>/raw/nokia/neighbor/4G/

Uses the same host/user/password as Nokia PM (sync_config.NOKIA_PM_SERVER).
Override paths with env NOKIA_NEIGHBOR_ROOT or NOKIA_NEIGHBOR_DIR_2G / _3G / _4G.

Then load into SQLite:
  python scripts/load_nokia_neighbor_raw_to_db.py
"""

from __future__ import annotations

import os
import subprocess
import sys

REMOTE_NEIGHBOR_BASE = (
    "/d/oss/global/var/pm/shared/content3/scheduler/exportCustom/Malek/Performance Project Neighbor"
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    puller = os.path.join(PROJECT_ROOT, "scripts", "pull_nokia_neighbor_raw.py")
    if not os.path.isfile(puller):
        print(f"[neighbor] missing {puller}")
        return 1

    env = os.environ.copy()
    env.setdefault("NOKIA_NEIGHBOR_ROOT", REMOTE_NEIGHBOR_BASE)

    print(f"[neighbor] remote base: {env.get('NOKIA_NEIGHBOR_ROOT')}")
    print(f"[neighbor] running: {puller}")

    proc = subprocess.run(
        [sys.executable, puller],
        cwd=PROJECT_ROOT,
        env=env,
    )
    return int(proc.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())
