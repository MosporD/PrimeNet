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


def _timestamp_candidates(columns: list[str]) -> list[str]:
    exact: list[str] = []
    partial: list[str] = []
    partial_keywords = ("period_start_time", "period start", "timestamp", "period")
    for col in columns:
        low = col.lower().strip()
        if "latency" in low:
            continue
        if low in _TS_KEYWORDS:
            exact.append(col)
            continue
        if any(kw in low for kw in partial_keywords):
            partial.append(col)
    return exact + [col for col in partial if col not in exact]


def _parse_pm_timestamp(value: Any, label: str, col_name: str) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nat", "nan"}:
        return None

    cleaned = " ".join(text.split())
    if len(cleaned) > 10 and cleaned[10] == "T":
        cleaned = f"{cleaned[:10]} {cleaned[11:]}"
    for suffix in (" DST", " STD"):
        if cleaned.upper().endswith(suffix):
            cleaned = cleaned[: -len(suffix)].strip()
            break

    low_label = label.lower()
    low_col = col_name.lower().strip()
    prefer_dayfirst = "huawei" in low_label or "/" in cleaned
    formats: list[str] = []

    if "huawei" in low_label or low_col in {"time", "date"} or "/" in cleaned:
        formats.extend(
            [
                "%d/%m/%Y %H:%M:%S",
                "%d/%m/%Y %H:%M",
                "%d/%m/%Y",
                "%d/%m/%y %H:%M:%S",
                "%d/%m/%y %H:%M",
                "%d/%m/%y",
            ]
        )
    if "nokia" in low_label or "." in cleaned:
        formats.extend(
            [
                "%m.%d.%Y %H:%M:%S",
                "%m.%d.%Y %H:%M",
                "%m.%d.%Y",
                "%m.%d.%y %H:%M:%S",
                "%m.%d.%y %H:%M",
                "%m.%d.%y",
                "%d.%m.%Y %H:%M:%S",
                "%d.%m.%Y %H:%M",
                "%d.%m.%Y",
                "%d.%m.%y %H:%M:%S",
                "%d.%m.%y %H:%M",
                "%d.%m.%y",
            ]
        )
    formats.extend(
        [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%Y%m%d%H%M%S",
            "%Y%m%d%H%M",
            "%Y%m%d%H",
            "%Y%m%d",
        ]
    )

    seen_formats: set[str] = set()
    for fmt in formats:
        if fmt in seen_formats:
            continue
        seen_formats.add(fmt)
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            pass

    # Ambiguous slash dates in these exports are Huawei-style DD/MM, not US MM/DD.
    if "/" in cleaned and prefer_dayfirst:
        parts = cleaned.split(" ", 1)
        date_parts = parts[0].split("/")
        if len(date_parts) == 3:
            try:
                day, month, year = (int(part) for part in date_parts)
                if year < 100:
                    year += 2000
                time_part = parts[1] if len(parts) > 1 else "00:00:00"
                hour, minute, second = _parse_time_part(time_part)
                return datetime(year, month, day, hour, minute, second)
            except (TypeError, ValueError):
                return None
    return None


def _parse_time_part(value: str) -> tuple[int, int, int]:
    parts = value.split(":")
    hour = int(parts[0]) if len(parts) > 0 and parts[0] else 0
    minute = int(parts[1]) if len(parts) > 1 and parts[1] else 0
    second = int(float(parts[2])) if len(parts) > 2 and parts[2] else 0
    return hour, minute, second


def _timestamp_bounds(
    conn: sqlite3.Connection, table: str, columns: list[str], label: str
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    for col in _timestamp_candidates(columns):
        parsed_count = 0
        earliest_dt: datetime | None = None
        earliest_raw: Any = None
        latest_dt: datetime | None = None
        latest_raw: Any = None
        try:
            values = conn.execute(
                f'SELECT DISTINCT "{col}" FROM "{table}" '
                f'WHERE "{col}" IS NOT NULL AND TRIM(CAST("{col}" AS TEXT)) != ""'
            )
        except Exception:
            continue

        for (raw_value,) in values:
            parsed = _parse_pm_timestamp(raw_value, label, col)
            if parsed is None:
                continue
            parsed_count += 1
            if earliest_dt is None or parsed < earliest_dt:
                earliest_dt = parsed
                earliest_raw = raw_value
            if latest_dt is None or parsed > latest_dt:
                latest_dt = parsed
                latest_raw = raw_value

        if parsed_count == 0 or earliest_dt is None or latest_dt is None:
            continue
        candidate = {
            "column": col,
            "earliest": earliest_raw,
            "latest": latest_raw,
            "earliest_sort": earliest_dt,
            "latest_sort": latest_dt,
            "parsed_distinct_timestamps": parsed_count,
        }
        if best is None or parsed_count > best["parsed_distinct_timestamps"]:
            best = candidate
    return best


def _table_stats(conn: sqlite3.Connection, table: str, label: str) -> dict:
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
    bounds = _timestamp_bounds(conn, table, columns, label)
    if bounds:
        out["timestamp_column"] = bounds["column"]
        out["earliest"] = bounds["earliest"]
        out["latest"] = bounds["latest"]
        out["_earliest_sort"] = bounds["earliest_sort"]
        out["_latest_sort"] = bounds["latest_sort"]
        out["parsed_distinct_timestamps"] = bounds["parsed_distinct_timestamps"]
    elif ts_col:
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
            result["tables"].append(_table_stats(conn, table, label))

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
        latest_sort = None
        latest_table = None
        for ts in result["tables"]:
            latest = ts.get("latest")
            sort_value = ts.get("_latest_sort")
            if latest and sort_value and (latest_sort is None or sort_value > latest_sort):
                latest_overall = latest
                latest_sort = sort_value
                latest_table = ts.get("table")
            elif latest and latest_sort is None and latest_overall is None:
                latest_overall = latest
                latest_table = ts.get("table")
        result["latest_data_overall"] = latest_overall
        result["latest_data_table"] = latest_table
        for table_stats in result["tables"]:
            table_stats.pop("_earliest_sort", None)
            table_stats.pop("_latest_sort", None)

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
