"""Print per-table row counts for all app SQLite databases (diagnostics)."""
from __future__ import annotations

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sync_config import (  # noqa: E402
    HUAWEI_GROUPS_DAILY_DB,
    HUAWEI_GROUPS_DB,
    HUAWEI_PM_DAILY_DB,
    HUAWEI_PM_DB,
    KPI_HEADERS_DB,
    METADATA_DB,
    NCMUSERS_DB,
    NEIGHBOR_KPI_DB,
    NOKIA_GROUPS_DAILY_DB,
    NOKIA_GROUPS_DB,
    NOKIA_PM_DAILY_DB,
    NOKIA_PM_DB,
    PROJECT_ROOT,
)


def audit(path: str, label: str) -> None:
    if not os.path.isfile(path):
        print(f"[{label}] MISSING FILE\n  {path}\n")
        return
    conn = sqlite3.connect(path)
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        rows_out: list[tuple[str, int]] = []
        for t in tables:
            try:
                n = int(conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0])
            except Exception as e:
                print(f"  [{label}] {t}: COUNT ERROR {e}")
                continue
            rows_out.append((t, n))
        empty = [t for t, n in rows_out if n == 0]
        sparse = [(t, n) for t, n in rows_out if 0 < n < 5]
        ok = [(t, n) for t, n in rows_out if n >= 5]
        print(f"=== {label} ===")
        print(f"  path: {path}")
        print(f"  tables: {len(tables)}  empty: {len(empty)}  sparse(<5): {len(sparse)}  populated: {len(ok)}")
        if empty:
            print("  EMPTY:", ", ".join(empty))
        if sparse:
            print("  SPARSE:", ", ".join(f"{a}({b})" for a, b in sparse))
        top = sorted(ok, key=lambda x: -x[1])[:10]
        for t, n in top:
            print(f"    {t}: {n:,}")
        if len(ok) > 10:
            print(f"    ... +{len(ok) - 10} more non-empty tables")
        print()
    finally:
        conn.close()


def main() -> None:
    known = [
        ("Nokia PM hourly", NOKIA_PM_DB),
        ("Huawei PM hourly", HUAWEI_PM_DB),
        ("Nokia PM daily", NOKIA_PM_DAILY_DB),
        ("Huawei PM daily", HUAWEI_PM_DAILY_DB),
        ("Nokia groups hourly", NOKIA_GROUPS_DB),
        ("Huawei groups hourly", HUAWEI_GROUPS_DB),
        ("Nokia groups daily", NOKIA_GROUPS_DAILY_DB),
        ("Huawei groups daily", HUAWEI_GROUPS_DAILY_DB),
        ("Metadata", METADATA_DB),
        ("Admin users", NCMUSERS_DB),
        ("Neighbor KPIs", NEIGHBOR_KPI_DB),
        ("KPI headers", KPI_HEADERS_DB),
    ]
    for label, p in known:
        audit(p, label)

    femto = os.path.join(PROJECT_ROOT, "databases", "cells", "femto_pm_cells.db")
    audit(femto, "Femto PM (optional)")


if __name__ == "__main__":
    main()
