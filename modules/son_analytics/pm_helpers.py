"""Read-only PM helpers for SON / Health (daily performance data)."""

from __future__ import annotations

import os
import re
import sqlite3
import time

from sync_config import (
    HUAWEI_PM_DAILY_DB,
    HUAWEI_PM_DB,
    NOKIA_PM_DAILY_DB,
    NOKIA_PM_DB,
    pm_table_name,
)

PM_DATA_SCOPE = "daily"

_CELL_COL_CANDIDATES = [
    "LNCEL name",
    "NRCEL name",
    "WCEL name",
    "BTS name",
    "cell_name",
    "LocalCell Id",
    "Cell CI",
    "Cell Name",
]
_TS_COL_CANDIDATES = [
    "PERIOD_START_TIME",
    "Date",
    "date",
    "timestamp",
    "Timestamp",
    "period_start_time",
]

_SERIES_CACHE: dict[str, tuple[float, float, dict]] = {}
_BENCHMARK_CACHE: dict[str, tuple[float, float, list]] = {}
_ALL_BENCHMARK_CACHE: dict[str, tuple[float, float, dict[str, list]]] = {}
_PM_CACHE_TTL_SECONDS = 3600


def _pm_db_mtime(db_path: str) -> float:
    try:
        return os.path.getmtime(db_path)
    except OSError:
        return 0.0


def _cache_get(store: dict, key: str, db_path: str):
    item = store.get(key)
    if not item:
        return None
    expires_at, cached_mtime, payload = item
    if time.time() > expires_at or cached_mtime != _pm_db_mtime(db_path):
        store.pop(key, None)
        return None
    return payload


def _cache_set(store: dict, key: str, db_path: str, payload) -> None:
    store[key] = (time.time() + _PM_CACHE_TTL_SECONDS, _pm_db_mtime(db_path), payload)


def _rowid_scan_cutoff(conn: sqlite3.Connection, table_name: str, lookback_days: int) -> int | None:
    """Limit PM scans to recent rows (append-only DBs). Returns None to scan all rows."""
    try:
        row = conn.execute(f'SELECT MAX(rowid) FROM "{table_name}"').fetchone()
    except sqlite3.Error:
        return None
    max_rowid = row[0] if row else None
    if not max_rowid:
        return None
    hourly = table_name.upper().endswith("_HOURLY")
    per_day = 350_000 if hourly else 35_000
    floor = 1_500_000 if hourly else 250_000
    window = min(int(max_rowid), max(floor, (lookback_days + 5) * per_day))
    return max(1, int(max_rowid) - window)


def _resolve_pm_table_axes(
    conn: sqlite3.Connection,
    table_name: str,
    kpi_column: str,
) -> tuple[str, str, str] | None:
    cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()]
    if not cols or kpi_column not in cols:
        return None
    cell_col = _find_col(cols, _CELL_COL_CANDIDATES + ["DN", "dn"])
    ts_col = _find_col(cols, _TS_COL_CANDIDATES + ["Date", "date", "Time", "time"])
    if not cell_col or not ts_col:
        return None
    return cell_col, ts_col, kpi_column


def _dedupe_daily_series_rows(
    rows,
    *,
    lookback_days: int,
) -> list[tuple[str, float]]:
    """Rows with ts_raw + kpi_value, newest first per day."""
    seen: set[str] = set()
    out: list[tuple[str, float]] = []
    max_points = lookback_days + 1
    for row in rows:
        day = parse_pm_timestamp(row["ts_raw"] if hasattr(row, "keys") else row[0])
        val = _to_float(row["kpi_value"] if hasattr(row, "keys") else row[1])
        if not day or val is None or day in seen:
            continue
        seen.add(day)
        out.append((day, val))
        if len(out) >= max_points:
            break
    return out


def _normalize_scope(scope: str | None) -> str:
    v = (scope or PM_DATA_SCOPE).strip().lower()
    if v in ("daily", "day", "d"):
        return "daily"
    return "hourly"


def pm_table_name_for_scope(technology: str, scope: str | None = None) -> str:
    table = pm_table_name(technology)
    if _normalize_scope(scope) == "daily":
        return table.replace("_HOURLY", "_DAILY")
    return table


