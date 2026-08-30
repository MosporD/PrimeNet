#!/usr/bin/env python3
"""CLI entrypoint: run SON ML offline job in an isolated process."""

from __future__ import annotations

import argparse
import json
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.activation_gate import install_sqlite_gate  # noqa: E402

install_sqlite_gate()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build SON ML feature store and scores.")
    parser.add_argument("--force", action="store_true", help="Rebuild even when up to date.")
    args = parser.parse_args()

    from modules.son_analytics.ml.job import build_all

    results = build_all(force=bool(args.force))
    errors = sum(1 for r in results if r.get("error"))
    built = sum(1 for r in results if not r.get("skipped") and not r.get("error"))
    print(json.dumps({"built": built, "errors": errors, "results": results}, default=str))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
