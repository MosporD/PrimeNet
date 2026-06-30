from __future__ import annotations

import os
import subprocess
import sys
import argparse

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Huawei daily pull wrapper")
    parser.add_argument("--category", choices=["all", "cells", "groups"], default="all")
    args = parser.parse_args()

    script = os.path.join(PROJECT_ROOT, "scripts", "pipeline", "pull_huawei_raw_daily.py")
    proc = subprocess.run([sys.executable, script, "--category", args.category], cwd=PROJECT_ROOT)
    return int(proc.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())
