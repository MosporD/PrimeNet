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
    for parts in (
        ["pipeline", "pull", "nokia", "all", "daily", "pull_all.py"],
        ["pipeline", "pull", "huawei", "all", "daily", "pull_all.py"],
    ):
        rc = _run(parts)
        if rc != 0:
            return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
