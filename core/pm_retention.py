"""
Delete PM/group rows older than N calendar days from SQLite KPI databases.

Uses the same timestamp column detection and vendor-specific parsing as the raw loader.
"""

from __future__ import annotations

import os
import sqlite3

import pandas as pd

from modules.sync.pm_processor import _pick_best_timestamp_column


def _retention_parse_label(db_path: str, label: str) -> str:
    low = db_path.replace("\\", "/").lower()
    if "huawei" in low:
        return "huawei-groups" if "groups" in low else "huawei-cells"
    if "nokia" in low:
        return "nokia-groups" if "groups" in low else "nokia-cells"
    return label


def _pragma_column_names(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]


def _match_column_name(data_cols: list[str], detected: str | None) -> str | None:
    if not detected:
        return None
    if detected in data_cols:
        return detected
    dl = str(detected).lower().strip()
    for c in data_cols:
        if str(c).lower().strip() == dl:
            return c
    return None


def _parse_ts_series(series: pd.Series, label: str, col: str) -> pd.Series:
    """Vendor-aware parse (lazy import from loader)."""
    from scripts.pipeline.load_raw_csv_to_databases import _parse_timestamp_series

    return _parse_timestamp_series(series, label, col)


def apply_retention(db_path: str, days: int, label: str) -> int:
    """
    Delete rows with timestamp strictly before ``now - days``.
    Returns approximate number of rows deleted.
    """
    if days <= 0 or not os.path.isfile(db_path):
        return 0

    parse_label = _retention_parse_label(db_path, label)
    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=int(days))
    deleted_total = 0

    conn = sqlite3.connect(db_path, timeout=120)
    try:
        conn.execute("PRAGMA busy_timeout=120000")
    except sqlite3.Error:
        pass
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for (table,) in tables:
            if table in ("groups", "group_cells"):
                continue
            try:
                cols = _pragma_column_names(conn, table)
                ts_col = _pick_best_timestamp_column(pd.DataFrame(columns=cols), cols)
                ts_col = _match_column_name(cols, ts_col)
                if not ts_col:
                    print(f"[{label}] retention {table}: no timestamp column — skipped")
                    continue

                row_count = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] or 0)
                if row_count == 0:
                    continue

                doomed: list[int] = []
                parsed_total = 0
                for chunk in pd.read_sql_query(
                    f'SELECT rowid AS _rid, "{ts_col}" AS _ts FROM "{table}"',
                    conn,
                    chunksize=50000,
                ):
                    if chunk.empty:
                        continue
                    ts = _parse_ts_series(chunk["_ts"], parse_label, ts_col)
                    valid = ts.notna()
                    parsed_total += int(valid.sum())
                    mask = valid & (ts < cutoff)
                    if mask.any():
                        doomed.extend(chunk.loc[mask, "_rid"].astype(int).tolist())

                if not doomed:
                    print(f"[{label}] retention {table}: kept all rows (cutoff {cutoff.date()})")
                    continue

                if parsed_total < max(10, int(row_count * 0.05)):
                    print(
                        f"[{label}] retention {table}: skipped — only {parsed_total}/{row_count} "
                        f"timestamps parsed (avoid mass delete)"
                    )
                    continue

                if len(doomed) > int(row_count * 0.85):
                    print(
                        f"[{label}] retention {table}: skipped — would delete {len(doomed)}/{row_count} "
                        f"rows (likely timestamp parse issue; cutoff {cutoff.date()})"
                    )
                    continue

                batch = 1000
                for i in range(0, len(doomed), batch):
                    part = doomed[i : i + batch]
                    ph = ",".join("?" for _ in part)
                    conn.execute(f'DELETE FROM "{table}" WHERE rowid IN ({ph})', part)
                deleted_total += len(doomed)
                print(
                    f"[{label}] retention {table}: deleted {len(doomed)} rows older than {cutoff.date()} "
                    f"(kept ~{row_count - len(doomed)})"
                )
            except Exception as ex:
                print(f"[{label}] retention skipped on {table}: {ex}")
        conn.commit()
    finally:
        conn.close()

    return deleted_total
