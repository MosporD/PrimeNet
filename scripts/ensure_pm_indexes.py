#!/usr/bin/env python3
"""CLI: create PM SQLite indexes for fast cell/group + time API queries."""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pm_indexes import ensure_all_pm_databases, ensure_pm_database  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Ensure PM SQLite cell/time indexes")
    parser.add_argument(
        "--scope",
        choices=("hourly", "daily", "both"),
        default="both",
        help="Which PM scope to index (default: both)",
    )
    parser.add_argument(
        "--category",
        choices=("all", "cells", "groups"),
        default="all",
        help="Limit to cells or groups DBs (default: all)",
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        help="Index a single database file instead of all configured PM DBs",
    )
    parser.add_argument(
        "--no-analyze",
        action="store_true",
        help="Skip ANALYZE after creating indexes",
    )
    args = parser.parse_args()

    categories = ("cells", "groups") if args.category == "all" else (args.category,)
    analyze = not args.no_analyze

    if args.db:
        rep = ensure_pm_database(args.db, analyze=analyze)
        if rep.get("missing"):
            print(f"Missing file: {args.db}")
            return 1
        for table, idxs in sorted((rep.get("tables") or {}).items()):
            print(f"  {table}: {', '.join(idxs)}")
        print(f"Done: {len(rep.get('indexes') or [])} index(es) on {args.db}")
        return 0

    scopes = ("hourly", "daily") if args.scope == "both" else (args.scope,)
    for scope in scopes:
        payload = ensure_all_pm_databases(scope=scope, categories=categories, analyze=analyze)
        for msg in payload.get("messages") or []:
            print(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
