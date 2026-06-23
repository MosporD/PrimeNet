"""
Performance PM database health checks (latest timestamps, row counts, distinct cells).
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any

from sync_config import (
    HUAWEI_GROUPS_DAILY_DB,
    HUAWEI_GROUPS_DB,
    HUAWEI_PM_DAILY_DB,
    HUAWEI_PM_DB,
    METADATA_DB,
    NOKIA_GROUPS_DAILY_DB,
    NOKIA_GROUPS_DB,
    NOKIA_PM_DAILY_DB,
    NOKIA_PM_DB,
)

_CELL_KEYWORDS = [
    "nrcel name", "nrcelname", "nrcel",
    "lncel name", "lncelname", "lncel",
    "wcel name", "wcelname", "wcel",
    "bts name", "btsname",
    "cell name", "cell_name", "cellname",
    "cell_name",
]
_TS_KEYWORDS = ["period_start_time", "period start", "timestamp", "date", "time"]

_CACHE_TTL_SEC = 600
_cache_lock = threading.Lock()
_cache: dict[str, Any] = {"expires_at": 0.0, "payload": None}

PM_CELL_DBS = [
    ("Nokia PM hourly", NOKIA_PM_DB),
    ("Huawei PM hourly", HUAWEI_PM_DB),
    ("Nokia PM daily", NOKIA_PM_DAILY_DB),
    ("Huawei PM daily", HUAWEI_PM_DAILY_DB),
]
PM_GROUP_DBS = [
    ("Nokia groups hourly", NOKIA_GROUPS_DB),
    ("Huawei groups hourly", HUAWEI_GROUPS_DB),
    ("Nokia groups daily", NOKIA_GROUPS_DAILY_DB),
    ("Huawei groups daily", HUAWEI_GROUPS_DAILY_DB),
]

# Empty tables that do not indicate a broken PM pipeline.
_OPTIONAL_EMPTY_GLOBAL = frozenset({"group_cells", "groups"})
_OPTIONAL_EMPTY_HUAWEI = frozenset(
    {
        "5G_CELLS_HOURLY",
        "5G_CELLS_DAILY",
        "5G_GROUPS_HOURLY",
        "5G_GROUPS_DAILY",
    }
)


def _optional_empty_tables(label: str) -> frozenset[str]:
    opt = set(_OPTIONAL_EMPTY_GLOBAL)
    if "huawei" in str(label).lower():
        opt |= _OPTIONAL_EMPTY_HUAWEI
    return frozenset(opt)


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


def _column_names(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]


def _detect_cell_col(columns: list[str]) -> str | None:
    lowered = {c: c.lower() for c in columns}
    for kw in _CELL_KEYWORDS:
        for col, low in lowered.items():
            if kw == low or kw in low:
                if "id" in low and "name" not in low:
                    continue
                return col
    if "cell_name" in lowered:
        return next(c for c in columns if c.lower() == "cell_name")
    return None


def _detect_ts_col(columns: list[str]) -> str | None:
    lowered = {c: c.lower() for c in columns}
    for kw in _TS_KEYWORDS:
        for col, low in lowered.items():
            if kw == low:
                return col
    for kw in _TS_KEYWORDS:
        for col, low in lowered.items():
            if kw in low and "latency" not in low:
                return col
    return None


def _table_stats(conn: sqlite3.Connection, table: str) -> dict:
    columns = _column_names(conn, table)
    cell_col = _detect_cell_col(columns)
    ts_col = _detect_ts_col(columns)
    out: dict = {"table": table, "rows": 0, "cell_column": cell_col, "timestamp_column": ts_col}
    try:
        out["rows"] = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    except Exception as exc:
        out["error"] = str(exc)
        out["status"] = "ERROR"
        return out
    if out["rows"] == 0:
        out["status"] = "EMPTY"
        return out
    if cell_col:
        out["distinct_cells"] = int(
            conn.execute(
                f'SELECT COUNT(DISTINCT "{cell_col}") FROM "{table}" WHERE "{cell_col}" IS NOT NULL'
            ).fetchone()[0]
        )
    if ts_col:
        row = conn.execute(
            f'SELECT MIN("{ts_col}"), MAX("{ts_col}") FROM "{table}" WHERE "{ts_col}" IS NOT NULL'
        ).fetchone()
        out["earliest"] = row[0]
        out["latest"] = row[1]
    out["status"] = "OK"
    return out


def audit_db(path: str, label: str, *, cell_scope: bool = True) -> dict:
    result: dict = {"label": label, "file": _file_health(path), "tables": []}
    if not result["file"].get("exists"):
        result["overall"] = "MISSING"
        return result

    conn = sqlite3.connect(path, timeout=120)
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

        if cell_scope:
            unions: list[str] = []
            for table in tables:
                cell_col = _detect_cell_col(_column_names(conn, table))
                if cell_col:
                    unions.append(f'SELECT "{cell_col}" AS cell_name FROM "{table}"')
            if unions:
                sql = (
                    f"SELECT COUNT(DISTINCT cell_name) FROM ({' UNION '.join(unions)}) "
                    "WHERE cell_name IS NOT NULL AND TRIM(cell_name) != ''"
                )
                result["distinct_cells_db"] = int(conn.execute(sql).fetchone()[0])

        latest_overall = None
        latest_table = None
        for ts in result["tables"]:
            latest = ts.get("latest")
            if latest and (latest_overall is None or str(latest) > str(latest_overall)):
                latest_overall = latest
                latest_table = ts.get("table")
        result["latest_data_overall"] = latest_overall
        result["latest_data_table"] = latest_table

        empty = [t["table"] for t in result["tables"] if t.get("status") == "EMPTY"]
        pm_tables = [t for t in tables if "GROUP" in t.upper() or "CELL" in t.upper()]
        optional = _optional_empty_tables(label)
        empty_pm = [
            t
            for t in empty
            if (t in pm_tables or t.endswith("_HOURLY") or t.endswith("_DAILY"))
            and t not in optional
        ]
        result["overall"] = "DEGRADED" if empty_pm else "HEALTHY"
        if optional:
            empty_optional = [t for t in empty if t in optional]
            if empty_optional:
                result["empty_optional_tables"] = empty_optional
        if empty:
            result["empty_tables"] = empty
    finally:
        conn.close()
    return result


def metadata_distinct_cells() -> dict | None:
    if not os.path.isfile(METADATA_DB):
        return None
    conn = sqlite3.connect(METADATA_DB, timeout=60)
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'cells_%'"
            ).fetchall()
        ]
        unions = [f'SELECT cell_name FROM "{t}"' for t in tables]
        if not unions:
            return None
        n = int(
            conn.execute(
                f"SELECT COUNT(DISTINCT cell_name) FROM ({' UNION '.join(unions)})"
            ).fetchone()[0]
        )
        return {"distinct_cells": n, "cell_tables": tables}
    finally:
        conn.close()


def pm_union_distinct_cells(pm_paths: list[str]) -> int:
    all_cells: set[str] = set()
    for path in pm_paths:
        if not os.path.isfile(path):
            continue
        conn = sqlite3.connect(path, timeout=120)
        try:
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]
            for table in tables:
                cell_col = _detect_cell_col(_column_names(conn, table))
                if not cell_col:
                    continue
                for (cell_name,) in conn.execute(
                    f'SELECT DISTINCT "{cell_col}" FROM "{table}" '
                    f'WHERE "{cell_col}" IS NOT NULL'
                ):
                    if cell_name and str(cell_name).strip():
                        all_cells.add(str(cell_name).strip())
        finally:
            conn.close()
    return len(all_cells)


def run_pm_health_check(
    *,
    include_groups: bool = True,
    include_global_distinct: bool = True,
) -> dict:
    """Run a full PM health survey."""
    cell_reports = [audit_db(path, label) for label, path in PM_CELL_DBS]
    group_reports = [audit_db(path, label) for label, path in PM_GROUP_DBS] if include_groups else []

    payload: dict[str, Any] = {
        "checked_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "pm_cell_databases": cell_reports,
        "pm_group_databases": group_reports,
        "metadata_cells": metadata_distinct_cells(),
    }
    if include_global_distinct:
        payload["distinct_cells_all_pm_cell_dbs_union"] = pm_union_distinct_cells(
            [p for _, p in PM_CELL_DBS]
        )
    return payload


def get_pm_health_cached(*, force_refresh: bool = False, **kwargs) -> dict:
    """Return cached health payload (refreshes every ``_CACHE_TTL_SEC`` or when forced)."""
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

    payload = run_pm_health_check(**kwargs)
    payload["cached"] = False
    with _cache_lock:
        _cache["payload"] = payload
        _cache["expires_at"] = now + _CACHE_TTL_SEC
    return payload
