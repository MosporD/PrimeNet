from __future__ import annotations

import os
import subprocess
import sys
import argparse

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _run(path_parts: list[str], category: str | None = None) -> int:
    script = os.path.join(PROJECT_ROOT, *path_parts)
    env = os.environ.copy()
    env["RAW_PULL_AUTO_LOAD"] = "0"
    cmd = [sys.executable, script]
    if category:
        cmd.extend(["--category", category])
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT, env=env)
    return int(proc.returncode or 0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Hourly pull wrapper")
    parser.add_argument("--category", choices=["cells", "groups"])
    args = parser.parse_args()

    critical = [
        ["pipeline", "pull", "nokia", "all", "hourly", "pull_all.py"],
        ["pipeline", "pull", "huawei", "all", "hourly", "pull_all.py"],
    ]
    for parts in critical:
        rc = _run(parts, args.category)
        if rc != 0:
            return rc

    if args.category:
        return 0

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
