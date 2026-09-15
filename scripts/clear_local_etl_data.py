#!/usr/bin/env python3
"""
Clear local ETL artefacts (PM DBs, raw CSV, sync downloads) to free disk.

Keeps auth + metadata (map/login still work).

Usage::

    python scripts/clear_local_etl_data.py          # dry-run sizes
    python scripts/clear_local_etl_data.py --yes    # delete

Refuses to run when NCM_ENABLE_ETL=1 so production data is not wiped by mistake.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=True)
except ImportError:
    pass

from core.etl_gate import etl_enabled  # noqa: E402
from sync_config import DATA_ROOT, DATABASES_ROOT  # noqa: E402

# Heavy ETL outputs — safe to rebuild by re-running the pipeline on the server.
CLEAR_DB_DIRS = (
    "cells",
    "Cells Daily",
    "groups",
    "Groups Daily",
    "neighbors",
    "nokia",
    "huawei",
    "network_health",
    "son_analytics",
    "network_balance",
    "daily",
    "pm_plus",
    "femto",
    "radio",
)

# Kept: admin (users/sessions), metadata (sites/cells for map), geo.
KEEP_DB_DIRS = frozenset({"admin", "metadata", "geo"})

CLEAR_ROOT_DIRS = (
    "raw",
    "sync_downloads",
)


def _dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


def _fmt(n: int) -> str:
    gb = n / (1024**3)
    if gb >= 0.1:
        return f"{gb:.2f} GB"
    mb = n / (1024**2)
    return f"{mb:.1f} MB"


def _targets() -> list[Path]:
    out: list[Path] = []
    db_root = Path(DATABASES_ROOT)
    for name in CLEAR_DB_DIRS:
        if name in KEEP_DB_DIRS:
            continue
        p = db_root / name
        if p.exists():
            out.append(p)
    data = Path(DATA_ROOT)
    for name in CLEAR_ROOT_DIRS:
        p = data / name
        if p.exists():
            out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Clear local ETL databases and raw pulls")
    ap.add_argument("--yes", action="store_true", help="Actually delete (default is dry-run)")
    ap.add_argument(
        "--force",
        action="store_true",
        help="Allow wipe even if NCM_ENABLE_ETL=1 (dangerous)",
    )
    args = ap.parse_args()

    if etl_enabled() and not args.force:
        print(
            "[refuse] NCM_ENABLE_ETL=1 — refusing to wipe ETL data.\n"
            "         Set NCM_ENABLE_ETL=0 for local cleanup, or pass --force."
        )
        return 2

    targets = _targets()
    if not targets:
        print("Nothing to clear.")
        return 0

    total = 0
    print(f"DATA_ROOT={DATA_ROOT}")
    for p in targets:
        size = _dir_size(p)
        total += size
        print(f"  {_fmt(size):>10}  {p}")

    print(f"\nTotal reclaimable: {_fmt(total)}")
    if not args.yes:
        print("Dry-run only. Re-run with --yes to delete.")
        return 0

    for p in targets:
        print(f"Removing {p} ...")
        if p.is_file():
            p.unlink(missing_ok=True)
        else:
            shutil.rmtree(p, ignore_errors=True)
        # Recreate empty taxonomy stubs for dirs the app expects.
        if p.name in CLEAR_ROOT_DIRS or p.parent == Path(DATABASES_ROOT):
            p.mkdir(parents=True, exist_ok=True)

    print("Done. Kept databases/admin, databases/metadata, databases/geo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
