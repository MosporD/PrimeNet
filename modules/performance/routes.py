"""
Performance Routes
==================
Three-database architecture:
  metadata.db          → sites, cells (source of truth, all vendors)
  nokia_pm_cells.db   → Nokia hourly KPIs keyed by cell_name
  huawei_pm_cells.db  → Huawei PM: same hourly tables as Nokia (2G_Hourly … 5G_Hourly)

KPI columns are dynamic — whatever headers were in the source files are stored
as-is in the PM databases. Queries build their SELECT lists by inspecting the
live DB schema so no code changes are needed when the file structure changes.
"""

from flask import Blueprint, request, jsonify, render_template, redirect, url_for, current_app
from functools import wraps
from collections import defaultdict
from datetime import datetime, timedelta
import sqlite3
import os
import sys
import json
import time
import re
import math
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from sync_config import (
    NOKIA_PM_DB,
    HUAWEI_PM_DB,
    NOKIA_PM_DAILY_DB,
    HUAWEI_PM_DAILY_DB,
    METADATA_DB,
    KPI_HEADERS_DB,
    NOKIA_GROUPS_DB,
    HUAWEI_GROUPS_DB,
    NOKIA_GROUPS_DAILY_DB,
    HUAWEI_GROUPS_DAILY_DB,
    PM_TECHNOLOGIES,
    pm_table_name,
)
from db.runtime import connect_app, connect_metadata, execute_query
from database_enhanced import get_user_by_session, log_activity
from modules.sync.metadata_active_sql import perf_per_tech_union_sql, perf_per_tech_union_sql_with_activity
from .kpi_catalog import KPI_HEADERS_MAP
from .kpi_mapping import get_kpi_mapping_payload

performance_bp = Blueprint(
    'performance', __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/performance/static',
)


def _meta_exec(conn, sql: str, params=()):
    """Run SQL on metadata or PM+metadata connection (SQLite ``.execute`` or Postgres via ``execute_query``)."""
    return execute_query(conn, sql, params or ())


_FIXED_COLS = {'id', 'cell_name', 'timestamp', 'Date', 'date', 'Time', 'PERIOD_START_TIME'}
# Match PRAGMA names after lower/strip (spaces kept); include spaced Nokia export headers.
_TIME_COL_ALIASES = (
    'timestamp',
    'time',
    'period_start_time',
    'period start time',
    'date',
)
_CELL_COL_ALIASES = (
    'cell_name', 'cell name',
    'bts name', 'wcel name', 'lncel name', 'nrcel name',
    'bcf name',  # Nokia 2G daily exports (BCF-level; no BTS name column)
    'dn',
)
_GROUP_ID_ALIASES = ('group', 'grp', 'ws_name', 'ws name')


def _clamp_trend_hours(raw) -> int:
    try:
        h = int(raw)
    except (TypeError, ValueError):
        h = 168
    return max(1, min(h, 8760))


def _normalize_granularity(arg) -> str:
    g = (arg or 'hour').strip().lower()
    if g in ('h', 'hour', 'hourly', '1'):
        return 'hour'
    if g in ('d', 'day', 'daily'):
        return 'day'
    if g in ('m', 'month', 'monthly'):
        return 'month'
    return 'hour'


def _normalize_data_scope(arg) -> str:
    s = (arg or 'hourly').strip().lower()
    if s in ('d', 'day', 'daily'):
        return 'daily'
    return 'hourly'


def _norm_vendor_for_pm(vendor: str) -> str:
    """Canonical vendor for PM / groups DB paths (metadata may use any casing)."""
    v = str(vendor or '').strip().lower()
    if v == 'huawei':
        return 'Huawei'
    return 'Nokia'


def _pm_db_for_vendor(vendor: str, scope: str = 'hourly') -> str:
    s = _normalize_data_scope(scope)
    if _norm_vendor_for_pm(vendor) == 'Huawei':
        return HUAWEI_PM_DAILY_DB if s == 'daily' else HUAWEI_PM_DB
    return NOKIA_PM_DAILY_DB if s == 'daily' else NOKIA_PM_DB


def _groups_db_for_vendor(vendor: str, scope: str = 'hourly') -> str:
    s = _normalize_data_scope(scope)
    if _norm_vendor_for_pm(vendor) == 'Huawei':
        return HUAWEI_GROUPS_DAILY_DB if s == 'daily' else HUAWEI_GROUPS_DB
    return NOKIA_GROUPS_DAILY_DB if s == 'daily' else NOKIA_GROUPS_DB


def _parse_trend_ts(val, prefer_dayfirst: bool | None = None):
    if val is None:
        return None
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        try:
            if float(val).is_integer() and float(val) > 10_000_000_000:  # ms epoch guard
                return datetime.utcfromtimestamp(float(val) / 1000.0)
            if float(val) > 10_000_000:  # seconds
                return datetime.utcfromtimestamp(float(val))
        except (TypeError, ValueError, OSError):
            return None
    s = str(val).strip()
    if not s or s.lower() in ('nan', 'nat', 'none'):
        return None
    # Huawei PM exports may append timezone-like tokens (e.g. 'DST').
    s = re.sub(r'\s+[A-Za-z]{2,5}$', '', s).strip()
    try:
        s_iso = s
        if s_iso.endswith('Z'):
            s_iso = s_iso[:-1] + '+00:00'
        if 'T' not in s_iso and len(s_iso) >= 10:
            s_iso = s_iso.replace(' ', 'T', 1)
        dt = datetime.fromisoformat(s_iso.split('.')[0])
        if dt.tzinfo:
            return dt.replace(tzinfo=None)
        return dt
    except ValueError:
        pass
    # For ambiguous date strings, apply caller hint:
    # - Nokia PERIOD_START_TIME tends to be month.day.year (prefer_dayfirst=False)
    # - Huawei Date tends to be day/month/year (prefer_dayfirst=True)
    dayfirst_dotted = (
        (
            '%d.%m.%Y %H:%M:%S',
            '%d.%m.%Y %H:%M',
            '%d.%m.%Y',
            '%d.%m.%y %H:%M:%S',
            '%d.%m.%y %H:%M',
            '%d.%m.%y',
            '%m.%d.%Y %H:%M:%S',
            '%m.%d.%y %H:%M:%S',
            '%m.%d.%Y',
            '%m.%d.%y',
        )
        if prefer_dayfirst is not False
        else
        (
            '%m.%d.%Y %H:%M:%S',
            '%m.%d.%y %H:%M:%S',
            '%m.%d.%Y',
            '%m.%d.%y',
            '%d.%m.%Y %H:%M:%S',
            '%d.%m.%Y %H:%M',
            '%d.%m.%Y',
            '%d.%m.%y %H:%M:%S',
            '%d.%m.%y %H:%M',
            '%d.%m.%y',
        )
    )

    fmts = (
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %H:%M',
        '%Y-%m-%d',
        '%Y/%m/%d %H:%M:%S',
        '%Y/%m/%d %H:%M',
        '%Y/%m/%d',
        '%d/%m/%Y',
        '%d/%m/%y',
        '%d-%m-%Y',
        '%d-%m-%y',
        '%d/%m/%y %H:%M',
        '%d/%m/%Y %H:%M',
    ) + dayfirst_dotted
    for fmt in fmts:
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    # Last-resort parsing for mixed exports; prefer day-first, then month-first.
    try:
        pref = prefer_dayfirst
        order = (True, False) if pref is not False else (False, True)
        for dayfirst in order:
            t = pd.to_datetime(s, errors='coerce', dayfirst=dayfirst)
            if pd.notna(t):
                return t.to_pydatetime().replace(tzinfo=None)
        t = pd.to_datetime(s, errors='coerce', dayfirst=True)
        if pd.notna(t):
            return t.to_pydatetime().replace(tzinfo=None)
    except Exception:
        pass
    return None


def _pick_trend_time_value(row: dict, granularity: str) -> tuple[object, bool | None]:
    """Pick row timestamp value plus parse hint (day-first or month-first)."""
    source_col = str(row.get('__time_source') or '').strip().lower()
    if source_col in ('period_start_time', 'period start time'):
        v = row.get('timestamp')
        if v is not None and str(v).strip().lower() not in ('', 'nan', 'nat', 'none'):
            return v, False
    if source_col in ('date',):
        v = row.get('timestamp')
        if v is not None and str(v).strip().lower() not in ('', 'nan', 'nat', 'none'):
            return v, True

    gran = (granularity or 'hour').lower()
    if gran == 'hour':
        ordered_keys = ('timestamp', 'Time', 'PERIOD_START_TIME', 'Date', 'date')
    else:
        ordered_keys = ('Date', 'date', 'timestamp', 'Time', 'PERIOD_START_TIME')

    for k in ordered_keys:
        v = row.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if not s or s.lower() in ('nan', 'nat', 'none'):
            continue
        # Vendor/date-source hints for ambiguous strings.
        if k in ('Date', 'date'):
            return v, True   # Huawei Date style: day/month/year
        if k == 'PERIOD_START_TIME':
            return v, False  # Nokia style: month.day.year
        return v, None
    return None, None


def _log_trend_time_parse_sample(
    logger_obj,
    *,
    endpoint: str,
    vendor: str,
    table: str,
    time_col: str,
    rows: list[dict],
    granularity: str,
    max_rows: int = 10,
) -> None:
    """
    Temporary debug helper: print how DB time values are interpreted for charting.
    """
    try:
        sample = rows[: max(1, int(max_rows or 10))]
    except Exception:
        sample = rows[:10]
    parsed_preview = []
    for row in sample:
        ts_raw, prefer_dayfirst = _pick_trend_time_value(row, granularity)
        dt = _parse_trend_ts(ts_raw, prefer_dayfirst=prefer_dayfirst)
        parsed_preview.append({
            'db_time_col_raw': row.get(time_col),
            'selected_ts_raw': ts_raw,
            'prefer_dayfirst': prefer_dayfirst,
            'parsed_ts': dt.strftime('%Y-%m-%d %H:%M:%S') if dt else None,
        })
    logger_obj.info(
        'trend-time-parse endpoint=%s vendor=%s table=%s time_col=%s granularity=%s sample=%s',
        endpoint,
        vendor,
        table,
        time_col,
        granularity,
        parsed_preview,
    )


def _aggregate_trend_rows(rows: list[dict], granularity: str) -> list[dict]:
    """
    Roll up raw PM rows to hour / day / month buckets (mean numeric KPIs per bucket).
    ``hour`` collapses duplicate timestamps within the same clock hour.
    """
    if not rows:
        return rows
    gran = (granularity or 'hour').lower()
    if gran not in ('hour', 'day', 'month'):
        gran = 'hour'

    def bucket_label(dt: datetime) -> str:
        if gran == 'hour':
            z = dt.replace(minute=0, second=0, microsecond=0)
            return z.strftime('%Y-%m-%d %H:%M:%S')
        if gran == 'day':
            return datetime(dt.year, dt.month, dt.day).strftime('%Y-%m-%d %H:%M:%S')
        return datetime(dt.year, dt.month, 1).strftime('%Y-%m-%d %H:%M:%S')

    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        # Daily/monthly exports can carry a flat "timestamp" while "Date" changes;
        # prefer Date-like columns for non-hourly rollups to avoid point collapse.
        ts_raw, prefer_dayfirst = _pick_trend_time_value(row, gran)
        dt = _parse_trend_ts(ts_raw, prefer_dayfirst=prefer_dayfirst)
        if dt is None:
            continue
        buckets[bucket_label(dt)].append(row)

    out = []
    skip = set(_FIXED_COLS)
    for label in sorted(buckets.keys()):
        group = buckets[label]
        merged = dict(group[0])
        merged['timestamp'] = label
        keys = [k for k in group[0] if k not in skip]
        for k in keys:
            vals = []
            for r in group:
                v = r.get(k)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    vals.append(float(v))
                elif isinstance(v, str) and str(v).strip():
                    try:
                        vals.append(float(str(v).strip().replace(',', '')))
                    except ValueError:
                        pass
            if vals:
                merged[k] = sum(vals) / len(vals)
        out.append(merged)
    return out


