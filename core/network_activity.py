"""
Cheap network-activity level from hourly PM traffic (dashboard visuals).

Returns a 0..1 "pulse" level: the latest synced hour's total traffic relative
to the peak hour observed in the recent scan window. Used to pace the
dashboard constellation background — visual only, never for engineering
decisions. Results are cached for 10 minutes per PM database mtime.
"""

from __future__ import annotations

import os
import sqlite3
import time

from sync_config import HUAWEI_PM_DB, NOKIA_PM_DB, pm_table_name

TRAFFIC_ALIASES = [
    "Traffic Volume", "Payload", "Data Volume", "DL Traffic", "UL Traffic",
]

_CACHE_TTL_SECONDS = 600
_cache: dict[str, tuple[float, dict]] = {}

# Scan roughly the last two days of hourly rows (append-only tables).
_SCAN_WINDOW_ROWS = 700_000


def _resolve_columns(conn: sqlite3.Connection, table: str) -> tuple[str, str] | None:
    """Return (timestamp_col, traffic_col) or None."""
    try:
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
    except sqlite3.Error:
        return None
    if not cols:
        return None
    low = {str(c).strip().lower(): c for c in cols}
    ts_col = None
    for cand in ("period_start_time", "date", "timestamp", "time"):
        if cand in low:
            ts_col = low[cand]
            break
    if not ts_col:
        return None

    def _norm(s: str) -> str:
        return "".join(ch for ch in str(s).lower() if ch.isalnum())

    norm_cols = {_norm(c): c for c in cols}
    for alias in TRAFFIC_ALIASES:
        hit = norm_cols.get(_norm(alias))
        if hit:
            return ts_col, hit
    alias_norms = [_norm(a) for a in TRAFFIC_ALIASES]
    for col in cols:
        cn = _norm(col)
        if any(a in cn or cn in a for a in alias_norms):
            return ts_col, col
    return None


def _vendor_activity(db_path: str, table: str) -> dict | None:
    """Per-vendor level: latest-hour traffic sum vs peak hour in the scan window."""
    if not db_path or not os.path.isfile(db_path):
        return None
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        resolved = _resolve_columns(conn, table)
        if not resolved:
            return None
        ts_col, traffic_col = resolved
        row = conn.execute(f'SELECT MAX(rowid) FROM "{table}"').fetchone()
        max_rowid = row[0] if row else None
        if not max_rowid:
            return None
        cutoff = max(1, int(max_rowid) - _SCAN_WINDOW_ROWS)
        value_expr = f"CAST(REPLACE(CAST(\"{traffic_col}\" AS TEXT), ',', '') AS REAL)"
        groups = conn.execute(
            f'''
            SELECT "{ts_col}" AS ts, SUM({value_expr}) AS total, COUNT(*) AS cells,
                   MAX(rowid) AS newest_rowid
            FROM "{table}"
            WHERE rowid >= ? AND "{traffic_col}" IS NOT NULL
            GROUP BY "{ts_col}"
            ''',
            (cutoff,),
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        conn.close()

    parsed = [
        {"ts": str(g[0]), "total": float(g[1] or 0.0), "cells": int(g[2] or 0), "newest_rowid": int(g[3] or 0)}
        for g in groups
        if g[0] is not None
    ]
    if not parsed:
        return None
    # "Latest" = the hour group most recently appended. If it looks partially
    # synced (well below the typical hour's cell count) fall back one group.
    parsed.sort(key=lambda g: g["newest_rowid"], reverse=True)
    typical_cells = max(g["cells"] for g in parsed)
    latest = parsed[0]
    if len(parsed) > 1 and latest["cells"] < typical_cells * 0.5:
        latest = parsed[1]
    peak = max(g["total"] for g in parsed)
    if peak <= 0:
        return None
    return {
        "level": max(0.0, min(1.0, latest["total"] / peak)),
        "latest_hour": latest["ts"],
        "cells_reporting": latest["cells"],
        "kpi": traffic_col,
    }


def get_network_activity(force_refresh: bool = False) -> dict:
    cache_key = "activity"
    now = time.time()
    if not force_refresh:
        item = _cache.get(cache_key)
        if item and item[0] > now:
            return item[1]

    vendors: dict[str, dict] = {}
    table = pm_table_name("4G")  # the dominant traffic layer; cheap single-table scan
    for label, db_path in (("Nokia", NOKIA_PM_DB), ("Huawei", HUAWEI_PM_DB)):
        info = _vendor_activity(db_path, table)
        if info:
            vendors[label] = info

    if vendors:
        level = round(sum(v["level"] for v in vendors.values()) / len(vendors), 3)
    else:
        level = None

    payload = {
        "level": level,
        "vendors": vendors,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
    }
    _cache[cache_key] = (now + _CACHE_TTL_SECONDS, payload)
    return payload
