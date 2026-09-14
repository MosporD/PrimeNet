#!/usr/bin/env python3
"""Import Nokia ref_bts spreadsheet → agg rules + KPI formulas."""

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

from core.pm_plus.catalog_import import import_nokia_catalog
from core.pm_plus.schema import init_schema


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "xlsx",
        nargs="?",
        default=str(ROOT / "raw/pm_plus/_debug/ref_bts_performance_measurements_24R3_24R2.xlsx"),
    )
    args = ap.parse_args()
    init_schema()
    path = Path(args.xlsx)
    if not path.exists():
        print(f"missing: {path}", file=sys.stderr)
        return 1
    print(json.dumps(import_nokia_catalog(path), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
