"""
Neighbor DB maintenance.

Legacy normalized tables are removed by ``scripts/load_nokia_neighbor_raw_to_db.py``
when loading raw per-RAT exports. ``ensure_neighbor_schema`` is a no-op so older
callers (e.g. load_neighbor_reports) do not wipe tables on connect.

Run ``python scripts/build_neighbor_kpi_db.py`` to apply optional one-time cleanup.
"""

from __future__ import annotations

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sync_config import NEIGHBOR_KPI_DB


def _drop_legacy_neighbor_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP INDEX IF EXISTS idx_neighbor_hourly_scope;
        DROP INDEX IF EXISTS idx_neighbor_hourly_source_time;
        DROP INDEX IF EXISTS idx_neighbor_hourly_target_time;
        DROP INDEX IF EXISTS idx_neighbor_hourly_attempts;
        DROP TABLE IF EXISTS neighbor_hourly;
        DROP TABLE IF EXISTS neighbor_cell_index;
        """
    )


def ensure_neighbor_schema(conn: sqlite3.Connection) -> None:
    """No-op: raw neighbor data uses nokia_neighbor_* tables."""
    return


def build() -> str:
    os.makedirs(os.path.dirname(NEIGHBOR_KPI_DB), exist_ok=True)
    conn = sqlite3.connect(NEIGHBOR_KPI_DB, timeout=30)
    try:
        _drop_legacy_neighbor_tables(conn)
        conn.commit()
    finally:
        conn.close()
    return NEIGHBOR_KPI_DB


def main() -> int:
    path = build()
    print(f"[neighbor-db] optional legacy cleanup applied: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