def _pm_db_paths(vendor: str, scope: str) -> tuple[str | None, str | None]:
    """Return (primary_db, hourly_fallback_db) for vendor."""
    v = (vendor or "all").strip().lower()
    is_daily = _normalize_scope(scope) == "daily"
    nokia_primary = NOKIA_PM_DAILY_DB if is_daily else NOKIA_PM_DB
    huawei_primary = HUAWEI_PM_DAILY_DB if is_daily else HUAWEI_PM_DB
    nokia_fb = NOKIA_PM_DB if is_daily else None
    huawei_fb = HUAWEI_PM_DB if is_daily else None

    if v == "nokia":
        return (
            nokia_primary if os.path.isfile(nokia_primary) else None,
            nokia_fb if nokia_fb and os.path.isfile(nokia_fb) else None,
        )
    if v == "huawei":
        return (
            huawei_primary if os.path.isfile(huawei_primary) else None,
            huawei_fb if huawei_fb and os.path.isfile(huawei_fb) else None,
        )
    # all vendors — caller iterates both
    return None, None


def _to_float(raw) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    s = str(raw).strip()
    if not s:
        return None
    s = s.replace(",", "")
    s = re.sub(r"(?i)\s*(m|meter|meters|%)\s*$", "", s).strip()
    m = re.search(r"[-+]?\d*\.?\d+", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except (TypeError, ValueError):
        return None


def _find_col(cols: list[str], candidates: list[str]) -> str | None:
    cols_lower = {c.strip().lower(): c for c in cols}
    for cand in candidates:
        matched = cols_lower.get(cand.strip().lower())
        if matched:
            return matched
    return None


def _table_has_rows(conn: sqlite3.Connection, table_name: str) -> bool:
    try:
        row = conn.execute(f'SELECT 1 FROM "{table_name}" LIMIT 1').fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def resolve_kpi_column(pm_db_path: str, table_name: str, aliases: list[str]) -> str | None:
    if not pm_db_path or not os.path.isfile(pm_db_path):
        return None
    conn = sqlite3.connect(pm_db_path, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()]
        if not cols:
            return None
        lower_map = {str(c).strip().lower(): c for c in cols}
        for alias in aliases:
            c = lower_map.get(str(alias).strip().lower())
            if c:
                return c

        def _norm(s: str) -> str:
            return "".join(ch for ch in str(s).lower() if ch.isalnum())

        norm_cols = {_norm(c): c for c in cols}
        for alias in aliases:
            c = norm_cols.get(_norm(alias))
            if c:
                return c
        alias_lows = [str(a).strip().lower() for a in aliases]
        for col in cols:
            cl = str(col).strip().lower()
            if any((a and (a in cl or cl in a)) for a in alias_lows):
                return col
        return None
    finally:
        conn.close()


def latest_kpi_values(
    pm_db_path: str,
    table_name: str,
    kpi_column: str,
    *,
    limit: int = 8000,
) -> dict[str, float]:
    if not pm_db_path or not os.path.isfile(pm_db_path):
        return {}
    out: dict[str, float] = {}
    conn = sqlite3.connect(pm_db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()]
        if not cols or kpi_column not in cols:
            return out
        cell_col = _find_col(cols, _CELL_COL_CANDIDATES)
        ts_col = _find_col(cols, _TS_COL_CANDIDATES)
        if not cell_col or not ts_col:
            return out
        sql = f"""
            SELECT t."{cell_col}" AS cell_name, t."{kpi_column}" AS kpi_value
            FROM "{table_name}" t
            JOIN (
                SELECT "{cell_col}", MAX("{ts_col}") AS max_ts
                FROM "{table_name}"
                WHERE "{kpi_column}" IS NOT NULL
                GROUP BY "{cell_col}"
            ) m ON m."{cell_col}" = t."{cell_col}" AND m.max_ts = t."{ts_col}"
            LIMIT ?
        """
        for row in conn.execute(sql, (max(1, limit),)):
            v = _to_float(row["kpi_value"])
            if v is not None:
                out[str(row["cell_name"])] = v
    except sqlite3.Error:
        return out
    finally:
        conn.close()
    return out


def _resolve_pm_source(
    vendor_label: str,
    db_primary: str,
    db_fallback: str | None,
    technology: str,
    scope: str,
) -> tuple[str, str] | None:
    """Pick db + table; fall back to hourly if daily table empty."""
    table_daily = pm_table_name_for_scope(technology, scope)
    table_hourly = pm_table_name(technology)

    if os.path.isfile(db_primary):
        conn = sqlite3.connect(db_primary, timeout=30)
        try:
            if _table_has_rows(conn, table_daily):
                return db_primary, table_daily
        finally:
            conn.close()

    if db_fallback and os.path.isfile(db_fallback):
        conn = sqlite3.connect(db_fallback, timeout=30)
        try:
            if _table_has_rows(conn, table_hourly):
                return db_fallback, table_hourly
        finally:
            conn.close()

    if os.path.isfile(db_primary):
        return db_primary, table_daily
    return None


def vendor_pm_sources(
    vendor: str = "all",
    technology: str = "4G",
    scope: str | None = None,
) -> list[tuple[str, str, str]]:
    """Return list of (vendor_label, db_path, table_name) for PM scope."""
    sc = _normalize_scope(scope)
    v = (vendor or "all").strip().lower()
    sources: list[tuple[str, str, str]] = []

    def _add(vlabel: str, primary: str, fallback: str | None) -> None:
        resolved = _resolve_pm_source(vlabel, primary, fallback, technology, sc)
        if resolved:
            sources.append((vlabel, resolved[0], resolved[1]))

    if v in ("all", "nokia"):
        primary = NOKIA_PM_DAILY_DB if sc == "daily" else NOKIA_PM_DB
        fallback = NOKIA_PM_DB if sc == "daily" else None
        _add("Nokia", primary, fallback)

    if v in ("all", "huawei"):
        primary = HUAWEI_PM_DAILY_DB if sc == "daily" else HUAWEI_PM_DB
        fallback = HUAWEI_PM_DB if sc == "daily" else None
        _add("Huawei", primary, fallback)

    return sources


def collect_kpi_by_vendor(
    aliases: list[str],
    vendor: str = "all",
    technology: str = "4G",
    scope: str | None = None,
) -> list[tuple[str, str, dict[str, float]]]:
    """Return [(vendor, kpi_column, cell_values), ...] from daily PM."""
    out: list[tuple[str, str, dict[str, float]]] = []
    for vlabel, db_path, table in vendor_pm_sources(vendor, technology, scope):
        col = resolve_kpi_column(db_path, table, aliases)
        if not col:
            continue
        vals = latest_kpi_values(db_path, table, col)
        if vals:
            out.append((vlabel, col, vals))
    return out


def parse_pm_timestamp(raw) -> str | None:
    """Normalize PM timestamps to YYYY-MM-DD for grouping."""
    if raw is None:
        return None
    from datetime import datetime

    text = str(raw).strip()
    if not text or text.lower() in {"nil", "nan", "-", "none"}:
        return None
    if text.lower().startswith("total"):
        return None
    # Huawei PM uses DD/MM/YYYY; try day-first before US month-first.
    for fmt in ("%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%m/%d/%Y", "%m.%d.%Y"):
        try:
            return datetime.strptime(text[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _cell_daily_kpi_series(
    pm_db_path: str,
    table_name: str,
    kpi_column: str,
    *,
    lookback_days: int = 7,
) -> dict[str, list[tuple[str, float]]]:
    """Return cell -> [(date_iso, value), ...] newest first, up to lookback_days+1 points."""
    if not pm_db_path or not os.path.isfile(pm_db_path):
        return {}

    cache_key = f"series|{pm_db_path}|{table_name}|{kpi_column}|{lookback_days}"
    cached = _cache_get(_SERIES_CACHE, cache_key, pm_db_path)
    if cached is not None:
        return cached

    out: dict[str, list[tuple[str, float]]] = {}
    conn = sqlite3.connect(pm_db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        axes = _resolve_pm_table_axes(conn, table_name, kpi_column)
        if not axes:
            return out
        cell_col, ts_col, kpi_col = axes
        rowid_cutoff = _rowid_scan_cutoff(conn, table_name, lookback_days)
        where_parts = [f'"{kpi_col}" IS NOT NULL']
        params: list[object] = []
        if rowid_cutoff is not None:
            where_parts.append("rowid >= ?")
            params.append(rowid_cutoff)
        sql = f"""
            SELECT "{cell_col}" AS cell_name, "{ts_col}" AS ts_raw, "{kpi_col}" AS kpi_value
            FROM "{table_name}"
            WHERE {' AND '.join(where_parts)}
            ORDER BY "{cell_col}", "{ts_col}" DESC
        """
        seen: dict[str, set[str]] = {}
        max_points = lookback_days + 1
        for row in conn.execute(sql, params):
            cell = str(row["cell_name"] or "").strip()
            day = parse_pm_timestamp(row["ts_raw"])
            val = _to_float(row["kpi_value"])
            if not cell or not day or val is None:
                continue
            bucket = seen.setdefault(cell, set())
            if day in bucket:
                continue
            bucket.add(day)
            out.setdefault(cell, []).append((day, val))
    except sqlite3.Error:
        return out
    finally:
        conn.close()

    _cache_set(_SERIES_CACHE, cache_key, pm_db_path, out)
    return out


def _single_cell_daily_kpi_series(
    pm_db_path: str,
    table_name: str,
    cell_name: str,
    kpi_column: str,
    *,
    lookback_days: int = 21,
) -> list[tuple[str, float]]:
    """Daily KPI points for one cell, newest first."""
    if not pm_db_path or not os.path.isfile(pm_db_path) or not cell_name:
        return []

    resolved_kpi = _resolve_kpi_column_in_table(pm_db_path, table_name, kpi_column)
    if not resolved_kpi:
        return []

    cache_key = f"cell|{pm_db_path}|{table_name}|{cell_name}|{resolved_kpi}|{lookback_days}"
    cached = _cache_get(_SERIES_CACHE, cache_key, pm_db_path)
    if cached is not None:
        return cached

    fetch_limit = max(30, (lookback_days + 1) * 4)

    def _query(exact: bool) -> list[tuple[str, float]]:
        conn = sqlite3.connect(pm_db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            axes = _resolve_pm_table_axes(conn, table_name, resolved_kpi)
            if not axes:
                return []
            cell_col, ts_col, kpi_col = axes
            if exact:
                where = f'LOWER(TRIM(CAST("{cell_col}" AS TEXT))) = LOWER(TRIM(?))'
                param = cell_name
            else:
                where = f'LOWER(TRIM(CAST("{cell_col}" AS TEXT))) LIKE LOWER(TRIM(?))'
                param = f"%{cell_name}%"
            sql = f"""
                SELECT "{ts_col}" AS ts_raw, "{kpi_col}" AS kpi_value
                FROM "{table_name}"
                WHERE {where}
                  AND "{kpi_col}" IS NOT NULL
                ORDER BY "{ts_col}" DESC
                LIMIT ?
            """
            rows = conn.execute(sql, (param, fetch_limit)).fetchall()
            return _dedupe_daily_series_rows(rows, lookback_days=lookback_days)
        except sqlite3.Error:
            return []
        finally:
            conn.close()

    series = _query(exact=True)
    if not series:
        series = _query(exact=False)
    _cache_set(_SERIES_CACHE, cache_key, pm_db_path, series)
    return series


def _benchmark_from_series(
    series: list[tuple[str, float]],
    *,
    direction: str,
    min_history_days: int = 3,
    degradation_pct: float = 5.0,
    min_absolute_delta: float = 0.5,
    no_change_threshold: float = 0.5,
) -> dict | None:
    """Core today-vs-7-day-avg comparison shared by degraded-only and all-cell paths."""
    if len(series) < min_history_days + 1:
        return None
    latest_day, latest_val = series[0]
    history = [val for _, val in series[1:]]
    if len(history) < min_history_days:
        return None
    week_avg = sum(history) / len(history)
    raw_delta = latest_val - week_avg
    base = max(abs(week_avg), 0.01)
    change_pct = (raw_delta / base) * 100.0

    if abs(raw_delta) < no_change_threshold:
        change_direction = "no_change"
    elif raw_delta > 0:
        change_direction = "increased"
    else:
        change_direction = "decreased"

    if direction == "higher_worse":
        severity_delta = raw_delta
        if abs(week_avg) < 1.0:
            degraded = severity_delta >= max(min_absolute_delta, 1.0)
        else:
            degraded = severity_delta >= min_absolute_delta and change_pct >= degradation_pct
    else:
        severity_delta = week_avg - latest_val
        if week_avg > 99.0:
            degraded = severity_delta >= max(min_absolute_delta, 1.0)
        else:
            degraded = severity_delta >= min_absolute_delta and change_pct >= degradation_pct

    return {
        "latest_day": latest_day,
        "today_value": round(latest_val, 2),
        "week_avg": round(week_avg, 2),
        "delta": round(raw_delta, 2),
        "severity_delta": round(severity_delta, 2),
        "change_pct": round(min(abs(change_pct), 999.0), 2),
        "history_days": len(history),
        "change_direction": change_direction,
        "degraded": degraded,
        "daily_series": list(reversed(series)),
    }


def benchmark_cell_vs_week(
    series: list[tuple[str, float]],
    *,
    direction: str,
    min_history_days: int = 3,
    degradation_pct: float = 5.0,
    min_absolute_delta: float = 0.5,
) -> dict | None:
    """Compare latest daily value to average of previous days in the series."""
    bench = _benchmark_from_series(
        series,
        direction=direction,
        min_history_days=min_history_days,
        degradation_pct=degradation_pct,
        min_absolute_delta=min_absolute_delta,
    )
    if not bench or not bench.get("degraded"):
        return None
    out = dict(bench)
    out["degraded"] = True
    out.pop("daily_series", None)
    out.pop("severity_delta", None)
    out.pop("change_direction", None)
    return out


def benchmark_cell_change(
    series: list[tuple[str, float]],
    *,
    direction: str,
    min_history_days: int = 3,
    degradation_pct: float = 5.0,
    min_absolute_delta: float = 0.5,
    no_change_threshold: float = 0.5,
) -> dict | None:
    """Return today vs 7-day avg for any cell with enough history."""
    return _benchmark_from_series(
        series,
        direction=direction,
        min_history_days=min_history_days,
        degradation_pct=degradation_pct,
        min_absolute_delta=min_absolute_delta,
        no_change_threshold=no_change_threshold,
    )


def collect_degraded_cells(
    category_presets: dict[str, dict],
    *,
    vendor: str = "all",
    technology: str = "4G",
    scope: str | None = None,
    lookback_days: int = 7,
    min_history_days: int = 3,
    degradation_pct: float = 5.0,
    min_absolute_delta: float = 0.5,
) -> list[dict]:
    """Find cells whose latest daily KPI is worse than the prior-week average."""
    degraded: list[dict] = []
    for cat_name, preset in category_presets.items():
        direction = preset["direction"]
        aliases = preset["aliases"]
        for vlabel, db_path, table in vendor_pm_sources(vendor, technology, scope):
            col = resolve_kpi_column(db_path, table, aliases)
            if not col:
                continue
            series_map = _cell_daily_kpi_series(
                db_path, table, col, lookback_days=lookback_days,
            )
            for cell, series in series_map.items():
                bench = benchmark_cell_vs_week(
                    series,
                    direction=direction,
                    min_history_days=min_history_days,
                    degradation_pct=degradation_pct,
                    min_absolute_delta=min_absolute_delta,
                )
                if not bench:
                    continue
                degraded.append({
                    "cell_name": cell,
                    "vendor": vlabel,
                    "technology": technology,
                    "category": cat_name,
                    "kpi_column": col,
                    "pm_data_scope": _normalize_scope(scope),
                    "direction": direction,
                    **bench,
                })
    return degraded


def collect_category_benchmarks(
    category: str,
    preset: dict,
    *,
    vendor: str = "all",
    technology: str = "4G",
    scope: str | None = None,
    lookback_days: int = 7,
    min_history_days: int = 3,
    degradation_pct: float = 5.0,
    min_absolute_delta: float = 0.5,
    no_change_threshold: float = 0.5,
) -> list[dict]:
    """All cells with today vs 7-day avg for one KPI category."""
    direction = preset["direction"]
    aliases = preset["aliases"]
    rows: list[dict] = []
    for vlabel, db_path, table in vendor_pm_sources(vendor, technology, scope):
        col = resolve_kpi_column(db_path, table, aliases)
        if not col:
            continue
        series_map = _cell_daily_kpi_series(
            db_path, table, col, lookback_days=lookback_days,
        )
        for cell, series in series_map.items():
            bench = benchmark_cell_change(
                series,
                direction=direction,
                min_history_days=min_history_days,
                degradation_pct=degradation_pct,
                min_absolute_delta=min_absolute_delta,
                no_change_threshold=no_change_threshold,
            )
            if not bench:
                continue
            rows.append({
                "cell_name": cell,
                "vendor": vlabel,
                "technology": technology,
                "category": category,
                "kpi_column": col,
                "kpi_label": col,
                "pm_data_scope": _normalize_scope(scope),
                "direction": direction,
                **bench,
            })
    return rows


def _resolve_pm_table_axes_bulk(
    conn: sqlite3.Connection,
    table_name: str,
    kpi_columns: list[str],
) -> tuple[str, str, list[str]] | None:
    cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()]
    if not cols:
        return None
    cell_col = _find_col(cols, _CELL_COL_CANDIDATES + ["DN", "dn"])
    ts_col = _find_col(cols, _TS_COL_CANDIDATES + ["Date", "date", "Time", "time"])
    kpi_cols = [k for k in kpi_columns if k in cols]
    if not cell_col or not ts_col or not kpi_cols:
        return None
    return cell_col, ts_col, kpi_cols


def _scan_all_kpi_daily_series(
    pm_db_path: str,
    table_name: str,
    kpi_columns: list[str],
    *,
    lookback_days: int = 7,
) -> dict[str, dict[str, list[tuple[str, float]]]]:
    """Single PM table scan -> {kpi: {cell: [(day, value), ...]}} newest first."""
    empty: dict[str, dict[str, list[tuple[str, float]]]] = {}
    if not pm_db_path or not os.path.isfile(pm_db_path) or not kpi_columns:
        return empty

    conn = sqlite3.connect(pm_db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        axes = _resolve_pm_table_axes_bulk(conn, table_name, kpi_columns)
        if not axes:
            return empty
        cell_col, ts_col, kpi_cols = axes
        rowid_cutoff = _rowid_scan_cutoff(conn, table_name, lookback_days)
        col_sql = ", ".join(f'"{c}"' for c in kpi_cols)
        where_parts: list[str] = []
        params: list[object] = []
        if rowid_cutoff is not None:
            where_parts.append("rowid >= ?")
            params.append(rowid_cutoff)
        where_sql = f" WHERE {' AND '.join(where_parts)}" if where_parts else ""
        sql = f"""
            SELECT "{cell_col}" AS cell_name, "{ts_col}" AS ts_raw, {col_sql}
            FROM "{table_name}"{where_sql}
            ORDER BY "{cell_col}", "{ts_col}" DESC
        """

        series: dict[str, dict[str, list[tuple[str, float]]]] = {k: {} for k in kpi_cols}
        seen: dict[str, dict[str, set[str]]] = {k: {} for k in kpi_cols}
        max_points = lookback_days + 1

        for row in conn.execute(sql, params):
            cell = str(row["cell_name"] or "").strip()
            day = parse_pm_timestamp(row["ts_raw"])
            if not cell or not day:
                continue
            for kpi_col in kpi_cols:
                val = _to_float(row[kpi_col])
                if val is None:
                    continue
                cell_seen = seen[kpi_col].setdefault(cell, set())
                if day in cell_seen:
                    continue
                cell_seen.add(day)
                bucket = series[kpi_col].setdefault(cell, [])
                bucket.append((day, val))
                if len(bucket) >= max_points:
                    continue
        return series
    except sqlite3.Error:
        return empty
    finally:
        conn.close()


def collect_all_kpi_benchmarks(
    kpi_columns: list[str],
    *,
    vendor: str = "all",
    technology: str = "4G",
    scope: str | None = None,
    lookback_days: int = 7,
    min_history_days: int = 3,
    no_change_threshold: float = 0.5,
) -> dict[str, list[dict]]:
    """All KPI columns in one PM scan -> {kpi_column: [cell benchmark rows]}."""
    out: dict[str, list[dict]] = {k: [] for k in kpi_columns}
    if not kpi_columns:
        return out

    for vlabel, db_path, table in vendor_pm_sources(vendor, technology, scope):
        table_cols = _table_columns(db_path, table)
        active_kpis = [k for k in kpi_columns if k in table_cols]
        if not active_kpis:
            continue

        kpi_sig = hash(tuple(sorted(active_kpis)))
        cache_key = (
            f"all|{vlabel}|{db_path}|{table}|{lookback_days}|"
            f"{min_history_days}|{no_change_threshold}|{kpi_sig}"
        )
        cached = _cache_get(_ALL_BENCHMARK_CACHE, cache_key, db_path)
        if cached is not None:
            for kpi, rows in cached.items():
                out.setdefault(kpi, []).extend(rows)
            continue

        vendor_out: dict[str, list[dict]] = {k: [] for k in active_kpis}
        series_map = _scan_all_kpi_daily_series(
            db_path, table, active_kpis, lookback_days=lookback_days,
        )
        for kpi_col, cell_map in series_map.items():
            rows: list[dict] = []
            for cell, series in cell_map.items():
                bench = benchmark_cell_change(
                    series,
                    direction="higher_worse",
                    min_history_days=min_history_days,
                    no_change_threshold=no_change_threshold,
                )
                if not bench:
                    continue
                bench.pop("daily_series", None)
                bench.pop("severity_delta", None)
                rows.append({
                    "cell_name": cell,
                    "vendor": vlabel,
                    "technology": technology,
                    "kpi_column": kpi_col,
                    "kpi_label": kpi_col,
                    "pm_data_scope": _normalize_scope(scope),
                    **bench,
                })
            vendor_out[kpi_col] = rows

        _cache_set(_ALL_BENCHMARK_CACHE, cache_key, db_path, vendor_out)
        for kpi, rows in vendor_out.items():
            out.setdefault(kpi, []).extend(rows)

    return out


def collect_kpi_benchmarks(
    kpi_column: str,
    *,
    vendor: str = "all",
    technology: str = "4G",
    scope: str | None = None,
    lookback_days: int = 7,
    min_history_days: int = 3,
    no_change_threshold: float = 0.5,
) -> list[dict]:
    """All cells for one KPI column with today vs 7-day avg."""
    all_rows = collect_all_kpi_benchmarks(
        [kpi_column],
        vendor=vendor,
        technology=technology,
        scope=scope,
        lookback_days=lookback_days,
        min_history_days=min_history_days,
        no_change_threshold=no_change_threshold,
    )
    return all_rows.get(kpi_column, [])


def _table_columns(db_path: str, table: str) -> set[str]:
    if not db_path or not os.path.isfile(db_path):
        return set()
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        return {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}
    except sqlite3.Error:
        return set()
    finally:
        conn.close()


def _resolve_kpi_column_in_table(db_path: str, table: str, kpi_column: str) -> str | None:
    cols = _table_columns(db_path, table)
    if kpi_column in cols:
        return kpi_column
    return resolve_kpi_column(db_path, table, [kpi_column])


def _cell_kpi_hourly_series(
    pm_db_path: str,
    table_name: str,
    cell_name: str,
    kpi_column: str,
    *,
    max_points: int = 336,
) -> list[tuple[str, float]]:
    """Hourly KPI points for one cell, oldest first."""
    if not pm_db_path or not os.path.isfile(pm_db_path):
        return []
    resolved_kpi = _resolve_kpi_column_in_table(pm_db_path, table_name, kpi_column)
    if not resolved_kpi:
        return []

    def _query(exact: bool) -> list[tuple[str, float]]:
        out: list[tuple[str, float]] = []
        conn = sqlite3.connect(pm_db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()]
            cell_col = _find_col(cols, _CELL_COL_CANDIDATES + ["DN", "dn"])
            ts_col = _find_col(cols, _TS_COL_CANDIDATES + ["Date", "date", "Time", "time"])
            if not cell_col or not ts_col:
                return out
            if exact:
                where = f'LOWER(TRIM(CAST("{cell_col}" AS TEXT))) = LOWER(TRIM(?))'
                param = cell_name
            else:
                where = f'LOWER(TRIM(CAST("{cell_col}" AS TEXT))) LIKE LOWER(TRIM(?))'
                param = f"%{cell_name}%"
            sql = f"""
                SELECT "{ts_col}" AS ts_raw, "{resolved_kpi}" AS kpi_value
                FROM "{table_name}"
                WHERE {where}
                  AND "{resolved_kpi}" IS NOT NULL
                ORDER BY "{ts_col}" DESC
                LIMIT ?
            """
            for row in conn.execute(sql, (param, max(1, max_points))):
                val = _to_float(row["kpi_value"])
                ts_raw = str(row["ts_raw"] or "").strip()
                if val is None or not ts_raw:
                    continue
                out.append((ts_raw, val))
        except sqlite3.Error:
            return []
        finally:
            conn.close()
        out.reverse()
        return out

    pts = _query(exact=True)
    if not pts:
        pts = _query(exact=False)
    return pts
