from __future__ import annotations

import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _run(path_parts: list[str]) -> int:
    script = os.path.join(PROJECT_ROOT, *path_parts)
    env = os.environ.copy()
    env["RAW_PULL_AUTO_LOAD"] = "0"
    proc = subprocess.run([sys.executable, script], cwd=PROJECT_ROOT, env=env)
    return int(proc.returncode or 0)


def main() -> int:
    critical = [
        ["pipeline", "pull", "nokia", "all", "hourly", "pull_all.py"],
        ["pipeline", "pull", "huawei", "all", "hourly", "pull_all.py"],
    ]
    for parts in critical:
        rc = _run(parts)
        if rc != 0:
            return rc

    supplementary = [
        ["scripts", "pipeline", "pull_nokia_neighbor_raw.py"],
        ["scripts", "pipeline", "pull_huawei_neighbor_raw.py"],
    ]
    for parts in supplementary:
        rc = _run(parts)
        if rc != 0:
            print(f"[pull] warning: {parts[-1]} exited {rc} (non-fatal, continuing)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
