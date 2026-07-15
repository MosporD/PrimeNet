#!/usr/bin/env python3
"""
OPTIONAL one-time migration: split monotable PM cells into area partitions.

Preferred rollout does NOT require this script:
  - New loads write only to area tables (…__WEST_AMMAN, etc.)
  - APIs dual-read monotable + area until retention drains the legacy table

Use this only if you want to backfill history early instead of waiting for
retention.

Usage:
  python scripts/migrate_pm_to_area_tables.py            # all vendor cell DBs
  python scripts/migrate_pm_to_area_tables.py --dry-run
  python scripts/migrate_pm_to_area_tables.py --drop-base  # after verifying partitions
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pm_indexes import ensure_table_indexes
from core.site_area import (
    build_cell_area_index,
    list_pm_partition_tables,
    pm_area_table_name,
    resolve_cell_area,
)
from sync_config import (
    HUAWEI_PM_DAILY_DB,
    HUAWEI_PM_DB,
    NOKIA_PM_DAILY_DB,
    NOKIA_PM_DB,
    PM_TECHNOLOGIES,
    pm_table_name,
)


_CELL_ALIASES = (
    "lncel name",
    "nrcel name",
    "wcel name",
    "bts name",
    "bcf name",
    "cell name",
    "cell_name",
)


def _detect_cell_col(conn: sqlite3.Connection, table: str, cols: list[str]) -> str | None:
    low = {c.strip().lower(): c for c in cols}
    for alias in _CELL_ALIASES:
        real = low.get(alias)
        if not real:
            continue
        hit = conn.execute(
            f'''
            SELECT 1 FROM "{table}"
            WHERE "{real}" IS NOT NULL
              AND TRIM(CAST("{real}" AS TEXT)) <> ''
            LIMIT 1
            '''
        ).fetchone()
        if hit:
            return real
    return None


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone()
    return bool(row)


def _chunked(items: list[str], size: int = 400):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def migrate_db(db_path: str, *, dry_run: bool, drop_base: bool) -> dict:
    summary: dict = {"path": db_path, "bases": {}, "skipped": False}
    if not os.path.isfile(db_path):
        summary["skipped"] = True
        summary["reason"] = "missing"
        return summary

    cell_index = build_cell_area_index()
    conn = sqlite3.connect(db_path, timeout=600)
    try:
        conn.execute("PRAGMA busy_timeout=600000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        existing = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        for tech in PM_TECHNOLOGIES:
            base = pm_table_name(tech)
            if not _table_exists(conn, base):
                parts = list_pm_partition_tables(existing, base)
                summary["bases"][base] = {"status": "no_monotable", "partitions": parts}
                continue

            cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{base}")').fetchall()]
            cell_col = _detect_cell_col(conn, base, cols)
            if not cell_col:
                summary["bases"][base] = {"status": "no_cell_col", "columns": cols[:20]}
                continue
            print(f"  cell column: {cell_col!r}")

            total = int(conn.execute(f'SELECT COUNT(*) FROM "{base}"').fetchone()[0])
            if total == 0:
                summary["bases"][base] = {"status": "empty", "rows": 0}
                continue

            print(f"[{os.path.basename(db_path)}] {base}: migrating {total} rows...")
            cells = [
                str(r[0] or "").strip()
                for r in conn.execute(
                    f'''
                    SELECT DISTINCT TRIM(CAST("{cell_col}" AS TEXT))
                    FROM "{base}"
                    WHERE "{cell_col}" IS NOT NULL
                      AND TRIM(CAST("{cell_col}" AS TEXT)) <> ''
                    '''
                ).fetchall()
            ]

            dest_cells: dict[str, list[str]] = defaultdict(list)
            for cell in cells:
                dest = pm_area_table_name(base, resolve_cell_area(cell, cell_index=cell_index))
                dest_cells[dest].append(cell)

            moved = 0
            by_area: dict[str, int] = {}
            col_list = ", ".join(f'"{c}"' for c in cols)

            for dest, cell_list in sorted(dest_cells.items()):
                n_dest = 0
                for batch in _chunked(cell_list, 400):
                    lower_keys = [c.lower() for c in batch]
                    placeholders = ",".join("?" * len(lower_keys))
                    count_sql = (
                        f'SELECT COUNT(*) FROM "{base}" '
                        f'WHERE LOWER(TRIM(CAST("{cell_col}" AS TEXT))) IN ({placeholders})'
                    )
                    n = int(conn.execute(count_sql, lower_keys).fetchone()[0])
                    n_dest += n
                    if dry_run:
                        continue
                    if not _table_exists(conn, dest):
                        try:
                            conn.execute(
                                f'CREATE TABLE IF NOT EXISTS "{dest}" '
                                f'AS SELECT * FROM "{base}" WHERE 0'
                            )
                        except sqlite3.OperationalError:
                            # Concurrent / resume: table may already exist.
                            if not _table_exists(conn, dest):
                                raise
                    conn.execute(
                        f'''
                        INSERT INTO "{dest}" ({col_list})
                        SELECT {col_list} FROM "{base}"
                        WHERE LOWER(TRIM(CAST("{cell_col}" AS TEXT))) IN ({placeholders})
                        ''',
                        lower_keys,
                    )
                    conn.execute(
                        f'''
                        DELETE FROM "{base}"
                        WHERE LOWER(TRIM(CAST("{cell_col}" AS TEXT))) IN ({placeholders})
                        ''',
                        lower_keys,
                    )
                    conn.commit()
                by_area[dest] = n_dest
                moved += n_dest
                print(f"  -> {dest}: {n_dest} rows ({len(cell_list)} cells)")

            if not dry_run:
                for dest in by_area:
                    try:
                        ensure_table_indexes(conn, dest)
                    except Exception as ex:
                        print(f"  index warning {dest}: {ex}")
                if drop_base:
                    left = int(conn.execute(f'SELECT COUNT(*) FROM "{base}"').fetchone()[0])
                    if left == 0:
                        conn.execute(f'DROP TABLE IF EXISTS "{base}"')
                        print(f"  dropped empty monotable {base}")
                    else:
                        print(f"  kept monotable {base} ({left} residual rows)")
                conn.commit()

            summary["bases"][base] = {
                "status": "dry_run" if dry_run else "migrated",
                "rows": moved,
                "partitions": by_area,
            }
            print(
                f"[{os.path.basename(db_path)}] {base}: "
                f"{'would move' if dry_run else 'moved'} {moved} rows -> "
                f"{len(by_area)} partitions"
            )
    finally:
        conn.close()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Count only; no writes")
    parser.add_argument(
        "--drop-base",
        action="store_true",
        help="Drop empty monotables after migrate",
    )
    parser.add_argument(
        "--db",
        action="append",
        dest="dbs",
        help="Specific DB path (repeatable). Default: all Nokia/Huawei hourly+daily cell DBs.",
    )
    args = parser.parse_args()

    dbs = args.dbs or [NOKIA_PM_DB, HUAWEI_PM_DB, NOKIA_PM_DAILY_DB, HUAWEI_PM_DAILY_DB]
    for path in dbs:
        summary = migrate_db(path, dry_run=args.dry_run, drop_base=args.drop_base)
        print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