def _filter_trend_rows_by_hours(rows: list[dict], hours: int, granularity: str = 'hour') -> list[dict]:
    """Keep only rows within `hours` from the latest valid timestamp."""
    if not rows:
        return rows
    gran = (granularity or 'hour').lower()
    parsed = []
    for row in rows:
        ts_raw, prefer_dayfirst = _pick_trend_time_value(row, gran)
        dt = _parse_trend_ts(ts_raw, prefer_dayfirst=prefer_dayfirst)
        if dt is None:
            continue
        parsed.append((dt, row))
    if not parsed:
        return []
    parsed.sort(key=lambda x: x[0])
    latest = parsed[-1][0]
    try:
        h = max(1, int(hours))
    except Exception:
        h = 168
    cutoff = latest - timedelta(hours=h)
    return [row for dt, row in parsed if dt >= cutoff]
_VENDOR_TECH_SCOPE = {
    'Nokia': ['2G', '3G', '4G', '5G'],
    'Huawei': ['2G', '3G', '4G'],
}


def _kpi_headers_static_for(vendor: str, technology: str) -> list[str]:
    return _drop_duplicate_kpis(list(KPI_HEADERS_MAP.get(f'{vendor}|{technology}', [])))


def _use_static_kpi_catalog() -> bool:
    """
    Optional fallback mode: /api/...?...&kpi_mode=static
    Default behavior is dynamic scan from PM tables.
    """
    return (request.args.get('kpi_mode') or '').strip().lower() == 'static'

# ---------------------------------------------------------------------------
# PM table view — static identifier columns per vendor / technology
# ---------------------------------------------------------------------------

_PM_STATIC_COLS = {
    'Huawei': {
        '2G': ['timestamp', 'cell_name', 'GBSC', 'Cell CI', 'CellIndex'],
        '3G': ['timestamp', 'cell_name', 'RNC', 'Cell ID', 'NodeB Name'],
        '4G': ['timestamp', 'cell_name', 'eNodeB Name', 'Cell FDD TDD Indication',
               'LocalCell Id', 'eNodeB Function Name'],
    },
    'Nokia': {
        '2G': ['timestamp', 'cell_name', 'BSC name', 'BCF name'],
        '3G': ['timestamp', 'cell_name', 'PLMN name', 'RNC name',
               'WBTS name', 'WBTS ID', 'WCEL ID'],
        '4G': ['timestamp', 'cell_name', 'MRBTS name', 'LNBTS name'],
        '5G': ['timestamp', 'cell_name', 'MRBTS name', 'NRBTS name'],
    },
}

_PM_EXCLUDE_COLS = {'id', 'Integrity'}
_DUPLICATE_KPI_NAMES = {
    'RH303:Handover Success Rate(%)',
    'K3034:TCHH Traffic Volume(Erl)',
    'Drop Call Rate',
    'CS RAB Congestion Num',
    'TCH raw block.1',
    'Act HS-DSCH  end usr thp',
    'Expect cell size',
    'Avg PDCP cell thp UL',
    'TRS_SLOT_PDSCH (M55308C00017)',
}

# Human-readable label for the cell_name column per vendor/technology
_PM_CELL_LABEL = {
    'Huawei': {'2G': 'Cell Name', '3G': 'Cell Name', '4G': 'Cell Name'},
    'Nokia':  {'2G': 'BTS name', '3G': 'WCEL name', '4G': 'LNCEL name', '5G': 'NRCEL name'},
}


def _drop_duplicate_kpis(cols: list[str]) -> list[str]:
    return [c for c in (cols or []) if c not in _DUPLICATE_KPI_NAMES]

# ---------------------------------------------------------------------------
# Lightweight in-memory cache for cell list queries
# ---------------------------------------------------------------------------
_CELL_LIST_CACHE = {}
_CELL_LIST_CACHE_TTL_SEC = 45
_TREND_CACHE = {}
_TREND_CACHE_TTL_SEC = 120
_TREND_CACHE_SCHEMA_VER = "v4"
_PM_TABLE_CACHE_SCHEMA_VER = "v3"
_PM_TABLE_CACHE = {}
_PM_TABLE_CACHE_TTL_SEC = 90


def _db_mtime_token(db_path: str) -> str:
    try:
        st = os.stat(db_path)
        return str(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000)))
    except OSError:
        return "0"


def _pm_data_version_token(vendor: str = "", include_metadata: bool = True, scope: str = "hourly") -> str:
    """
    Lightweight invalidation token based on SQLite file mtimes.
    Any PM/metadata update changes the key namespace and stale cache entries are bypassed.
    """
    vendors = [_norm_vendor_for_pm(vendor)] if str(vendor or "").strip() else ["Nokia", "Huawei"]
    parts = []
    if include_metadata:
        parts.append(f"meta:{_db_mtime_token(METADATA_DB)}")
    for v in vendors:
        db_path = _pm_db_for_vendor(v, scope)
        parts.append(f"{v.lower()}:{_db_mtime_token(db_path)}")
    return "|".join(parts)


def _cell_cache_key(
    vendor: str,
    technology: str,
    site_id: str,
    cluster: str,
    area: str,
    version_token: str,
) -> str:
    return '||'.join([
        (version_token or '').strip(),
        (vendor or '').strip(),
        (technology or '').strip(),
        (site_id or '').strip(),
        (cluster or '').strip(),
        (area or '').strip(),
    ])


def _cell_cache_get(key: str):
    item = _CELL_LIST_CACHE.get(key)
    if not item:
        return None
    expires_at, payload = item
    if expires_at < time.time():
        _CELL_LIST_CACHE.pop(key, None)
        return None
    return payload


def _cell_cache_set(key: str, payload):
    _CELL_LIST_CACHE[key] = (time.time() + _CELL_LIST_CACHE_TTL_SEC, payload)


def _trend_cache_key(
    scope: str,
    cell_ref: str,
    vendor: str,
    table: str,
    hours: int,
    granularity: str,
    requested_kpis: list | None,
    version_token: str,
) -> str:
    req = ",".join(requested_kpis or [])
    return "||".join([
        _TREND_CACHE_SCHEMA_VER,
        scope,
        version_token,
        cell_ref or "",
        vendor or "",
        table or "",
        str(int(hours or 0)),
        granularity or "hour",
        req,
    ])


def _trend_cache_get(key: str):
    item = _TREND_CACHE.get(key)
    if not item:
        return None
    expires_at, payload = item
    if expires_at < time.time():
        _TREND_CACHE.pop(key, None)
        return None
    return payload


def _trend_cache_set(key: str, payload):
    _TREND_CACHE[key] = (time.time() + _TREND_CACHE_TTL_SEC, payload)


def _pm_table_cache_key(
    vendor: str,
    technology: str,
    table: str,
    search: str,
    page: int,
    page_size: int,
    version_token: str,
) -> str:
    return "||".join([
        _PM_TABLE_CACHE_SCHEMA_VER,
        version_token,
        vendor or "",
        technology or "",
        table or "",
        search or "",
        str(int(page or 1)),
        str(int(page_size or 100)),
    ])


def _pm_table_cache_get(key: str):
    item = _PM_TABLE_CACHE.get(key)
    if not item:
        return None
    expires_at, payload = item
    if expires_at < time.time():
        _PM_TABLE_CACHE.pop(key, None)
        return None
    return payload


def _pm_table_cache_set(key: str, payload):
    _PM_TABLE_CACHE[key] = (time.time() + _PM_TABLE_CACHE_TTL_SEC, payload)

# ---------------------------------------------------------------------------
# PM KPI column discovery (PRAGMA + per-column counts) — cache briefly
# ---------------------------------------------------------------------------
_KPI_COLS_CACHE = {}
_KPI_COLS_CACHE_TTL_SEC = 90


def _kpi_headers_db_available() -> bool:
    return os.path.isfile(KPI_HEADERS_DB)


def _kpi_scope_from_catalog(vendor: str = "", technology: str = "") -> list[str]:
    if not _kpi_headers_db_available():
        return []
    where = []
    params = []
    if vendor:
        where.append("vendor = ?")
        params.append(vendor)
    if technology:
        where.append("technology = ?")
        params.append(technology)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    conn = sqlite3.connect(KPI_HEADERS_DB, timeout=15)
    try:
        rows = conn.execute(
            f"""
            SELECT kpi_name
            FROM kpi_scope
            {where_sql}
            ORDER BY kpi_name
            """,
            params,
        ).fetchall()
        return _drop_duplicate_kpis([str(r[0]) for r in rows])
    except Exception:
        return []
    finally:
        conn.close()


