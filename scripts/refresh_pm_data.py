#!/usr/bin/env python3
"""
Clear Nokia and Huawei PM SQLite stores, then run SFTP pulls + ingest (scheduler logic).

After this completes, open Performance in the browser and refresh (or change vendor/tech)
so KPI headers reload from /api/performance/kpi_columns.

Usage (from project root):
  python scripts/refresh_pm_data.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Load .env before sync_config (SFTP hosts, etc.)
os.chdir(ROOT)


def _p(msg: str) -> None:
    print(msg, flush=True)


def main() -> int:
    from sync.pm_processor import clear_huawei_pm_tables, clear_nokia_pm_tables
    from sync.scheduler import pull_huawei_pm, pull_nokia_pm

    _p('Clearing Nokia PM tables…')
    clear_nokia_pm_tables()
    _p('Clearing Huawei PM tables…')
    clear_huawei_pm_tables()

    _p('Nokia PM: download + ingest (SFTP may take several minutes)…')
    pull_nokia_pm()

    _p('Huawei PM: download + ingest…')
    pull_huawei_pm()

    _p('Done. In the app, open Performance and refresh the page (F5) to reload KPI headers.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
