"""
Build standalone KPI header catalog DB from Nokia/Huawei PM databases.

Output:
  raw/KPIs/kpi_headers.db
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sync_config import NOKIA_PM_DB, HUAWEI_PM_DB, KPI_HEADERS_DB

_FIXED = {"id", "cell_name", "timestamp", "date", "_sync_row_hash"}
_TIME_ALIASES = {"timestamp", "time", "period_start_time", "date"}
_CELL_ALIASES = {
    "cell_name",
    "cell name",
    "bts name",
    "wcel name",
    "lncel name",
    "nrcel name",
}
_NON_KPI_ALIASES = {
    "dn",
    "plmn name",
    "mrbts name",
    "lnbts name",
    "rnc name",
    "wbts name",
    "bsc name",
    "bcf name",
}


def _norm(s: object) -> str:
    return str(s or "").strip()


def _norm_key(s: object) -> str:
    return _norm(s).lower()


def _detect_tech(table_name: str) -> str | None:
    t = _norm(table_name).lower()
    if re.search(r"(^|_)(5g|nr)($|_)", t):
        return "5G"
    if re.search(r"(^|_)(4g|lte|fdd|tdd)($|_)", t):
        return "4G"
    if re.search(r"(^|_)(3g|wcdma|umts)($|_)", t):
        return "3G"
    if re.search(r"(^|_)(2g|gsm)($|_)", t):
        return "2G"
    return None


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]


def _candidate_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def _collect_rows(vendor: str, db_path: str) -> list[tuple[str, str, str, str]]:
    if not os.path.isfile(db_path):
        return []
    conn = sqlite3.connect(db_path, timeout=30)
    out: list[tuple[str, str, str, str]] = []
    try:
        for table in _candidate_tables(conn):
            cols = _table_columns(conn, table)
            low = {_norm_key(c) for c in cols}
            # PM tables can use aliases like Time / PERIOD_START_TIME.
            if not (low & _TIME_ALIASES):
                continue
            tech = _detect_tech(table)
            if not tech:
                continue
            for c in cols:
                key = _norm_key(c)
                if key in _FIXED or key in _TIME_ALIASES or key in _CELL_ALIASES or key in _NON_KPI_ALIASES:
                    continue
                out.append((vendor, tech, table, c))
    finally:
        conn.close()
    return out


def build() -> tuple[int, int]:
    os.makedirs(os.path.dirname(KPI_HEADERS_DB), exist_ok=True)
    conn = sqlite3.connect(KPI_HEADERS_DB, timeout=30)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kpi_headers (
                vendor TEXT NOT NULL,
                technology TEXT NOT NULL,
                table_name TEXT NOT NULL,
                kpi_name TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (vendor, technology, table_name, kpi_name)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kpi_scope (
                vendor TEXT NOT NULL,
                technology TEXT NOT NULL,
                kpi_name TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (vendor, technology, kpi_name)
            )
            """
        )
        conn.execute("DELETE FROM kpi_headers")
        conn.execute("DELETE FROM kpi_scope")

        rows = []
        rows.extend(_collect_rows("Nokia", NOKIA_PM_DB))
        rows.extend(_collect_rows("Huawei", HUAWEI_PM_DB))
        conn.executemany(
            """
            INSERT OR REPLACE INTO kpi_headers (vendor, technology, table_name, kpi_name)
            VALUES (?,?,?,?)
            """,
            rows,
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO kpi_scope (vendor, technology, kpi_name)
            SELECT vendor, technology, kpi_name
            FROM kpi_headers
            GROUP BY vendor, technology, kpi_name
            """
        )
        conn.commit()
        scope_count = int(conn.execute("SELECT COUNT(*) FROM kpi_scope").fetchone()[0])
        return len(rows), scope_count
    finally:
        conn.close()


def main() -> int:
    detailed, scoped = build()
    print(f"[kpi-db] detailed_rows={detailed} scope_rows={scoped} path={KPI_HEADERS_DB}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