def _kpi_mapping_from_catalog() -> dict[str, list[str]]:
    if not _kpi_headers_db_available():
        return {}
    conn = sqlite3.connect(KPI_HEADERS_DB, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT vendor, technology, kpi_name
            FROM kpi_scope
            ORDER BY vendor, technology, kpi_name
            """
        ).fetchall()
    except Exception:
        conn.close()
        return {}
    conn.close()
    mapping: dict[str, list[str]] = {}
    for r in rows:
        key = f"{r['vendor']}|{r['technology']}"
        kpi_name = str(r["kpi_name"])
        if kpi_name in _DUPLICATE_KPI_NAMES:
            continue
        mapping.setdefault(key, []).append(kpi_name)
    return mapping


def _pm_cols_cache_key(db_path, table: str) -> str:
    m = _db_mtime_token(str(db_path))
    return f'{os.path.abspath(str(db_path))}||{table}||{m}'


def _requested_trend_kpi_names():
    """
    Optional narrow trend SELECT: ?kpi=col1,col2 or repeated ?kpi=…
    Only names that exist in the table (after server-side intersect) are used.
    """
    parts = []
    lst = request.args.getlist('kpi')
    if lst:
        for item in lst:
            parts.extend(str(item).split(','))
    else:
        raw = (request.args.get('kpi') or request.args.get('kpis') or '').strip()
        if raw:
            parts = raw.split(',')
    fixed = {c.lower() for c in _FIXED_COLS}
    out, seen = [], set()
    for p in parts:
        t = str(p).strip()
        if not t or t.lower() in fixed:
            continue
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out if out else None


def _trend_kpi_columns(full_kpi_cols: list, requested: list | None) -> list:
    if not full_kpi_cols:
        return []
    if not requested:
        return full_kpi_cols
    allow = set(full_kpi_cols)
    picked = [c for c in requested if c in allow]
    return picked if picked else full_kpi_cols

# ---------------------------------------------------------------------------
# Cluster / Area derivation  (same logic as network_map/static/map.js)
# cluster = floor(site_id / 100),  area = CLUSTER_AREA[cluster]
# ---------------------------------------------------------------------------

_CLUSTER_AREA = {
     3: 'East Amman',  13: 'East Amman',  17: 'East Amman',  21: 'East Amman',
    23: 'East Amman',  27: 'East Amman',  48: 'East Amman',  49: 'East Amman',
    50: 'East Amman',  51: 'East Amman',  52: 'East Amman',  54: 'East Amman',
    10: 'East Jordan', 11: 'East Jordan', 19: 'East Jordan', 28: 'East Jordan',
    31: 'East Jordan', 42: 'East Jordan', 43: 'East Jordan', 47: 'East Jordan',
     1: 'South Amman',  6: 'South Amman',  9: 'South Amman', 18: 'South Amman',
    30: 'South Amman', 36: 'South Amman', 38: 'South Amman', 39: 'South Amman',
    53: 'South Amman', 57: 'South Amman', 59: 'South Amman',
     7: 'South Jordan',  8: 'South Jordan', 12: 'South Jordan', 15: 'South Jordan',
    33: 'South Jordan', 41: 'South Jordan', 58: 'South Jordan',
     2: 'West Amman',   5: 'West Amman',  16: 'West Amman',  20: 'West Amman',
    22: 'West Amman',  25: 'West Amman',  26: 'West Amman',  32: 'West Amman',
    35: 'West Amman',  40: 'West Amman',  55: 'West Amman',  56: 'West Amman',
     4: 'North Jordan', 14: 'North Jordan', 24: 'North Jordan', 29: 'North Jordan',
    34: 'North Jordan', 37: 'North Jordan', 44: 'North Jordan', 45: 'North Jordan',
    46: 'North Jordan', 65: 'North Jordan',
}


def _derive_cluster_area(site_id):
    """Derive (cluster, area) from a numeric site_id, matching the network map logic."""
    try:
        cluster_num = int(site_id) // 100
    except (TypeError, ValueError):
        return None, None
    area = _CLUSTER_AREA.get(cluster_num)
    return cluster_num, area


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lng / 2) ** 2
    )
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _build_site_area_index(conn) -> dict[str, tuple[int | None, str | None]]:
    """
    Build site_id -> (cluster, area), inferring unknown areas from nearest known site.
    """
    rows = [dict(r) for r in _meta_exec(
        conn,
        'SELECT site_id, latitude, longitude FROM sites WHERE site_id IS NOT NULL',
    ).fetchall()]
    resolved: dict[str, dict] = {}
    known: list[tuple[float, float, str]] = []
    unknown_with_geo: list[tuple[str, float, float]] = []

    for r in rows:
        sid = str(r.get('site_id'))
        cluster, area = _derive_cluster_area(r.get('site_id'))
        resolved[sid] = {'cluster': cluster, 'area': area}

        lat = r.get('latitude')
        lng = r.get('longitude')
        try:
            lat_f = float(lat) if lat is not None else None
            lng_f = float(lng) if lng is not None else None
        except (TypeError, ValueError):
            lat_f = None
            lng_f = None
        if lat_f is None or lng_f is None:
            continue

        if area:
            known.append((lat_f, lng_f, area))
        else:
            unknown_with_geo.append((sid, lat_f, lng_f))

    if known:
        for sid, lat_f, lng_f in unknown_with_geo:
            nearest_area = None
            nearest_dist = None
            for k_lat, k_lng, k_area in known:
                d = _haversine_km(lat_f, lng_f, k_lat, k_lng)
                if nearest_dist is None or d < nearest_dist:
                    nearest_dist = d
                    nearest_area = k_area
            if nearest_area:
                resolved[sid]['area'] = nearest_area

    return {sid: (v.get('cluster'), v.get('area')) for sid, v in resolved.items()}


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        session_token = request.cookies.get('session_token')
        if not session_token:
            return redirect(url_for('auth.login_page'))
        user = get_user_by_session(session_token)
        if not user:
            return redirect(url_for('auth.login_page'))
        request.current_user = user
        return f(*args, **kwargs)
    return decorated


def get_current_user():
    session_token = request.cookies.get('session_token')
    if session_token:
        return get_user_by_session(session_token)
    return None


def format_user(user):
    if not user:
        return None
    if isinstance(user, dict):
        return {'username': user.get('username'), 'role': user.get('role'), 'id': user.get('id')}
    return {'username': user[1], 'role': user[6], 'id': user[0]}


def _user_id(user):
    return user.get('id') if isinstance(user, dict) else user[0]


def _groups_conn(vendor: str, scope: str = 'hourly'):
    conn = sqlite3.connect(_groups_db_for_vendor(vendor, scope), timeout=15)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.row_factory = sqlite3.Row
    return conn


def _has_groups_schema(conn: sqlite3.Connection) -> bool:
    names = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    return 'groups' in names and 'group_cells' in names


def _table_has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    try:
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info({_sqlite_ident(table)})').fetchall()]
    except Exception:
        return False
    want = (column or '').strip().lower()
    return any(str(c).strip().lower() == want for c in cols)


def _pick_first_col(cols: list[str], keywords: tuple[str, ...]) -> str | None:
    low_map = {c: _norm_col_name(c) for c in cols}
    for kw in keywords:
        for c, low in low_map.items():
            if kw in low:
                return c
    return None


def _raw_group_table_specs(conn: sqlite3.Connection) -> list[tuple[str, str, str | None, str | None, str | None]]:
    specs: list[tuple[str, str, str | None, str | None, str | None]] = []
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    for (table,) in rows:
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info({_sqlite_ident(table)})').fetchall()]
        if not cols:
            continue
        gcol = _pick_first_col(cols, ('group', 'grp', 'ws_name', 'ws name'))
        ccol = _pick_first_col(cols, ('cell name', 'cell_name', 'cellname', 'wcel', 'lncel', 'nrcel', 'bts'))
        if not gcol:
            continue
        tcol = _pick_first_col(cols, ('technology', 'tech', 'rat'))
        scol = _pick_first_col(cols, ('site_id', 'site id', 'site'))
        specs.append((table, gcol, ccol, tcol, scol))
    return specs


def _reports_conn():
    return connect_app()


def _ensure_reports_table():
    conn = _reports_conn()
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS performance_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            report_name TEXT NOT NULL,
            report_config TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )
    conn.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS idx_perf_reports_user_name ON performance_reports(user_id, report_name)'
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _meta_conn():
    conn = sqlite3.connect(METADATA_DB, timeout=15)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.row_factory = sqlite3.Row
    return conn


def _is_huawei_pm_db(db_path: str) -> bool:
    try:
        target = os.path.normpath(os.path.abspath(db_path))
        return target in {
            os.path.normpath(os.path.abspath(HUAWEI_PM_DB)),
            os.path.normpath(os.path.abspath(HUAWEI_PM_DAILY_DB)),
        }
    except Exception:
        return False


def _sqlite_ident(name: str) -> str:
    """Quote a SQLite identifier (handles embedded double quotes)."""
    return '"' + str(name).replace('"', '""') + '"'


def _sqlite_text_lit(value: object) -> str:
    """Quote a SQLite text literal (single-quoted, escaped)."""
    return "'" + str(value).replace("'", "''") + "'"


def _norm_col_name(name: str) -> str:
    return str(name or '').strip().lower()


def _table_technology(table_name: str) -> str | None:
    t = _norm_col_name(table_name)
    if any(x in t for x in ('5g', 'nr')):
        return '5G'
    if any(x in t for x in ('4g', 'lte', 'fdd', 'tdd')):
        return '4G'
    if any(x in t for x in ('3g', 'wcdma', 'umts')):
        return '3G'
    if any(x in t for x in ('2g', 'gsm')):
        return '2G'
    return None


def _normalize_group_tech(tech: str) -> str:
    t = str(tech or '').strip()
    if t in ('4G-FDD', '4G-TDD'):
        return '4G'
    return t


def _axis_column_nonempty_count(conn: sqlite3.Connection, table: str, col: str) -> int:
    try:
        return int(
            conn.execute(
                f'SELECT COUNT(*) FROM {_sqlite_ident(table)} '
                f'WHERE {_sqlite_ident(col)} IS NOT NULL '
                f'AND TRIM(CAST({_sqlite_ident(col)} AS TEXT)) != ""'
            ).fetchone()[0]
        )
    except sqlite3.OperationalError:
        return 0


def _pick_axis_column_from_aliases(
    conn: sqlite3.Connection,
    table: str,
    cols: list[str],
    aliases: tuple[str, ...],
) -> str | None:
    """Pick the alias column with the most populated values (legacy empty cell_name wins otherwise)."""
    low_to_real = {_norm_col_name(c): c for c in cols}
    candidates = [low_to_real[a] for a in aliases if low_to_real.get(a)]
    if not candidates:
        return None
    return max(candidates, key=lambda c: _axis_column_nonempty_count(conn, table, c))


def _resolve_pm_axis_columns_sqlite(conn: sqlite3.Connection, table: str) -> tuple[str | None, str | None]:
    try:
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info({_sqlite_ident(table)})').fetchall()]
    except sqlite3.OperationalError:
        return None, None
    cell_col = _pick_axis_column_from_aliases(conn, table, cols, _CELL_COL_ALIASES)
    time_col = _pick_axis_column_from_aliases(conn, table, cols, _TIME_COL_ALIASES)
    return cell_col, time_col


def _pm_table_select_col(
    col: str,
    *,
    resolved_cell_col: str | None,
    resolved_time_col: str | None,
) -> str:
    if col == 'cell_name' and resolved_cell_col:
        if resolved_cell_col == 'cell_name':
            return _sqlite_ident(col)
        return f'{_sqlite_ident(resolved_cell_col)} AS {_sqlite_ident(col)}'
    if col == 'timestamp' and resolved_time_col:
        if resolved_time_col == 'timestamp':
            return _sqlite_ident(col)
        return f'{_sqlite_ident(resolved_time_col)} AS {_sqlite_ident(col)}'
    return _sqlite_ident(col)


def _build_pm_table_column_layout(
    vendor: str,
    technology: str,
    all_cols: list[str],
    resolved_cell_col: str | None,
    resolved_time_col: str | None,
) -> tuple[list[str], list[str]]:
    """
    Legacy pm-table column order: timestamp, cell_name, vendor static IDs, then KPIs.
    Empty legacy cell_name/timestamp slots are mapped to populated vendor-native axes.
    """
    static_cfg = _PM_STATIC_COLS.get(vendor, {}).get(technology, [])
    existing_static: list[str] = []
    for c in static_cfg:
        if c == 'cell_name':
            if resolved_cell_col:
                existing_static.append('cell_name')
        elif c == 'timestamp':
            if resolved_time_col:
                existing_static.append('timestamp')
        elif c in all_cols:
            existing_static.append(c)
    # Huawei hourly exports may include a separate Date column beside Time.
    # Daily exports use Date as the only time axis — do not duplicate it.
    if vendor == 'Huawei':
        for dc in ('Date', 'date'):
            if dc not in all_cols or dc in existing_static:
                break
            if resolved_time_col and _norm_col_name(resolved_time_col) == _norm_col_name(dc):
                break
            if 'timestamp' in existing_static:
                i = existing_static.index('timestamp') + 1
                existing_static.insert(i, dc)
            else:
                existing_static.insert(0, dc)
            break
    static_set = set(existing_static)
    axis_source_cols = {c for c in (resolved_cell_col, resolved_time_col) if c}
    kpi_cols = [
        c for c in all_cols
        if c not in _PM_EXCLUDE_COLS
        and c not in static_set
        and c not in _DUPLICATE_KPI_NAMES
        and c not in axis_source_cols
    ]
    ordered_cols = existing_static + kpi_cols
    return existing_static, ordered_cols


def _resolve_time_col_from_names(names: list[str]) -> str | None:
    low_to_real = {_norm_col_name(c): c for c in names}
    return next((low_to_real.get(a) for a in _TIME_COL_ALIASES if low_to_real.get(a)), None)


def _resolve_pm_table_sqlite(
    conn: sqlite3.Connection,
    vendor: str,
    technology: str,
    cell_name: str = "",
    preferred: str | None = None,
) -> str | None:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name DESC"
    ).fetchall()
    tables = [r[0] for r in rows]
    tech = '4G' if technology in ('4G-FDD', '4G-TDD') else technology
    candidates: list[str] = []
    for t in tables:
        tt = _table_technology(t)
        if tech and tt and tt != tech:
            continue
        c_col, t_col = _resolve_pm_axis_columns_sqlite(conn, t)
        if c_col and t_col:
            candidates.append(t)
    if preferred in candidates:
        candidates.insert(0, candidates.pop(candidates.index(preferred)))
    if not cell_name:
        return candidates[0] if candidates else None
    for t in candidates:
        c_col, _ = _resolve_pm_axis_columns_sqlite(conn, t)
        if not c_col:
            continue
        q = (
            f"SELECT 1 FROM {_sqlite_ident(t)} "
            f"WHERE LOWER(TRIM(CAST({_sqlite_ident(c_col)} AS TEXT))) = LOWER(TRIM(?)) "
            f"LIMIT 1"
        )
        try:
            if conn.execute(q, (cell_name,)).fetchone():
                return t
        except sqlite3.OperationalError:
            continue
    # Fallback: tolerate minor naming drift (suffix/prefix/noise) via contains match.
    for t in candidates:
        c_col, _ = _resolve_pm_axis_columns_sqlite(conn, t)
        if not c_col:
            continue
        q = (
            f"SELECT 1 FROM {_sqlite_ident(t)} "
            f"WHERE LOWER(TRIM(CAST({_sqlite_ident(c_col)} AS TEXT))) LIKE LOWER(TRIM(?)) "
            f"LIMIT 1"
        )
        try:
            if conn.execute(q, (f"%{cell_name}%",)).fetchone():
                return t
        except sqlite3.OperationalError:
            continue
    return candidates[0] if candidates else None


def _pragma_table_kpi_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    try:
        return [r[1] for r in conn.execute(f'PRAGMA table_info({_sqlite_ident(table)})').fetchall()
                if r[1] not in _FIXED_COLS]
    except sqlite3.OperationalError:
        return []


def _nonnull_columns_via_aggregate(conn: sqlite3.Connection, table: str, cols: list[str]) -> set[str] | None:
    """
    Columns with at least one non-NULL (single full-table scan).
    Returns None if SQLite rejects the statement (too many expressions / bad names).
    """
    if not cols:
        return set()
    t = _sqlite_ident(table)
    counts_sql = ', '.join(
        f'SUM(CASE WHEN {_sqlite_ident(c)} IS NOT NULL THEN 1 ELSE 0 END)'
        for c in cols
    )
    try:
        row = conn.execute(f'SELECT {counts_sql} FROM {t}').fetchone()
    except sqlite3.OperationalError:
        return None
    if not row:
        return set()
    return {c for c, cnt in zip(cols, row) if cnt and cnt > 0}


def _nonnull_columns_via_sample(
    conn: sqlite3.Connection,
    table: str,
    cols: list[str],
    *,
    limit: int = 800,
    chunk: int = 40,
) -> set[str]:
    """
    Find KPI columns with values by reading only the first ``limit`` rows, a few
    columns per SELECT. Nokia 4G exports can have hundreds of headers — one giant
    aggregate often hits SQLite limits or pathological parse cost.
    """
    if not cols:
        return set()
    t = _sqlite_ident(table)
    good: set[str] = set()
    for i in range(0, len(cols), chunk):
        part = cols[i : i + chunk]
        col_sql = ', '.join(_sqlite_ident(c) for c in part)
        try:
            cur = conn.execute(f'SELECT {col_sql} FROM {t} LIMIT ?', (limit,))
        except sqlite3.OperationalError:
            continue
        for row in cur:
            for c, v in zip(part, row):
                if v is not None and str(v).strip() != '':
                    good.add(c)
    return good


def _looks_like_merged_netact_header(col: str) -> bool:
    """True when a DB column name is several KPI labels concatenated (bad CSV delimiter on ingest)."""
    s = str(col)
    return ';' in s and s.count(';') >= 3 and len(s) > 80


def _kpi_columns_for_sqlite_table(conn: sqlite3.Connection, table: str) -> list[str]:
    """
    KPI column names for one SQLite PM table.
    Uses a bounded aggregate when the schema is modest; otherwise samples rows.
    Falls back to full non-id schema so the KPI picker works even for empty tables.
    """
    cols = _pragma_table_kpi_columns(conn, table)
    if not cols:
        return []

    try:
        max_agg = int(os.environ.get('PM_KPI_AGG_MAX_COLS', '96'))
    except ValueError:
        max_agg = 96

    good: set[str] = set()
    if len(cols) <= max_agg:
        via = _nonnull_columns_via_aggregate(conn, table, cols)
        if via is not None:
            good = via

    if not good:
        good = _nonnull_columns_via_sample(conn, table, cols)

    out = sorted(good) if good else sorted(cols)
    sane = [c for c in out if not _looks_like_merged_netact_header(c)]
    return sane if sane else out


def _get_pm_cols(db_path, technology=None):
    """
    Return KPI column names that contain actual numeric data.
    Scans all per-technology tables (or a single one when technology is given).
    """
    from modules.sync.pm_processor import huawei_pm_kpi_tables, huawei_table_matches_technology

    result = set()
    if _is_huawei_pm_db(db_path):
        tables = huawei_pm_kpi_tables(db_path)
        if technology:
            tables = [t for t in tables if huawei_table_matches_technology(t, technology)]

        try:
            conn = sqlite3.connect(db_path, timeout=30)
            for table in tables:
                try:
                    result.update(_kpi_columns_for_sqlite_table(conn, table))
                except sqlite3.OperationalError:
                    continue
            conn.close()
        except Exception:
            pass
        return _drop_duplicate_kpis(sorted(result))

    techs = [technology] if technology else PM_TECHNOLOGIES
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        for tech in techs:
            table = pm_table_name(tech)
            try:
                result.update(_kpi_columns_for_sqlite_table(conn, table))
            except sqlite3.OperationalError:
                continue
        conn.close()
    except Exception:
        pass
    return _drop_duplicate_kpis(sorted(result))


def _pm_extra_trend_time_columns(conn, table: str) -> str:
    """
    Extra SELECT columns for trend rows (Huawei files often keep a literal ``Date`` column
    for display while ``timestamp`` drives SQL ordering).
    """
    try:
        names = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
    except sqlite3.OperationalError:
        return ''
    if 'Date' in names:
        return ', "Date"'
    if 'date' in names:
        return ', "date"'
    return ''


def _load_pm_cols_for_table(db_path, table):
    """Return non-empty KPI columns for a specific table (uncached)."""
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        try:
            return _kpi_columns_for_sqlite_table(conn, table)
        finally:
            conn.close()
    except Exception:
        return []


def _get_pm_cols_for_table(db_path, table):
    """Cached KPI column list for trend / discovery endpoints."""
    key = _pm_cols_cache_key(db_path, table)
    item = _KPI_COLS_CACHE.get(key)
    if item:
        expires_at, cols = item
        if expires_at >= time.time():
            return cols
        _KPI_COLS_CACHE.pop(key, None)
    cols = _load_pm_cols_for_table(db_path, table)
    _KPI_COLS_CACHE[key] = (time.time() + _KPI_COLS_CACHE_TTL_SEC, cols)
    return cols


def _pm_conn(vendor=None, scope: str = 'hourly'):
    """
    Open metadata.db and ATTACH the right PM db(s).
    Returns (conn, pm_alias_or_None).
    """
    conn = sqlite3.connect(METADATA_DB, timeout=15)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.row_factory = sqlite3.Row

    if vendor is None or (isinstance(vendor, str) and not str(vendor).strip()):
        conn.execute(f"ATTACH DATABASE '{_pm_db_for_vendor('Nokia', scope)}'  AS nokia_pm")
        conn.execute(f"ATTACH DATABASE '{_pm_db_for_vendor('Huawei', scope)}' AS huawei_pm")
        return conn, None
    nv = _norm_vendor_for_pm(vendor)
    if nv == 'Nokia':
        conn.execute(f"ATTACH DATABASE '{_pm_db_for_vendor('Nokia', scope)}'  AS pm")
        return conn, 'pm'
    conn.execute(f"ATTACH DATABASE '{_pm_db_for_vendor('Huawei', scope)}' AS pm")
    return conn, 'pm'


def _build_pm_union(alias, db_path, technology=None):
    """
    Build UNION ALL subqueries across per-technology tables.

    Returns (data_sql, max_sql) where:
      data_sql — full UNION ALL with all KPI columns (for LEFT JOIN)
      max_sql  — minimal UNION ALL with just cell_name + timestamp (for MAX subquery)

    Both are None when no tables have data.
    """
    from modules.sync.pm_processor import huawei_pm_kpi_tables, huawei_table_matches_technology

    all_kpi = set()
    table_cols = {}  # {table: [cols_with_data]}

    if _is_huawei_pm_db(db_path):
        tables = huawei_pm_kpi_tables(db_path)
        if technology:
            tables = [t for t in tables if huawei_table_matches_technology(t, technology)]
    else:
        tables = [pm_table_name(t) for t in ([technology] if technology else PM_TECHNOLOGIES)]

    try:
        conn = sqlite3.connect(db_path, timeout=30)
        for table in tables:
            try:
                good = _kpi_columns_for_sqlite_table(conn, table)
                if good:
                    table_cols[table] = good
                    all_kpi.update(good)
            except sqlite3.OperationalError:
                continue
        conn.close()
    except Exception:
        return None, None

    if not table_cols:
        return None, None

    all_kpi_sorted = sorted(all_kpi)

    data_parts = []
    max_parts  = []
    for table, cols in table_cols.items():
        col_exprs = ', '.join(
            f'"{c}"' if c in cols else f'NULL AS "{c}"'
            for c in all_kpi_sorted
        )
        data_parts.append(
            f'SELECT cell_name, timestamp, {col_exprs} FROM {alias}."{table}"'
        )
        max_parts.append(
            f'SELECT cell_name, timestamp FROM {alias}."{table}"'
        )

    return ' UNION ALL '.join(data_parts), ' UNION ALL '.join(max_parts)


def _build_pm_union_minimal(alias, db_path, technology=None):
    """
    Lightweight UNION builder for cell listing:
    returns only ``cell_name`` + ``timestamp`` without scanning KPI columns.
    """
    from modules.sync.pm_processor import huawei_pm_kpi_tables, huawei_table_matches_technology

    if _is_huawei_pm_db(db_path):
        tables = huawei_pm_kpi_tables(db_path)
        if technology:
            tables = [t for t in tables if huawei_table_matches_technology(t, technology)]
    else:
        tables = [pm_table_name(t) for t in ([technology] if technology else PM_TECHNOLOGIES)]

    if not tables:
        return None, None

    parts = []
    for table in tables:
        parts.append(f'SELECT cell_name, timestamp FROM {alias}."{table}"')

    union_sql = ' UNION ALL '.join(parts)
    return union_sql, union_sql


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

@performance_bp.route('/performance')
@login_required
def performance_page():
    user = get_current_user()
    return render_template('performance.html', user=format_user(user))


# ---------------------------------------------------------------------------
# API: available KPI columns per vendor
# ---------------------------------------------------------------------------

@performance_bp.route('/api/performance/kpi_columns')
def get_kpi_columns():
    """
    KPI names with numeric data in PM DBs.
    Query params (optional):
      vendor — Nokia | Huawei — scope to that PM DB
      technology — 2G | 3G | 4G | 5G — scope to that table (pm_table_name)
    When both set → columns for that vendor/tech only.
    When neither → columns as union + legacy nokia/huawei arrays for clients.
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    vendor = (request.args.get('vendor') or '').strip()
    technology = (request.args.get('technology') or '').strip()
    data_scope = _normalize_data_scope(request.args.get('data_scope'))
    if vendor and str(vendor).strip().lower() not in ('nokia', 'huawei'):
        vendor = ''
    elif vendor:
        vendor = _norm_vendor_for_pm(vendor)
    allowed_tech = {'2G', '3G', '4G', '5G'}
    if technology and technology not in allowed_tech:
        technology = ''

    # Preferred source: standalone KPI catalog DB (raw/KPIs/kpi_headers.db).
    catalog_cols = _kpi_scope_from_catalog(vendor, technology)
    if catalog_cols:
        payload = {
            'success': True,
            'columns': catalog_cols,
            'source': 'kpi_catalog_db',
        }
        if vendor:
            payload['vendor'] = vendor
        if technology:
            payload['technology'] = technology
        if not vendor and not technology:
            payload['nokia'] = _kpi_scope_from_catalog('Nokia', '')
            payload['huawei'] = _kpi_scope_from_catalog('Huawei', '')
        return jsonify(payload)

    if _use_static_kpi_catalog():
        if vendor and technology:
            columns = _kpi_headers_static_for(vendor, technology)
            return jsonify({
                'success': True,
                'columns': columns,
                'vendor': vendor,
                'technology': technology,
                'source': 'static',
            })

        if vendor and not technology:
            techs = _VENDOR_TECH_SCOPE.get(vendor, [])
            cols = set()
            for tech in techs:
                cols.update(_kpi_headers_static_for(vendor, tech))
            return jsonify({'success': True, 'columns': sorted(cols), 'vendor': vendor, 'source': 'static'})

        if technology and not vendor:
            n = _kpi_headers_static_for('Nokia', technology)
            h = _kpi_headers_static_for('Huawei', technology)
            return jsonify({
                'success': True,
                'columns': sorted(set(n) | set(h)),
                'technology': technology,
                'source': 'static',
            })

        nokia = sorted({c for t in _VENDOR_TECH_SCOPE['Nokia'] for c in _kpi_headers_static_for('Nokia', t)})
        huawei = sorted({c for t in _VENDOR_TECH_SCOPE['Huawei'] for c in _kpi_headers_static_for('Huawei', t)})
        columns = sorted(set(nokia) | set(huawei))
        return jsonify({
            'success': True,
            'columns': columns,
            'nokia': nokia,
            'huawei': huawei,
            'source': 'static',
        })

    # Dynamic scan mode (default)
    if vendor and technology:
        db_path = _pm_db_for_vendor(vendor, data_scope)
        columns = _get_pm_cols(db_path, technology)
        return jsonify({
            'success': True,
            'columns': columns,
            'vendor': vendor,
            'technology': technology,
            'data_scope': data_scope,
            'source': 'dynamic',
        })

    if vendor and not technology:
        db_path = _pm_db_for_vendor(vendor, data_scope)
        columns = _get_pm_cols(db_path, None)
        return jsonify({'success': True, 'columns': columns, 'vendor': vendor, 'data_scope': data_scope, 'source': 'dynamic'})

    if technology and not vendor:
        n = _get_pm_cols(_pm_db_for_vendor('Nokia', data_scope), technology)
        h = _get_pm_cols(_pm_db_for_vendor('Huawei', data_scope), technology)
        columns = sorted(set(n) | set(h))
        return jsonify({'success': True, 'columns': columns, 'technology': technology, 'data_scope': data_scope, 'source': 'dynamic'})

    nokia = _get_pm_cols(_pm_db_for_vendor('Nokia', data_scope))
    huawei = _get_pm_cols(_pm_db_for_vendor('Huawei', data_scope))
    columns = sorted(set(nokia) | set(huawei))
    return jsonify({
        'success': True,
        'columns': columns,
        'nokia': nokia,
        'huawei': huawei,
        'data_scope': data_scope,
        'source': 'dynamic',
    })


@performance_bp.route('/api/performance/kpi_headers_map')
def get_kpi_headers_map():
    """
    Return KPI headers grouped by vendor+technology scope.
    This keeps frontend KPI selection strictly tied to a chosen scope.
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    if _use_static_kpi_catalog():
        return jsonify({'success': True, 'mapping': KPI_HEADERS_MAP, 'source': 'static'})

    # Preferred source: standalone KPI catalog DB.
    mapping_from_db = _kpi_mapping_from_catalog()
    if mapping_from_db:
        return jsonify({'success': True, 'mapping': mapping_from_db, 'source': 'kpi_catalog_db'})

    data_scope = _normalize_data_scope(request.args.get('data_scope'))
    mapping = {}
    for vendor, techs in _VENDOR_TECH_SCOPE.items():
        db_path = _pm_db_for_vendor(vendor, data_scope)
        for tech in techs:
            cols = _get_pm_cols(db_path, tech)
            mapping[f'{vendor}|{tech}'] = cols
    return jsonify({'success': True, 'mapping': mapping, 'data_scope': data_scope, 'source': 'dynamic'})


@performance_bp.route('/api/performance/kpi_mapping')
def get_kpi_mapping():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    payload = get_kpi_mapping_payload()
    payload['success'] = True
    return jsonify(payload)


@performance_bp.route('/api/performance/groups', methods=['GET'])
def get_cell_groups():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    uid = _user_id(user)
    req_vendor = (request.args.get('vendor') or '').strip()
    req_tech = _normalize_group_tech(request.args.get('technology') or '')
    data_scope = _normalize_data_scope(request.args.get('data_scope'))
    vendors = (
        [_norm_vendor_for_pm(req_vendor)]
        if str(req_vendor).strip().lower() in ('nokia', 'huawei')
        else ['Nokia', 'Huawei']
    )
    rows = []
    for vendor in vendors:
        conn = _groups_conn(vendor, data_scope)
        if _has_groups_schema(conn):
            try:
                where = ['(g.user_id = ? OR g.is_shared = 1)']
                params = [uid]
                if req_tech and _table_has_column(conn, 'group_cells', 'technology'):
                    where.append('(gc.technology = ? OR gc.technology = ?)')
                    params.extend([req_tech, _normalize_group_tech(req_tech)])
                v_rows = [dict(r) for r in conn.execute(
                    f'''
                    SELECT g.id, g.name, g.description, g.is_shared, g.updated_at, COUNT(gc.id) AS cell_count
                    FROM groups g
                    LEFT JOIN group_cells gc ON gc.group_id = g.id
                    WHERE {' AND '.join(where)}
                    GROUP BY g.id, g.name, g.description, g.is_shared, g.updated_at
                    ORDER BY g.updated_at DESC, g.id DESC
                    ''',
                    params,
                ).fetchall()]
                schema_rows = []
                for r in v_rows:
                    if req_tech and int(r.get('cell_count') or 0) <= 0:
                        continue
                    r['vendor'] = vendor
                    r['group_ref'] = f'{vendor}:{r["id"]}'
                    schema_rows.append(r)
                # If normalized groups schema has data, use it.
                # If it's empty (common in legacy hourly DBs), fall back to raw tables below.
                if schema_rows:
                    conn.close()
                    rows.extend(schema_rows)
                    continue
            except sqlite3.OperationalError:
                # Partial schema (legacy hourly DB) — fallback to raw imported tables below.
                pass

        # Fallback: raw imported group tables without groups/group_cells schema.
        for table, gcol, _ccol, _tcol, _scol in _raw_group_table_specs(conn):
            table_tech = _table_technology(table) or ''
            if req_tech and table_tech and req_tech != table_tech:
                continue
            sql = (
                f'SELECT {_sqlite_ident(gcol)} AS gname, COUNT(1) AS cell_count '
                f'FROM {_sqlite_ident(table)} '
                f'WHERE {_sqlite_ident(gcol)} IS NOT NULL AND TRIM(CAST({_sqlite_ident(gcol)} AS TEXT)) <> "" '
                f'GROUP BY {_sqlite_ident(gcol)} '
                f'ORDER BY gname'
            )
            for r in conn.execute(sql).fetchall():
                gname = str(r[0] or '').strip()
                if not gname:
                    continue
                rows.append({
                    'id': None,
                    'name': gname,
                    'description': f'Imported from {table}',
                    'is_shared': 1,
                    'updated_at': None,
                    'cell_count': int(r[1] or 0),
                    'vendor': vendor,
                    'group_ref': f'{vendor}:raw:{table}:{gname}',
                    'technology': table_tech or (req_tech or ''),
                })
        conn.close()
    rows.sort(key=lambda r: (str(r.get('updated_at') or ''), str(r.get('group_ref') or '')), reverse=True)
    return jsonify({'success': True, 'groups': rows})


@performance_bp.route('/api/performance/groups/<group_ref>/cell_keys', methods=['GET'])
def get_group_cell_keys(group_ref):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    uid = _user_id(user)
    vendor = (request.args.get('vendor') or '').strip()
    technology = _normalize_group_tech(request.args.get('technology') or '')
    data_scope = _normalize_data_scope(request.args.get('data_scope'))
    parts = group_ref.split(':', 3)
    if not parts or parts[0] not in ('Nokia', 'Huawei'):
        return jsonify({'error': 'Invalid group vendor'}), 400
    source_vendor = parts[0]

    conn = _groups_conn(source_vendor, data_scope)
    if len(parts) >= 4 and parts[1] == 'raw':
        table = parts[2]
        group_name = parts[3]
        specs = {t: (g, c, tc, sc) for t, g, c, tc, sc in _raw_group_table_specs(conn)}
        if table not in specs:
            conn.close()
            return jsonify({'error': 'Group source table not found'}), 404
        gcol, ccol, tcol, scol = specs[table]
        if not ccol:
            # Some vendor group exports (e.g. Nokia WS_NAME tables) have no per-cell column.
            conn.close()
            return jsonify({'success': True, 'cell_keys': []})
        where = [f'{_sqlite_ident(gcol)} = ?']
        params = [group_name]
        if technology:
            if tcol:
                where.append(f'({_sqlite_ident(tcol)} = ? OR {_sqlite_ident(tcol)} = ?)')
                params.extend([technology, _normalize_group_tech(technology)])
            elif (_table_technology(table) or '') != technology:
                conn.close()
                return jsonify({'success': True, 'cell_keys': []})
        sql = (
            f'SELECT {_sqlite_ident(ccol)} AS cell_name'
            + (f', {_sqlite_ident(tcol)} AS technology' if tcol else ', NULL AS technology')
            + (f', {_sqlite_ident(scol)} AS site_id' if scol else ', NULL AS site_id')
            + f' FROM {_sqlite_ident(table)} WHERE {" AND ".join(where)}'
        )
        rows = []
        for r in conn.execute(sql, params).fetchall():
            c_name = str(r[0] or '').strip()
            if not c_name:
                continue
            r_tech = str(r[1] or _table_technology(table) or '').strip()
            r_site = str(r[2] or '').strip()
            rows.append({
                'cell_key': '||'.join([source_vendor, r_tech, r_site, c_name]),
                'cell_name': c_name,
                'vendor': source_vendor,
                'technology': r_tech,
                'site_id': r_site,
            })
        conn.close()
        rows.sort(key=lambda x: (x.get('technology') or '', x.get('site_id') or '', x.get('cell_name') or ''))
        return jsonify({'success': True, 'cell_keys': rows})

    try:
        _source_vendor, raw_gid = group_ref.split(':', 1)
        group_id = int(raw_gid)
    except Exception:
        conn.close()
        return jsonify({'error': 'Invalid group reference'}), 400

    owner = conn.execute('SELECT user_id, is_shared FROM groups WHERE id = ?', (group_id,)).fetchone()
    if not owner:
        conn.close()
        return jsonify({'error': 'Group not found'}), 404
    if int(owner['user_id']) != int(uid) and int(owner['is_shared'] or 0) != 1:
        conn.close()
        return jsonify({'error': 'Forbidden'}), 403
    where = ['group_id = ?']
    params = [group_id]
    if vendor:
        where.append('vendor = ?')
        params.append(vendor)
    if technology:
        if _table_has_column(conn, 'group_cells', 'technology'):
            where.append('technology = ?')
            params.append(technology)
    rows = [dict(r) for r in conn.execute(
        f'''
        SELECT cell_key, cell_name, vendor, technology, site_id
        FROM group_cells
        WHERE {' AND '.join(where)}
        ORDER BY technology, vendor, site_id, cell_name
        ''',
        params,
    ).fetchall()]
    conn.close()
    return jsonify({'success': True, 'cell_keys': rows})


def _resolve_group_ref_cell_names(
    uid: int,
    group_ref: str,
    vendor: str,
    technology: str,
    data_scope: str,
) -> set[str]:
    out: set[str] = set()
    parts = (group_ref or '').split(':', 3)
    if not parts or parts[0] not in ('Nokia', 'Huawei'):
        return out
    source_vendor = parts[0]
    conn = _groups_conn(source_vendor, data_scope)
    try:
        if len(parts) >= 4 and parts[1] == 'raw':
            table = parts[2]
            group_name = parts[3]
            specs = {t: (g, c, tc, sc) for t, g, c, tc, sc in _raw_group_table_specs(conn)}
            if table not in specs:
                return out
            gcol, ccol, tcol, _scol = specs[table]
            if not ccol:
                return out
            where = [f'{_sqlite_ident(gcol)} = ?']
            params = [group_name]
            if technology:
                if tcol:
                    where.append(f'({_sqlite_ident(tcol)} = ? OR {_sqlite_ident(tcol)} = ?)')
                    params.extend([technology, _normalize_group_tech(technology)])
                elif (_table_technology(table) or '') != technology:
                    return out
            sql = f'''
                SELECT {_sqlite_ident(ccol)} AS cell_name
                FROM {_sqlite_ident(table)}
                WHERE {' AND '.join(where)}
            '''
            for r in conn.execute(sql, params).fetchall():
                n = str(r[0] or '').strip()
                if n:
                    out.add(n)
            return out

        try:
            _source_vendor, raw_gid = group_ref.split(':', 1)
            group_id = int(raw_gid)
        except Exception:
            return out

        owner = conn.execute('SELECT user_id, is_shared FROM groups WHERE id = ?', (group_id,)).fetchone()
        if not owner:
            return out
        if int(owner['user_id']) != int(uid) and int(owner['is_shared'] or 0) != 1:
            return out
        where = ['group_id = ?']
        params = [group_id]
        if vendor:
            where.append('vendor = ?')
            params.append(vendor)
        if technology and _table_has_column(conn, 'group_cells', 'technology'):
            where.append('technology = ?')
            params.append(technology)
        for r in conn.execute(
            f'''
            SELECT cell_name
            FROM group_cells
            WHERE {' AND '.join(where)}
            ''',
            params,
        ).fetchall():
            n = str(r[0] or '').strip()
            if n:
                out.add(n)
        return out
    finally:
        conn.close()


@performance_bp.route('/api/performance/group/trend', methods=['GET'])
def get_group_trend():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    group_ref = (request.args.get('group_ref') or '').strip()
    granularity = _normalize_granularity(request.args.get('granularity'))
    data_scope = _normalize_data_scope(request.args.get('data_scope'))
    requested_kpis = _requested_trend_kpi_names()
    if not group_ref:
        return jsonify({'error': 'group_ref is required'}), 400

    parts = group_ref.split(':', 3)
    if len(parts) < 4 or parts[0] not in ('Nokia', 'Huawei') or parts[1] != 'raw':
        return jsonify({'error': 'Only raw imported groups are supported'}), 400
    source_vendor, _raw_tag, table, group_name = parts
    conn = _groups_conn(source_vendor, data_scope)
    try:
        specs = {t: (g, c, tc, sc) for t, g, c, tc, sc in _raw_group_table_specs(conn)}
        if table not in specs:
            return jsonify({'error': 'Group source table not found'}), 404
        gcol, _ccol, _tcol, _scol = specs[table]
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info({_sqlite_ident(table)})').fetchall()]
        if not cols:
            return jsonify({'success': True, 'group': {'name': group_name, 'vendor': source_vendor}, 'trend': []})
        tcol = _resolve_time_col_from_names(cols)
        if not tcol:
            return jsonify({'success': True, 'group': {'name': group_name, 'vendor': source_vendor}, 'trend': []})

        kpi_exclude = {c.lower() for c in _FIXED_COLS}
        kpi_exclude.update({str(gcol).lower(), str(tcol).lower(), '_sync_row_hash', 'dn'})
        kpi_cols = [c for c in cols if str(c).lower() not in kpi_exclude and c not in _DUPLICATE_KPI_NAMES]
        if requested_kpis:
            allow = set(requested_kpis)
            kpi_cols = [c for c in kpi_cols if c in allow]

        select_cols = [f'{_sqlite_ident(tcol)} AS "timestamp"'] + [f'{_sqlite_ident(c)}' for c in kpi_cols]
        rows = [
            dict(r)
            for r in conn.execute(
                f'''
                SELECT {", ".join(select_cols)}
                FROM {_sqlite_ident(table)}
                WHERE LOWER(TRIM(CAST({_sqlite_ident(gcol)} AS TEXT))) = LOWER(TRIM(?))
                ORDER BY {_sqlite_ident(tcol)} ASC
                ''',
                (group_name,),
            ).fetchall()
        ]
        rows = _aggregate_trend_rows(rows, granularity)
        return jsonify({
            'success': True,
            'group': {'name': group_name, 'vendor': source_vendor, 'table': table},
            'trend': rows,
        })
    finally:
        conn.close()


@performance_bp.route('/api/performance/reports', methods=['GET'])
def get_performance_reports():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    _ensure_reports_table()
    uid = _user_id(user)
    conn = _reports_conn()
    rows = [dict(r) for r in execute_query(
        conn,
        '''
        SELECT id, report_name, report_config, updated_at
        FROM performance_reports
        WHERE user_id = ?
        ORDER BY updated_at DESC, id DESC
        ''',
        (uid,),
    ).fetchall()]
    conn.close()
    reports = []
    for r in rows:
        try:
            cfg = json.loads(r.get('report_config') or '{}')
        except Exception:
            cfg = {}
        reports.append({
            'id': r['id'],
            'name': r['report_name'],
            'config': cfg,
            'updated_at': r['updated_at'],
        })
    return jsonify({'success': True, 'reports': reports})


@performance_bp.route('/api/performance/reports', methods=['POST'])
def save_performance_report():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    config = data.get('config') or {}
    if not name:
        return jsonify({'error': 'Report name is required'}), 400
    _ensure_reports_table()
    uid = _user_id(user)
    cfg_text = json.dumps(config, ensure_ascii=False)
    conn = _reports_conn()
    row = execute_query(
        conn,
        'SELECT id FROM performance_reports WHERE user_id = ? AND report_name = ?',
        (uid, name),
    ).fetchone()
    if row:
        rid = int(row['id'])
        execute_query(
            conn,
            '''
            UPDATE performance_reports
            SET report_config = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            ''',
            (cfg_text, rid),
        )
    else:
        cur = conn.cursor()
        cur.execute(
            '''
            INSERT INTO performance_reports (user_id, report_name, report_config)
            VALUES (?,?,?)
            ''',
            (uid, name, cfg_text),
        )
        rid = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'id': rid, 'name': name})


@performance_bp.route('/api/performance/reports/<int:report_id>', methods=['DELETE'])
def delete_performance_report(report_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    _ensure_reports_table()
    uid = _user_id(user)
    conn = _reports_conn()
    cur = execute_query(conn, 'DELETE FROM performance_reports WHERE id = ? AND user_id = ?', (report_id, uid))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    if not deleted:
        return jsonify({'error': 'Report not found'}), 404
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# API: filter options
# ---------------------------------------------------------------------------

@performance_bp.route('/api/performance/filters', methods=['GET'])
def get_filters():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    conn = _meta_conn()
    union_sql = perf_per_tech_union_sql()
    raw_sites = [dict(r) for r in _meta_exec(conn, f'''
        SELECT DISTINCT s.site_id, s.site_name, s.vendor, s.latitude, s.longitude
        FROM ({union_sql}) v
        JOIN sites s ON s.site_id = v.site_id
        ORDER BY s.site_name
    ''').fetchall()]
    area_index = _build_site_area_index(conn)
    conn.close()

    # Derive cluster/area from site_id (same logic as network map)
    cluster_set = set()
    area_pairs  = set()      # (cluster, area)
    sites = []
    for s in raw_sites:
        cluster, area = area_index.get(str(s['site_id']), _derive_cluster_area(s['site_id']))
        s['cluster'] = cluster
        s['area']    = area
        sites.append(s)
        if cluster is not None:
            cluster_set.add(cluster)
        if area:
            area_pairs.add((cluster, area))

    clusters = sorted(cluster_set)
    areas    = [{'cluster': c, 'area': a} for c, a in sorted(area_pairs)]

    return jsonify({'success': True, 'clusters': clusters, 'areas': areas, 'sites': sites})


# ---------------------------------------------------------------------------
# API: cells list with latest KPI snapshot
# ---------------------------------------------------------------------------

@performance_bp.route('/api/performance/cells', methods=['GET'])
def get_cells():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    vendor     = request.args.get('vendor', '')
    technology = request.args.get('technology', '')
    site_id    = request.args.get('site_id', '')
    cluster    = request.args.get('cluster', '')
    area       = request.args.get('area', '')
    data_scope = _normalize_data_scope(request.args.get('data_scope'))
    cache_key = _cell_cache_key(
        vendor,
        technology,
        site_id,
        cluster,
        area,
        _pm_data_version_token(vendor if vendor else "", include_metadata=True, scope=data_scope),
    )
    cached_cells = _cell_cache_get(cache_key)
    if cached_cells is not None:
        return jsonify({'success': True, 'cells': cached_cells, 'cached': True})

    where  = ["1=1"]
    params = []

    if vendor:
        where.append("LOWER(TRIM(COALESCE(v.vendor, ''))) = LOWER(TRIM(?))")
        params.append(vendor)
    if technology:
        if technology == '4G':
            where.append("(v.technology = '4G-FDD' OR v.technology = '4G-TDD')")
        else:
            where.append('v.technology = ?')
            params.append(technology)
    if site_id:
        where.append('v.site_id = ?')
        params.append(site_id)

    meta = _meta_conn()
    area_index = _build_site_area_index(meta)

    # cluster / area filtering: derive/infer from site_id, then filter by matching site_ids
    if cluster or area:
        all_sites = [dict(r) for r in _meta_exec(
            meta,
            "SELECT site_id FROM sites WHERE site_id IS NOT NULL",
        ).fetchall()]
        matching_ids = []
        for s in all_sites:
            c_num, a_name = area_index.get(str(s['site_id']), _derive_cluster_area(s['site_id']))
            if cluster and str(c_num) != str(cluster):
                continue
            if area and a_name != area:
                continue
            matching_ids.append(s['site_id'])
        if matching_ids:
            placeholders = ','.join(['?'] * len(matching_ids))
            where.append(f'v.site_id IN ({placeholders})')
            params.extend(matching_ids)
        else:
            meta.close()
            # No sites match — return empty
            return jsonify({'success': True, 'cells': []})
    meta.close()

    where_sql = ' AND '.join(where)
    union_sql = perf_per_tech_union_sql_with_activity()

    conn, _pm_alias = _pm_conn(vendor if vendor else None, scope=data_scope)

    try:
        # Fast path for cell tree loading:
        # return metadata-driven objects only (no PM latest timestamp join).
        # The UI does not use kpi_ts for rendering the cell tree.
        sql = f'''
            SELECT
                v.cell_name AS cell_id,
                v.cell_name, v.technology, v.vendor,
                v.frequency_band, v.azimuth, v.pci,
                v.activity_status,
                st.site_id, st.site_name, st.latitude, st.longitude,
                NULL AS kpi_ts
            FROM ({union_sql}) v
            LEFT JOIN sites st ON v.site_id = st.site_id
            WHERE {where_sql}
            ORDER BY st.site_name, v.cell_name
        '''
        rows = [dict(r) for r in _meta_exec(conn, sql, params).fetchall()]

    except Exception:
        # PM db doesn't exist yet (first run before any sync)
        rows = [dict(r) for r in _meta_exec(conn, f'''
            SELECT
                v.cell_name AS cell_id,
                v.cell_name, v.technology, v.vendor,
                v.frequency_band, v.azimuth, v.pci,
                v.activity_status,
                st.site_id, st.site_name,
                st.latitude, st.longitude, NULL AS kpi_ts
            FROM ({union_sql}) v
            LEFT JOIN sites st ON v.site_id = st.site_id
            WHERE {where_sql}
            ORDER BY st.site_name, v.cell_name
        ''', params).fetchall()]

    finally:
        conn.close()

    # Enrich each row with derived cluster / area + legacy ``status`` alias (network map parity).
    for row in rows:
        c_num, a_name = area_index.get(str(row.get('site_id')), _derive_cluster_area(row.get('site_id')))
        row['cluster'] = c_num
        row['area']    = a_name
        row['cell_key'] = '||'.join([
            str(row.get('vendor') or ''),
            str(row.get('technology') or ''),
            str(row.get('site_id') or ''),
            str(row.get('cell_name') or ''),
        ])
        if row.get('status') is None and row.get('activity_status') is not None:
            row['status'] = row['activity_status']

    _cell_cache_set(cache_key, rows)
    log_activity(_user_id(user), 'performance_view', 'Viewed performance cells list')
    return jsonify({'success': True, 'cells': rows, 'cached': False})


# ---------------------------------------------------------------------------
# API: time-series KPI trend for a single cell
# ---------------------------------------------------------------------------

@performance_bp.route('/api/performance/cell/<int:cell_id>/trend', methods=['GET'])
def get_cell_trend(cell_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    granularity = _normalize_granularity(request.args.get('granularity'))
    data_scope = _normalize_data_scope(request.args.get('data_scope'))

    meta_conn = _meta_conn()
    area_index = _build_site_area_index(meta_conn)
    cell = _meta_exec(meta_conn, '''
        SELECT c.cell_id, c.cell_name, c.technology, c.vendor,
               c.frequency_band, c.azimuth, c.mechanical_tilt, c.pci,
               st.site_id, st.site_name, st.latitude, st.longitude
        FROM cells c
        LEFT JOIN sites st ON c.site_id = st.site_id
        WHERE c.cell_id = ?
    ''', (cell_id,)).fetchone()
    meta_conn.close()

    if not cell:
        return jsonify({'error': 'Cell not found'}), 404

    cell      = dict(cell)
    cluster, area = area_index.get(str(cell.get('site_id')), _derive_cluster_area(cell.get('site_id')))
    cell['cluster'] = cluster
    cell['area']    = area
    vendor    = _norm_vendor_for_pm(cell.get('vendor') or 'Nokia')
    cell_name = cell['cell_name']
    cell_tech = cell.get('technology', '4G')
    pm_db     = _pm_db_for_vendor(vendor, data_scope)
    if vendor == 'Huawei':
        from modules.sync.pm_processor import huawei_pm_table_for_cell

        table = huawei_pm_table_for_cell(cell_name, cell_tech, pm_db)
    else:
        table = pm_table_name(cell_tech)

    requested_kpis = _requested_trend_kpi_names()
    trend_cache_key = _trend_cache_key(
        "cell_id",
        str(cell_id),
        str(vendor or ""),
        str(table or ""),
        0,
        granularity,
        requested_kpis,
        _pm_data_version_token(vendor or "", include_metadata=True, scope=data_scope),
    )
    cached_trend = _trend_cache_get(trend_cache_key)
    if cached_trend is not None:
        return jsonify({'success': True, 'cell': cell, 'trend': cached_trend, 'cached': True})

    trend = []
    try:
        if table:
            pm_conn = sqlite3.connect(pm_db)
            pm_conn.row_factory = sqlite3.Row
            table = _resolve_pm_table_sqlite(pm_conn, str(vendor or ''), str(cell_tech or ''), cell_name, table)
            if table:
                cell_col, time_col = _resolve_pm_axis_columns_sqlite(pm_conn, table)
                full_kpi = _get_pm_cols_for_table(pm_db, table)
                kpi_cols = _trend_kpi_columns(full_kpi, requested_kpis)
            else:
                cell_col, time_col = None, None
            if not table or not cell_col or not time_col:
                trend = []
            else:
                extra_time = _pm_extra_trend_time_columns(pm_conn, table)
                base_cols = (
                    f'{_sqlite_ident(cell_col)} AS "cell_name", '
                    f'{_sqlite_ident(time_col)} AS "timestamp", '
                    f'{_sqlite_text_lit(time_col)} AS "__time_source"'
                )
                if kpi_cols:
                    col_list = base_cols + extra_time + ', ' + ', '.join(f'"{c}"' for c in kpi_cols)
                else:
                    col_list = base_cols + extra_time

                trend = [dict(r) for r in pm_conn.execute(f'''
                    SELECT {col_list}
                    FROM "{table}"
                    WHERE LOWER(TRIM(CAST({_sqlite_ident(cell_col)} AS TEXT))) = LOWER(TRIM(?))
                    ORDER BY {_sqlite_ident(time_col)} ASC
                ''', (cell_name,)).fetchall()]
                if not trend:
                    trend = [dict(r) for r in pm_conn.execute(f'''
                        SELECT {col_list}
                        FROM "{table}"
                        WHERE LOWER(TRIM(CAST({_sqlite_ident(cell_col)} AS TEXT))) LIKE LOWER(TRIM(?))
                        ORDER BY {_sqlite_ident(time_col)} ASC
                    ''', (f'%{cell_name}%',)).fetchall()]
                _log_trend_time_parse_sample(
                    current_app.logger,
                    endpoint='get_cell_trend',
                    vendor=str(vendor),
                    table=str(table),
                    time_col=str(time_col),
                    rows=trend,
                    granularity=granularity,
                )
                current_app.logger.info(
                    "get_cell_trend(cell_id=%s) vendor=%s table=%s cell_col=%s time_col=%s rows=%s",
                    cell_id, vendor, table, cell_col, time_col, len(trend)
                )
            pm_conn.close()
    except Exception:
        current_app.logger.exception('get_cell_trend: PM query failed cell_id=%s', cell_id)
        trend = []

    trend = _aggregate_trend_rows(trend, granularity)
    _trend_cache_set(trend_cache_key, trend)
    return jsonify({'success': True, 'cell': cell, 'trend': trend, 'cached': False})


@performance_bp.route('/api/performance/cell/trend', methods=['GET'])
def get_cell_trend_by_name():
    """Raw-cell trend endpoint keyed by cell_name (from per-tech metadata tables)."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    cell_name = request.args.get('cell_name', '').strip()
    technology = request.args.get('technology', '').strip()
    site_id = request.args.get('site_id', '').strip()
    vendor = request.args.get('vendor', '').strip()
    if not cell_name:
        return jsonify({'error': 'cell_name is required'}), 400
    granularity = _normalize_granularity(request.args.get('granularity'))
    data_scope = _normalize_data_scope(request.args.get('data_scope'))

    meta_conn = _meta_conn()
    area_index = _build_site_area_index(meta_conn)
    union_sql = perf_per_tech_union_sql()
    where = ['v.cell_name = ?']
    params = [cell_name]
    if technology:
        where.append('v.technology = ?')
        params.append(technology)
    if site_id:
        where.append('CAST(v.site_id AS TEXT) = ?')
        params.append(site_id)
    if vendor:
        where.append('v.vendor = ?')
        params.append(vendor)

    cell = _meta_exec(meta_conn, f'''
        SELECT
            v.cell_name AS cell_id,
            v.cell_name, v.technology, v.vendor,
            v.frequency_band, v.azimuth, v.pci,
            st.site_id, st.site_name, st.latitude, st.longitude
        FROM ({union_sql}) v
        LEFT JOIN sites st ON st.site_id = v.site_id
        WHERE {' AND '.join(where)}
        LIMIT 1
    ''', params).fetchone()
    meta_conn.close()
    if not cell:
        return jsonify({'error': 'Cell not found'}), 404

    cell = dict(cell)
    cluster, area = area_index.get(str(cell.get('site_id')), _derive_cluster_area(cell.get('site_id')))
    cell['cluster'] = cluster
    cell['area'] = area

    vendor = _norm_vendor_for_pm(cell.get('vendor') or 'Nokia')
    tech = cell.get('technology', '4G')
    pm_db = _pm_db_for_vendor(vendor, data_scope)
    pm_tech = '4G' if tech in ('4G-FDD', '4G-TDD') else tech
    if vendor == 'Huawei':
        from modules.sync.pm_processor import huawei_pm_table_for_cell

        table = huawei_pm_table_for_cell(cell_name, pm_tech, pm_db)
    else:
        table = pm_table_name(pm_tech)

    requested_kpis = _requested_trend_kpi_names()
    trend_cache_key = _trend_cache_key(
        "cell_name",
        "||".join([str(cell_name), str(technology), str(site_id)]),
        str(vendor or ""),
        str(table or ""),
        0,
        granularity,
        requested_kpis,
        _pm_data_version_token(vendor or "", include_metadata=True, scope=data_scope),
    )
    cached_trend = _trend_cache_get(trend_cache_key)
    if cached_trend is not None:
        return jsonify({'success': True, 'cell': cell, 'trend': cached_trend, 'cached': True})

    trend = []
    try:
        if table:
            pm_conn = sqlite3.connect(pm_db)
            pm_conn.row_factory = sqlite3.Row
            table = _resolve_pm_table_sqlite(pm_conn, str(vendor or ''), str(pm_tech or ''), cell_name, table)
            if table:
                cell_col, time_col = _resolve_pm_axis_columns_sqlite(pm_conn, table)
                full_kpi = _get_pm_cols_for_table(pm_db, table)
                kpi_cols = _trend_kpi_columns(full_kpi, requested_kpis)
            else:
                cell_col, time_col = None, None
            if not table or not cell_col or not time_col:
                trend = []
            else:
                extra_time = _pm_extra_trend_time_columns(pm_conn, table)
                col_list = (
                    f'{_sqlite_ident(cell_col)} AS "cell_name", '
                    f'{_sqlite_ident(time_col)} AS "timestamp", '
                    f'{_sqlite_text_lit(time_col)} AS "__time_source"'
                    + extra_time
                    + (', ' + ', '.join(f'"{c}"' for c in kpi_cols) if kpi_cols else '')
                )
                trend = [dict(r) for r in pm_conn.execute(f'''
                    SELECT {col_list}
                    FROM "{table}"
                    WHERE LOWER(TRIM(CAST({_sqlite_ident(cell_col)} AS TEXT))) = LOWER(TRIM(?))
                    ORDER BY {_sqlite_ident(time_col)} ASC
                ''', (cell_name,)).fetchall()]
                if not trend:
                    trend = [dict(r) for r in pm_conn.execute(f'''
                        SELECT {col_list}
                        FROM "{table}"
                        WHERE LOWER(TRIM(CAST({_sqlite_ident(cell_col)} AS TEXT))) LIKE LOWER(TRIM(?))
                        ORDER BY {_sqlite_ident(time_col)} ASC
                    ''', (f'%{cell_name}%',)).fetchall()]
                _log_trend_time_parse_sample(
                    current_app.logger,
                    endpoint='get_cell_trend_by_name',
                    vendor=str(vendor),
                    table=str(table),
                    time_col=str(time_col),
                    rows=trend,
                    granularity=granularity,
                )
                current_app.logger.info(
                    "get_cell_trend_by_name(cell=%r vendor=%r tech=%r table=%s cell_col=%s time_col=%s rows=%s",
                    cell_name, vendor, pm_tech, table, cell_col, time_col, len(trend)
                )
            pm_conn.close()
    except Exception:
        current_app.logger.exception(
            'get_cell_trend_by_name: PM query failed cell_name=%r vendor=%r',
            cell_name,
            vendor,
        )
        trend = []

    trend = _aggregate_trend_rows(trend, granularity)
    _trend_cache_set(trend_cache_key, trend)
    return jsonify({'success': True, 'cell': cell, 'trend': trend, 'cached': False})


# ---------------------------------------------------------------------------
# API: PM raw data table (paginated, with static identifier columns)
# ---------------------------------------------------------------------------

@performance_bp.route('/api/performance/pm-table')
def get_pm_table():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    vendor     = request.args.get('vendor', '')
    technology = request.args.get('technology', '')
    search     = request.args.get('search', '').strip()
    scoped_cell_names = [str(x).strip() for x in request.args.getlist('cell_name') if str(x).strip()]
    scoped_group_refs = [str(x).strip() for x in request.args.getlist('group_ref') if str(x).strip()]
    page       = request.args.get('page', 1, type=int)
    page_size  = min(request.args.get('page_size', 100, type=int), 500)
    data_scope = _normalize_data_scope(request.args.get('data_scope'))

    if str(vendor or '').strip().lower() not in ('nokia', 'huawei'):
        return jsonify({'error': 'Vendor must be Nokia or Huawei'}), 400
    vendor = _norm_vendor_for_pm(vendor)
    if not technology:
        return jsonify({'error': 'Technology is required'}), 400
    uid = _user_id(user)

    # -------------------------------------------------------------------
    # Group-scope table mode:
    # If a group is selected, table output must show group rows (not per-cell PM rows).
    # -------------------------------------------------------------------
    if scoped_group_refs:
        def _pick_group_time_col(cols: list[str]) -> str | None:
            low_to_real = {_norm_col_name(c): c for c in cols}
            for alias in _TIME_COL_ALIASES:
                real = low_to_real.get(alias)
                if real:
                    return real
            return None

        all_rows: list[dict] = []
        merged_cols: list[str] = []
        seen_cols: set[str] = set()

        for gref in scoped_group_refs:
            parts = gref.split(':', 3)
            if not parts or parts[0] not in ('Nokia', 'Huawei'):
                continue
            source_vendor = parts[0]
            conn_g = _groups_conn(source_vendor, data_scope)
            try:
                # Raw imported groups carry the actual KPI table rows.
                if len(parts) >= 4 and parts[1] == 'raw':
                    table = parts[2]
                    group_name = parts[3]
                    specs = {t: (g, c, tc, sc) for t, g, c, tc, sc in _raw_group_table_specs(conn_g)}
                    if table not in specs:
                        continue
                    gcol, _ccol, tcol, _scol = specs[table]
                    cols = [r[1] for r in conn_g.execute(f'PRAGMA table_info({_sqlite_ident(table)})').fetchall()]
                    if not cols:
                        continue
                    for c in cols:
                        if c not in seen_cols:
                            seen_cols.add(c)
                            merged_cols.append(c)
                    for extra in ('group_name', 'group_ref', 'vendor'):
                        if extra not in seen_cols:
                            seen_cols.add(extra)
                            merged_cols.append(extra)

                    base_where = [f'LOWER(TRIM(CAST({_sqlite_ident(gcol)} AS TEXT))) = LOWER(TRIM(?))']
                    base_params = [group_name]
                    where = list(base_where)
                    params = list(base_params)
                    applied_tech_filter = False
                    if technology:
                        if tcol:
                            where.append(f'({_sqlite_ident(tcol)} = ? OR {_sqlite_ident(tcol)} = ?)')
                            params.extend([technology, _normalize_group_tech(technology)])
                            applied_tech_filter = True
                        elif (_table_technology(table) or '') not in ('', technology):
                            # Table doesn't match selected technology by name, skip this raw source.
                            continue
                    sql = f'''SELECT * FROM {_sqlite_ident(table)} WHERE {' AND '.join(where)}'''
                    rows = [dict(r) for r in conn_g.execute(sql, params).fetchall()]
                    # Be tolerant like chart flow: if tech-filtered query produced nothing,
                    # retry by group only so table still reflects queried group rows.
                    if not rows and applied_tech_filter:
                        sql = f'''SELECT * FROM {_sqlite_ident(table)} WHERE {' AND '.join(base_where)}'''
                        rows = [dict(r) for r in conn_g.execute(sql, base_params).fetchall()]
                    for r in rows:
                        r['group_name'] = group_name
                        r['group_ref'] = gref
                        r['vendor'] = source_vendor
                        all_rows.append(r)
                    continue

                # Normalized groups schema does not include KPI rows, so expose group metadata rows.
                try:
                    _src_vendor, raw_gid = gref.split(':', 1)
                    gid = int(raw_gid)
                except Exception:
                    continue
                owner = conn_g.execute('SELECT user_id, is_shared, name, updated_at FROM groups WHERE id = ?', (gid,)).fetchone()
                if not owner:
                    continue
                if int(owner['user_id']) != int(uid) and int(owner['is_shared'] or 0) != 1:
                    continue
                if 'group_name' not in seen_cols:
                    seen_cols.add('group_name')
                    merged_cols.append('group_name')
                for c in ('group_ref', 'vendor', 'updated_at'):
                    if c not in seen_cols:
                        seen_cols.add(c)
                        merged_cols.append(c)
                all_rows.append({
                    'group_name': owner['name'],
                    'group_ref': gref,
                    'vendor': source_vendor,
                    'updated_at': owner['updated_at'],
                })
            finally:
                conn_g.close()

        if search:
            s = search.lower()
            all_rows = [
                r for r in all_rows
                if any(s in str(v).lower() for v in r.values() if v is not None)
            ]

        tcol = _pick_group_time_col(merged_cols)
        if tcol:
            all_rows.sort(
                key=lambda r: (_parse_trend_ts(r.get(tcol)) is not None, _parse_trend_ts(r.get(tcol)) or datetime.min),
                reverse=True,
            )
        else:
            all_rows.sort(key=lambda r: str(r.get('group_name') or ''), reverse=False)

        total = len(all_rows)
        offset = (page - 1) * page_size
        page_rows = all_rows[offset:offset + page_size]

        static_cols = [c for c in ('group_name', 'vendor', 'group_ref') if c in merged_cols]
        ordered_cols = static_cols + [c for c in merged_cols if c not in static_cols]
        payload = {
            'success': True,
            'columns': ordered_cols,
            'static_cols': static_cols,
            'column_labels': {'group_name': 'Group', 'group_ref': 'Group Ref', 'vendor': 'Vendor'},
            'rows': page_rows,
            'total': total,
            'page': page,
            'page_size': page_size,
            'cell_label': 'Group',
            'cached': False,
        }
        return jsonify(payload)

    if scoped_group_refs:
        merged: set[str] = set(scoped_cell_names)
        for gref in scoped_group_refs:
            merged.update(_resolve_group_ref_cell_names(uid, gref, vendor, technology, data_scope))
        scoped_cell_names = sorted(merged)

    static_cfg = _PM_STATIC_COLS.get(vendor, {}).get(technology, [])
    cell_label = _PM_CELL_LABEL.get(vendor, {}).get(technology, 'Cell Name')
    ts_label   = 'Period Start' if vendor == 'Nokia' else 'Date'

    empty = {
        'success': True, 'columns': [], 'static_cols': [],
        'column_labels': {}, 'rows': [], 'total': 0,
        'page': page, 'page_size': page_size, 'cell_label': cell_label,
    }

    db_path = _pm_db_for_vendor(vendor, data_scope)
    table = None
    resolved_cell_col = None
    resolved_time_col = None
    try:
        pre_conn = sqlite3.connect(db_path, timeout=15)
        table = _resolve_pm_table_sqlite(pre_conn, vendor, technology, "", None)
        if table:
            resolved_cell_col, resolved_time_col = _resolve_pm_axis_columns_sqlite(pre_conn, table)
        pre_conn.close()
    except Exception:
        table = None
    if not table or not resolved_cell_col or not resolved_time_col:
        empty['cached'] = False
        return jsonify(empty)

    scoped_sig = '|'.join(sorted({n.lower() for n in scoped_cell_names}))
    group_sig = '|'.join(sorted({g.lower() for g in scoped_group_refs}))
    table_cache_key = _pm_table_cache_key(
        vendor,
        technology,
        table,
        f'{search}||{scoped_sig}||{group_sig}',
        page,
        page_size,
        _pm_data_version_token(vendor, include_metadata=False, scope=data_scope),
    )
    cached_table_payload = _pm_table_cache_get(table_cache_key)
    if cached_table_payload is not None:
        out = dict(cached_table_payload)
        out['cached'] = True
        return jsonify(out)

    try:
        conn     = sqlite3.connect(db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        all_cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]

        if not all_cols:
            conn.close()
            empty['cached'] = False
            return jsonify(empty)

        # Build column order: static first, then KPIs (legacy cell_name/timestamp slots).
        existing_static, ordered_cols = _build_pm_table_column_layout(
            vendor,
            technology,
            all_cols,
            resolved_cell_col,
            resolved_time_col,
        )
        col_select = ', '.join(
            _pm_table_select_col(
                c,
                resolved_cell_col=resolved_cell_col,
                resolved_time_col=resolved_time_col,
            )
            for c in ordered_cols
        )

        where_parts = ['1=1']
        params = []
        if search:
            where_parts.append(f'{_sqlite_ident(resolved_cell_col)} LIKE ?')
            params.append(f'%{search}%')
        if scoped_cell_names:
            placeholders = ','.join(['?'] * len(scoped_cell_names))
            where_parts.append(
                f'LOWER(TRIM(CAST({_sqlite_ident(resolved_cell_col)} AS TEXT))) IN ({placeholders})'
            )
            params.extend([n.lower() for n in scoped_cell_names])
        where_clause = ' AND '.join(where_parts)

        total  = conn.execute(
            f'SELECT COUNT(*) FROM "{table}" WHERE {where_clause}', params
        ).fetchone()[0]
        offset = (page - 1) * page_size
        rows   = conn.execute(f'''
            SELECT {col_select} FROM "{table}"
            WHERE  {where_clause}
            ORDER  BY {_sqlite_ident(resolved_time_col)} DESC
            LIMIT  ? OFFSET ?
        ''', params + [page_size, offset]).fetchall()
        conn.close()

        column_labels = {'timestamp': ts_label, 'cell_name': cell_label}
        for dc in ('Date', 'date'):
            if dc in ordered_cols:
                column_labels[dc] = 'Date'
                if 'timestamp' in ordered_cols:
                    column_labels['timestamp'] = 'Timestamp'
                break

        payload = {
            'success':       True,
            'columns':       ordered_cols,
            'static_cols':   existing_static,
            'column_labels': column_labels,
            'rows':          [dict(r) for r in rows],
            'total':         total,
            'page':          page,
            'page_size':     page_size,
            'cell_label':    cell_label,
        }
        _pm_table_cache_set(table_cache_key, payload)
        payload = dict(payload)
        payload['cached'] = False
        return jsonify(payload)

    except sqlite3.OperationalError:
        empty['cached'] = False
        return jsonify(empty)


# ---------------------------------------------------------------------------
# API: sync triggers (for admin panel)
# ---------------------------------------------------------------------------

@performance_bp.route('/api/sync/trigger/nokia', methods=['POST'])
def trigger_nokia():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    import threading
    from modules.sync.scheduler import trigger_nokia_pm_now
    threading.Thread(target=trigger_nokia_pm_now, daemon=True).start()
    return jsonify({'success': True, 'message': 'Nokia PM pull triggered.'})


@performance_bp.route('/api/sync/trigger/huawei', methods=['POST'])
def trigger_huawei():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    import threading
    from modules.sync.scheduler import trigger_huawei_pm_now
    threading.Thread(target=trigger_huawei_pm_now, daemon=True).start()
    return jsonify({'success': True, 'message': 'Huawei PM pull triggered.'})
