"""Print raw neighbor files vs row counts (Nokia: neighbor_kpis.db, Huawei: huawei_neighbor_raw.db)."""

from __future__ import annotations

import os
import sqlite3
import sys

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _HERE)
from sync_config import HUAWEI_NEIGHBOR_RAW_DB, NEIGHBOR_KPI_DB, PROJECT_ROOT  # noqa: E402

_TAB = (".csv", ".txt", ".tsv", ".xlsx", ".xls", ".xlsm")


def _list_raw() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for vendor in ("nokia", "huawei"):
        base = os.path.join(PROJECT_ROOT, "raw", vendor, "neighbor")
        files: list[str] = []
        for tech in ("2G", "3G", "4G"):
            d = os.path.join(base, tech)
            if not os.path.isdir(d):
                continue
            for name in sorted(os.listdir(d)):
                if name.lower().endswith(_TAB) and os.path.isfile(os.path.join(d, name)):
                    files.append(f"{vendor}/{tech}/{name}")
        out[vendor] = files
    return out


def _summarize(db_path: str, title: str) -> None:
    print("===", title, "===")
    print("path:", db_path)
    if not os.path.isfile(db_path):
        print("  (missing)")
        print()
        return
    conn = sqlite3.connect(db_path)
    try:
        for (t,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY 1"
        ):
            n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            print(f"  {t}: {n} rows")
    finally:
        conn.close()
    print()


def main() -> int:
    raw = _list_raw()
    print("=== raw neighbor exports ===")
    for vendor, paths in raw.items():
        print(f"  {vendor}: {len(paths)} file(s)")
        for p in paths[:30]:
            print(f"    {p}")
        if len(paths) > 30:
            print(f"    ... +{len(paths) - 30}")
    if not any(raw.values()):
        print("  (none)")
    print()
    _summarize(NEIGHBOR_KPI_DB, "neighbor_kpis.db")
    _summarize(HUAWEI_NEIGHBOR_RAW_DB, "huawei_neighbor_raw.db")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
