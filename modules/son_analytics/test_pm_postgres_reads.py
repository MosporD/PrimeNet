"""PM reads must work on the Postgres runtime (no rowid, dict rows, text vendor dates)."""

from __future__ import annotations

import sqlite3

from db.runtime import PgConn, PgRow
from modules.performance.routes import _row_values
from modules.son_analytics import pm_helpers as ph


class _FakeRaw:
    def __init__(self):
        self.sql: list[str] = []

    def execute(self, sql, params=()):
        self.sql.append(sql)
        raise AssertionError("rowid probe must not run on Postgres")


def test_rowid_probe_skipped_on_postgres():
    raw = _FakeRaw()
    assert ph._rowid_scan_cutoff(PgConn(raw), "4G_CELLS_DAILY", 7) is None
    assert raw.sql == []


def test_row_values_reads_values_from_pg_rows():
    assert _row_values(PgRow({"n0": 5, "n1": 0})) == [5, 0]
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    assert _row_values(conn.execute("SELECT 1 AS a, NULL AS b").fetchone()) == [1, None]


def test_loader_iso_columns_win_over_raw_vendor_dates():
    cols = ["Date", "Cell Name", "timestamp", "report_date"]
    assert ph._find_col(cols, ph._TS_COL_CANDIDATES) == "timestamp"
    cols = ["Period start time", "LNCEL name", "report_date"]
    assert ph._find_col(cols, ph._TS_COL_CANDIDATES) == "report_date"


def test_day_cutoff_only_on_loader_iso_columns():
    conn = sqlite3.connect(":memory:")
    conn.execute('CREATE TABLE t ("Date" TEXT, "Cell Name" TEXT, kpi REAL, "timestamp" TEXT)')
    rows = [
        ("30/09/2026", "C1", 5.0, "2026-09-30 00:00:00"),
        ("06/10/2026", "C1", 0.0, "2026-10-06 00:00:00"),
        ("01/09/2026", "C1", 9.0, "2026-09-01 00:00:00"),
    ]
    conn.executemany("INSERT INTO t VALUES (?, ?, ?, ?)", rows)
    assert ph._recent_day_cutoff(conn, "t", "timestamp", 7) == "2026-09-29"
    assert ph._recent_day_cutoff(conn, "t", "Date", 7) is None
