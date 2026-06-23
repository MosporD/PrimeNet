#!/usr/bin/env python3
"""Build Network Health precomputed tables (run daily after PM daily load).

Examples:
  python scripts/build_network_health_precalc.py
  python scripts/build_network_health_precalc.py --vendor nokia --rat 3G --force
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from modules.network_health.precalc_job import build_all, build_vendor_rat  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_network_health_precalc")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Network Health precalc SQLite store")
    parser.add_argument("--vendor", help="Vendor key (nokia, huawei)")
    parser.add_argument("--rat", help="RAT key (3G, 4G-FDD, …)")
    parser.add_argument("--force", action="store_true", help="Rebuild even if PM fingerprint unchanged")
    parser.add_argument(
        "--shortlist-only",
        action="store_true",
        help="Only precompute the KPI shortlist (default: all KPIs with data)",
    )
    args = parser.parse_args()

    all_kpis = False if args.shortlist_only else None
    if args.vendor and args.rat:
        result = build_vendor_rat(
            args.vendor.strip().lower(),
            args.rat.strip(),
            force=args.force,
            all_kpis=all_kpis,
        )
        print(json.dumps(result, indent=2))
        return 0 if "error" not in result else 1

    results = build_all(force=args.force, all_kpis=all_kpis)
    print(json.dumps(results, indent=2))
    errors = [r for r in results if r.get("error")]
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
