"""Neighbor database health checks for the dashboard operations panel."""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any

from sync_config import HUAWEI_NEIGHBOR_RAW_DB, NEIGHBOR_KPI_DB

_CACHE_TTL_SEC = 600
_cache_lock = threading.Lock()
_cache: dict[str, Any] = {"expires_at": 0.0, "payload": None}

_TS_SAMPLE_ROWS = 50_000

NEIGHBOR_DBS = [
    ("Nokia neighbor hourly", NEIGHBOR_KPI_DB),
    ("Huawei neighbor hourly", HUAWEI_NEIGHBOR_RAW_DB),
]

_TS_KEYWORDS = (
    "period_start_time",
    "period start",
    "start time",
    "timestamp",
    "datetime",
    "date",
    "time",
    "period",
)


def _file_health(path: str) -> dict:
    if not os.path.isfile(path):
        return {"exists": False, "path": path}
    st = os.stat(path)
    return {
        "exists": True,
        "path": path,
        "size_mb": round(st.st_size / (1024 * 1024), 2),
        "modified_utc": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
    }


def _sqlite_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _column_names(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({_sqlite_ident(table)})").fetchall()]


def _detect_ts_col(columns: list[str]) -> str | None:
    lowered = {c: c.lower().strip() for c in columns}
    for keyword in _TS_KEYWORDS:
        for col, low in lowered.items():
            if low == keyword:
                return col
    for keyword in _TS_KEYWORDS:
        for col, low in lowered.items():
            if keyword in low and "latency" not in low:
                return col
    return None


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text or text.lower() in {"none", "null", "nan", "nat"}:
        return None
    text = " ".join(text.split())
    for suffix in (" DST", " STD"):
        if text.upper().endswith(suffix):
            text = text[: -len(suffix)].strip()
            break
    formats = (
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%m.%d.%Y %H:%M:%S",
        "%m.%d.%Y %H:%M",
        "%m.%d.%Y",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _latest_timestamp(conn: sqlite3.Connection, table: str, ts_col: str) -> str | None:
    try:
        max_rowid = conn.execute(
            f"SELECT MAX(rowid) FROM {_sqlite_ident(table)}"
        ).fetchone()[0]
    except sqlite3.Error:
        max_rowid = None
    cutoff = max(1, int(max_rowid) - _TS_SAMPLE_ROWS) if max_rowid else None
    sql = f"""
        SELECT DISTINCT {_sqlite_ident(ts_col)}
        FROM {_sqlite_ident(table)}
        WHERE {_sqlite_ident(ts_col)} IS NOT NULL
          AND TRIM(CAST({_sqlite_ident(ts_col)} AS TEXT)) <> ''
    """
    params: tuple = ()
    if cutoff is not None:
        sql += " AND rowid >= ?"
        params = (cutoff,)
    best: datetime | None = None
    try:
        rows = conn.execute(sql, params)
    except sqlite3.Error:
        return None
    for (raw,) in rows:
        parsed = _parse_timestamp(raw)
        if parsed is not None and (best is None or parsed > best):
            best = parsed
    return best.strftime("%Y-%m-%d %H:%M:%S") if best else None


def _table_stats(conn: sqlite3.Connection, table: str) -> dict:
    rows = int(conn.execute(f"SELECT COUNT(*) FROM {_sqlite_ident(table)}").fetchone()[0] or 0)
    columns = _column_names(conn, table)
    ts_col = _detect_ts_col(columns)
    latest = None
    if ts_col and rows:
        latest = _latest_timestamp(conn, table, ts_col)
    return {
        "table": table,
        "status": "EMPTY" if rows == 0 else "OK",
        "rows": rows,
        "columns": len(columns),
        "timestamp_column": ts_col,
        "latest": latest,
    }


def audit_neighbor_db(path: str, label: str) -> dict:
    result: dict = {"label": label, "file": _file_health(path), "tables": []}
    if not result["file"].get("exists"):
        result["overall"] = "MISSING"
        return result

    conn = sqlite3.connect(path, timeout=60)
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        for table in tables:
            result["tables"].append(_table_stats(conn, table))
    finally:
        conn.close()

    total_rows = sum(int(t.get("rows") or 0) for t in result["tables"])
    latest_table = None
    latest_value = None
    for table in result["tables"]:
        latest = table.get("latest")
        if latest and (latest_value is None or str(latest) > str(latest_value)):
            latest_value = latest
            latest_table = table.get("table")

    result["total_rows"] = total_rows
    result["latest_data_overall"] = latest_value
    result["latest_data_table"] = latest_table
    empty_tables = [t["table"] for t in result["tables"] if t.get("status") == "EMPTY"]
    if empty_tables:
        result["empty_tables"] = empty_tables
    if not result["tables"] or total_rows == 0:
        result["overall"] = "DEGRADED"
    elif empty_tables:
        result["overall"] = "DEGRADED"
    else:
        result["overall"] = "HEALTHY"
    return result


def run_neighbor_health_check() -> dict:
    return {
        "checked_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "neighbor_databases": [
            audit_neighbor_db(path, label)
            for label, path in NEIGHBOR_DBS
        ],
    }


def get_neighbor_health_cached(*, force_refresh: bool = False) -> dict:
    now = time.time()
    with _cache_lock:
        if (
            not force_refresh
            and _cache.get("payload")
            and now < float(_cache.get("expires_at") or 0)
        ):
            out = dict(_cache["payload"])
            out["cached"] = True
            return out

    payload = run_neighbor_health_check()
    payload["cached"] = False
    with _cache_lock:
        _cache["payload"] = payload
        _cache["expires_at"] = now + _CACHE_TTL_SEC
    return payload
