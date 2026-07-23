from __future__ import annotations

import os
import subprocess
import sys
import argparse

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Exit codes shared with the orchestrator / scheduler callers.
EXIT_OK = 0
EXIT_ALL_FAILED = 1
EXIT_PARTIAL = 2


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
        ("nokia", ["pipeline", "pull", "nokia", "all", "hourly", "pull_all.py"]),
        ("huawei", ["pipeline", "pull", "huawei", "all", "hourly", "pull_all.py"]),
    ]
    results: dict[str, int] = {}
    for name, parts in critical:
        rc = _run(parts, args.category)
        results[name] = rc
        if rc != 0:
            # Do not abort the whole cycle: a transient miss for one vendor must
            # not block the other vendor or the downstream load step.
            print(
                f"[pull] warning: {name} hourly pull exited {rc}; "
                "continuing with remaining vendors",
                file=sys.stderr,
            )

    succeeded = [n for n, rc in results.items() if rc == 0]
    failed = [n for n, rc in results.items() if rc != 0]

    if failed:
        print(
            f"[pull] vendor summary: ok={succeeded or ['-']} failed={failed}",
            file=sys.stderr,
        )

    if not succeeded:
        return EXIT_ALL_FAILED
    if failed:
        return EXIT_PARTIAL
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
