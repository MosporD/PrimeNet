import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sync_config import HUAWEI_PM_DAILY_DB, HUAWEI_PM_DB

import sqlite3
from modules.son_analytics.pm_helpers import vendor_pm_sources, PM_DATA_SCOPE, collect_all_kpi_benchmarks
from modules.network_health.logic import list_kpi_columns
from modules.network_health import config as cfg
from modules.network_health.precalc_store import load_payload, get_build_meta

print("HUAWEI_PM_DAILY_DB", HUAWEI_PM_DAILY_DB, "exists", os.path.isfile(HUAWEI_PM_DAILY_DB))
print("HUAWEI_PM_DB", HUAWEI_PM_DB, "exists", os.path.isfile(HUAWEI_PM_DB))

for rat in ["2G", "3G", "4G-FDD", "4G-TDD", "5G"]:
    pm_tech = cfg.pm_technology_for_rat(rat)
    sources = vendor_pm_sources("huawei", pm_tech, PM_DATA_SCOPE)
    print("\n=== huawei", rat, "pm_tech", pm_tech, "===")
    print("sources:", sources)
    if not sources:
        continue
    db, table = sources[0][1], sources[0][2]
    conn = sqlite3.connect(db)
    n = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    print("rows in table:", n)
    conn.close()
    kpis = list_kpi_columns("huawei", rat)
    print("kpis:", len(kpis))
    if kpis and n:
        from modules.son_analytics.pm_helpers import _resolve_pm_table_axes_bulk
        conn = sqlite3.connect(db)
        axes = _resolve_pm_table_axes_bulk(conn, table, kpis[:3])
        print("  axes (cell, ts, kpis):", axes[0] if axes else None, axes[1] if axes else None, len(axes[2]) if axes else 0)
        conn.close()
        raw = collect_all_kpi_benchmarks(
            kpis[:2],
            vendor="huawei",
            technology=pm_tech,
            scope=PM_DATA_SCOPE,
            lookback_days=7,
            min_history_days=3,
        )
        for k, v in raw.items():
            print("  benchmark", k, "cells", len(v))
        conn = sqlite3.connect(db)
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
        ts_cols = [c for c in cols if any(x in c.lower() for x in ("time", "date", "period"))]
        print("  ts cols", ts_cols[:5])
        if ts_cols:
            samples = conn.execute(
                f'SELECT DISTINCT "{ts_cols[0]}" FROM "{table}" WHERE "{ts_cols[0]}" IS NOT NULL LIMIT 15'
            ).fetchall()
            print("  distinct dates (sample)", samples)
        from modules.son_analytics.pm_helpers import parse_pm_timestamp
        for s in (samples or []):
            print("  parsed", s[0], "->", parse_pm_timestamp(s[0]))
        conn.close()
    meta = get_build_meta("huawei", rat)
    payload = load_payload("huawei", rat)
    print("precalc meta:", meta)
    print("precalc loaded:", payload is not None, "tables", len((payload or {}).get("tables") or {}))
