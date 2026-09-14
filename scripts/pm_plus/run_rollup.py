#!/usr/bin/env python3
"""Run PM Plus rollup cascade and optional retention."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=True)
except ImportError:
    pass

from core.pm_plus.rollup import apply_retention, rollup_all
from core.pm_plus.schema import init_schema


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Cascade: hour←ROP, day←ROP, week←day, month←week, year←month"
    )
    ap.add_argument("--from", dest="ts_from", default="")
    ap.add_argument("--to", dest="ts_to", default="")
    ap.add_argument("--retention", action="store_true")
    ap.add_argument(
        "--ignore-etl-gate",
        action="store_true",
        help="Run even when NCM_ENABLE_ETL=0",
    )
    args = ap.parse_args()

    if not args.ignore_etl_gate:
        from core.etl_gate import require_etl_enabled

        if not require_etl_enabled():
            print(
                "[pm-plus] tip: use --ignore-etl-gate while Excel ETL stays offline",
                file=sys.stderr,
            )
            return 0

    init_schema()
    out = {
        "rollup": rollup_all(
            ts_from=args.ts_from or None,
            ts_to=args.ts_to or None,
        )
    }
    if args.retention:
        out["retention"] = apply_retention()
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
