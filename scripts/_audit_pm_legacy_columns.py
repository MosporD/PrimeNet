"""Audit PM/group tables for legacy cell_name/timestamp vs vendor-native axis columns."""
from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import sqlite3

from sync_config import (
    HUAWEI_GROUPS_DAILY_DB,
    HUAWEI_GROUPS_DB,
    HUAWEI_PM_DAILY_DB,
    HUAWEI_PM_DB,
    NOKIA_GROUPS_DAILY_DB,
    NOKIA_GROUPS_DB,
    NOKIA_PM_DAILY_DB,
    NOKIA_PM_DB,
)
from modules.performance.routes import (
    _PM_STATIC_COLS,
    _axis_column_nonempty_count,
    _build_pm_table_column_layout,
    _resolve_pm_axis_columns_sqlite,
    _sqlite_ident,
    _table_technology,
)

PM_DBS = [
    ("Nokia PM hourly", "Nokia", NOKIA_PM_DB),
    ("Huawei PM hourly", "Huawei", HUAWEI_PM_DB),
    ("Nokia PM daily", "Nokia", NOKIA_PM_DAILY_DB),
    ("Huawei PM daily", "Huawei", HUAWEI_PM_DAILY_DB),
    ("Nokia groups hourly", "Nokia", NOKIA_GROUPS_DB),
    ("Huawei groups hourly", "Huawei", HUAWEI_GROUPS_DB),
    ("Nokia groups daily", "Nokia", NOKIA_GROUPS_DAILY_DB),
    ("Huawei groups daily", "Huawei", HUAWEI_GROUPS_DAILY_DB),
]

TECH_ORDER = ("2G", "3G", "4G", "5G")


def _check_pm_table_layout(
    vendor: str,
    technology: str,
    cols: list[str],
    cell_col: str | None,
    time_col: str | None,
    row_count: int,
) -> list[str]:
    issues: list[str] = []
    if row_count <= 0:
        return issues
    static_cfg = _PM_STATIC_COLS.get(vendor, {}).get(technology, [])
    missing_static = [c for c in static_cfg if c not in ("cell_name", "timestamp") and c not in cols]
    if missing_static:
        issues.append(f"STATIC_COLS_MISSING:{','.join(missing_static)}")
    static_cols, ordered = _build_pm_table_column_layout(
        vendor, technology, cols, cell_col, time_col
    )
    if cell_col and "cell_name" not in static_cols:
        issues.append("OUTPUT_MISSING_CELL_NAME_SLOT")
    if time_col and "timestamp" not in static_cols:
        issues.append("OUTPUT_MISSING_TIMESTAMP_SLOT")
    if static_cols[:2] != [c for c in ("timestamp", "cell_name") if c in static_cols]:
        issues.append(f"LEGACY_ORDER_BROKEN:{static_cols}")
    dup_axis = [
        c for c in (cell_col, time_col)
        if c and c in ordered[len(static_cols):] and c not in ("cell_name", "timestamp")
    ]
    if dup_axis:
        issues.append(f"DUPLICATE_AXIS_IN_KPI:{','.join(dup_axis)}")
    return issues


def audit_db(label: str, vendor: str, path: str) -> list[dict]:
    issues: list[dict] = []
    if not os.path.isfile(path):
        return [{"db": label, "issue": "MISSING_FILE", "path": path}]

    conn = sqlite3.connect(path, timeout=60)
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]

    for table in tables:
        tech = _table_technology(table) or "?"
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({_sqlite_ident(table)})").fetchall()]
        if not cols:
            continue

        cell_col, time_col = _resolve_pm_axis_columns_sqlite(conn, table)
        row_count = int(conn.execute(f"SELECT COUNT(*) FROM {_sqlite_ident(table)}").fetchone()[0])

        legacy_cell = "cell_name" in cols
        legacy_ts = "timestamp" in cols
        legacy_cell_n = _axis_column_nonempty_count(conn, table, "cell_name") if legacy_cell else -1
        legacy_ts_n = _axis_column_nonempty_count(conn, table, "timestamp") if legacy_ts else -1

        entry = {
            "db": label,
            "table": table,
            "tech": tech,
            "rows": row_count,
            "resolved_cell": cell_col,
            "resolved_time": time_col,
            "legacy_cell_nonempty": legacy_cell_n,
            "legacy_ts_nonempty": legacy_ts_n,
            "issues": [],
        }

        if row_count == 0:
            entry["issues"].append("EMPTY_TABLE")
        if not cell_col:
            entry["issues"].append("NO_CELL_AXIS")
        elif _axis_column_nonempty_count(conn, table, cell_col) == 0 and row_count > 0:
            entry["issues"].append("CELL_AXIS_EMPTY")
        if not time_col:
            entry["issues"].append("NO_TIME_AXIS")
        elif _axis_column_nonempty_count(conn, table, time_col) == 0 and row_count > 0:
            entry["issues"].append("TIME_AXIS_EMPTY")

        if legacy_cell and legacy_cell_n == 0 and cell_col and cell_col != "cell_name" and row_count > 0:
            entry["note"] = f"legacy cell_name empty; uses {cell_col!r}"

        if "CELLS" in table.upper() and tech in TECH_ORDER:
            layout_issues = _check_pm_table_layout(vendor, tech, cols, cell_col, time_col, row_count)
            static_cols, ordered = _build_pm_table_column_layout(
                vendor, tech, cols, cell_col, time_col
            )
            entry["static_output"] = static_cols
            entry["first_kpi_cols"] = ordered[len(static_cols) : len(static_cols) + 3]
            entry["issues"].extend(layout_issues)

        if entry["issues"]:
            issues.append(entry)

    conn.close()
    return issues


def main() -> int:
    all_issues: list[dict] = []
    summary: list[str] = []

    print("PM / groups legacy column audit\n" + "=" * 72)
    for label, vendor, path in PM_DBS:
        issues = audit_db(label, vendor, path)
        conn = sqlite3.connect(path, timeout=60) if os.path.isfile(path) else None
        tables_ok = []
        if conn:
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ).fetchall()
            ]
            for table in tables:
                if "GROUP" in table.upper() and "CELL" not in table.upper():
                    continue
                if "CELL" not in table.upper() and table not in ("groups", "group_cells"):
                    continue
                tech = _table_technology(table) or "?"
                cols = [r[1] for r in conn.execute(f"PRAGMA table_info({_sqlite_ident(table)})").fetchall()]
                cc, tc = _resolve_pm_axis_columns_sqlite(conn, table)
                n = int(conn.execute(f"SELECT COUNT(*) FROM {_sqlite_ident(table)}").fetchone()[0])
                tables_ok.append((table, tech, n, cc, tc))
            conn.close()

        print(f"\n{label} ({os.path.basename(path)})")
        for table, tech, n, cc, tc in tables_ok:
            flag = ""
            matching = [i for i in issues if i.get("table") == table]
            if matching:
                flag = " *** " + "; ".join(matching[0]["issues"])
            print(f"  {table:22} tech={tech:3} rows={n:>8,}  cell={cc!r:20} time={tc!r}{flag}")

        all_issues.extend(issues)

    print("\n" + "=" * 72)
    if not all_issues:
        print("All checked tables: axis resolution and static column order OK.")
        return 0

    print(f"Issues found: {len(all_issues)} table(s)\n")
    for e in all_issues:
        print(f"- {e['db']} / {e['table']}")
        for iss in e["issues"]:
            print(f"    {iss}")
        if e.get("static_output"):
            print(f"    static_output: {e['static_output']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
