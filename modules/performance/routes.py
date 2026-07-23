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

from flask import Blueprint, request, jsonify, render_template, redirect, url_for, current_app, Response
from functools import wraps
from collections import defaultdict
from datetime import datetime, timedelta
import csv
import io
import sqlite3
import os
import sys
import json
import time
import threading
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
    PM_RETENTION_DAYS,
    DAILY_RETENTION_DAYS,
    PM_EXPORT_MAX_ROWS,
    PM_CHARTS_MAX_ROWS,
    pm_table_name,
)
from core.resource_limits import heavy_query_required
from db.runtime import apply_pm_read_pragmas
from core.site_area import (
    list_pm_partition_tables,
    preferred_pm_table,
    site_id_from_cell_name,
)
from db.runtime import connect_app, connect_metadata, execute_query
from database_enhanced import get_user_by_session, log_activity
from modules.sync.metadata_active_sql import (
    perf_per_tech_union_sql,
    perf_per_tech_union_sql_with_activity,
    perf_cell_source_sql_with_activity,
)
from .kpi_catalog import KPI_HEADERS_MAP
from .kpi_mapping import get_kpi_mapping_payload
from core.pm_timestamp import (
    PM_REPORT_DATE_COL,
    PM_REPORT_TIME_COL,
    format_pm_report_date,
    format_pm_report_time,
    format_pm_timestamp,
    parse_pm_datetime,
)

performance_bp = Blueprint(
    'performance', __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/performance/static',
)


def _meta_exec(conn, sql: str, params=()):
    """Run SQL on metadata or PM+metadata connection (SQLite ``.execute`` or Postgres via ``execute_query``)."""
    return execute_query(conn, sql, params or ())


_FIXED_COLS = {
    'id', 'cell_name', 'timestamp', 'Date', 'date', 'Time', 'PERIOD_START_TIME',
    PM_REPORT_DATE_COL, PM_REPORT_TIME_COL, '__time_source',
}
_VENDOR_TIME_COLS = {'Date', 'date', 'Time', 'PERIOD_START_TIME', 'period start time'}
# Match PRAGMA names after lower/strip (spaces kept); include spaced Nokia export headers.
_TIME_COL_ALIASES = (
    'timestamp',
    PM_REPORT_DATE_COL,
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


def _retention_days_for_scope(scope: str = 'hourly') -> int:
    s = _normalize_data_scope(scope)
    if s == 'daily':
        return max(1, int(DAILY_RETENTION_DAYS or 120))
    days = int(PM_RETENTION_DAYS or 14)
    return max(1, days) if days > 0 else 14


def _retention_hours_for_scope(scope: str = 'hourly') -> int:
    return _retention_days_for_scope(scope) * 24


def _parse_hours_param(raw, scope: str = 'hourly') -> int | None:
    """Return None for full retention window; otherwise clamp to scope retention."""
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s or s in ('full', 'all', 'retention'):
        return None
    try:
        h = int(float(s))
    except (TypeError, ValueError):
        return None
    max_h = _retention_hours_for_scope(scope)
    return max(1, min(h, max_h))


def _hours_from_request(scope: str | None = None) -> int | None:
    scope = scope or _normalize_data_scope(request.args.get('data_scope'))
    if _date_range_from_request(scope)[0] is not None:
        return None
    return _parse_hours_param(request.args.get('hours'), scope)


def _parse_range_datetime(raw, hour_raw=None, *, scope: str = 'hourly') -> datetime | None:
    s = str(raw or '').strip()
    if not s:
        return None
    dt = _parse_trend_ts(s)
    if dt is None and len(s) >= 10 and s[4] == '-':
        try:
            dt = datetime.strptime(s[:10], '%Y-%m-%d')
        except ValueError:
            dt = None
    if dt is None:
        return None
    if scope != 'daily':
        try:
            hh = int(hour_raw) if hour_raw is not None and str(hour_raw).strip() != '' else dt.hour
        except (TypeError, ValueError):
            hh = dt.hour
        hh = max(0, min(23, hh))
        dt = dt.replace(hour=hh, minute=0, second=0, microsecond=0)
    else:
        dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return dt


def _date_range_from_request(scope: str | None = None) -> tuple[datetime | None, datetime | None]:
    scope = scope or _normalize_data_scope(request.args.get('data_scope'))
    start = _parse_range_datetime(
        request.args.get('date_from'),
        request.args.get('date_from_hour'),
        scope=scope,
    )
    end = _parse_range_datetime(
        request.args.get('date_to'),
        request.args.get('date_to_hour'),
        scope=scope,
    )
    if start is None or end is None:
        return None, None
    if scope == 'daily':
        end = end.replace(hour=23, minute=59, second=59, microsecond=0)
    else:
        try:
            eh = int(request.args.get('date_to_hour')) if request.args.get('date_to_hour') not in (None, '') else end.hour
        except (TypeError, ValueError):
            eh = end.hour
        end = end.replace(hour=max(0, min(23, eh)), minute=59, second=59, microsecond=0)
    if end < start:
        start, end = end, start
    retention_days = _retention_days_for_scope(scope)
    earliest = datetime.now().replace(minute=0, second=0, microsecond=0) - timedelta(days=retention_days)
    if start < earliest:
        start = earliest
    return start, end


def _filter_trend_rows_by_range(
    rows: list[dict],
    start: datetime,
    end: datetime,
    granularity: str = 'hour',
) -> list[dict]:
    if not rows:
        return rows
    gran = (granularity or 'hour').lower()
    out = []
    for row in rows:
        ts_raw, prefer_dayfirst = _pick_trend_time_value(row, gran)
        dt = _parse_trend_ts(ts_raw, prefer_dayfirst=prefer_dayfirst)
        if dt is None:
            continue
        if start <= dt <= end:
            out.append(row)
    return out


def _resolved_time_frame(scope: str | None = None) -> tuple[int | None, str, datetime | None, datetime | None]:
    scope = scope or _normalize_data_scope(request.args.get('data_scope'))
    gran = 'day' if scope == 'daily' else 'hour'
    date_start, date_end = _date_range_from_request(scope)
    hours = _hours_from_request(scope)
    return hours, gran, date_start, date_end


def _time_frame_cache_token(scope: str | None = None) -> str:
    scope = scope or _normalize_data_scope(request.args.get('data_scope'))
    hours, _, date_start, date_end = _resolved_time_frame(scope)
    if date_start is not None and date_end is not None:
        return f'range:{format_pm_timestamp(date_start)}..{format_pm_timestamp(date_end)}'
    return f'hours:{hours if hours is not None else "full"}'


def _apply_time_frame_rows(
    rows: list[dict],
    hours: int | None,
    granularity: str = 'hour',
    date_start: datetime | None = None,
    date_end: datetime | None = None,
) -> list[dict]:
    if not rows:
        return rows
    if date_start is not None and date_end is not None:
        return _filter_trend_rows_by_range(rows, date_start, date_end, granularity)
    if hours is None:
        return rows
    return _filter_trend_rows_by_hours(rows, hours, granularity)


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


def _scope_from_pm_db(db_path: str) -> str:
    """Infer hourly/daily from a PM DB path (daily filenames/dirs contain 'daily')."""
    p = os.path.normpath(str(db_path or '')).replace('\\', '/').lower()
    if 'daily' in p:
        return 'daily'
    return 'hourly'


def _groups_db_for_vendor(vendor: str, scope: str = 'hourly') -> str:
    s = _normalize_data_scope(scope)
    if _norm_vendor_for_pm(vendor) == 'Huawei':
        return HUAWEI_GROUPS_DAILY_DB if s == 'daily' else HUAWEI_GROUPS_DB
    return NOKIA_GROUPS_DAILY_DB if s == 'daily' else NOKIA_GROUPS_DB


def _parse_trend_ts(val, prefer_dayfirst: bool | None = None):
    """Parse Huawei/Nokia PM time cells into naive datetime (canonical ISO via format_pm_timestamp)."""
    return parse_pm_datetime(val, prefer_dayfirst=prefer_dayfirst)


def _pick_trend_time_value(row: dict, granularity: str) -> tuple[object, bool | None]:
    """Pick row time from PrimeNet report columns; legacy vendor columns are last resort."""
    gran = (granularity or 'hour').lower()

    rd = row.get(PM_REPORT_DATE_COL)
    if rd is not None and str(rd).strip():
        rd_s = str(rd).strip()
        if gran == 'hour':
            rt = row.get(PM_REPORT_TIME_COL)
            if rt is not None and str(rt).strip():
                return f'{rd_s} {str(rt).strip()}', None
        else:
            return rd_s, None

    ts = row.get('timestamp')
    if ts is not None:
        s = str(ts).strip()
        if s and s.lower() not in ('nan', 'nat', 'none') and len(s) >= 10 and s[4] == '-':
            return ts, None

    source_col = str(row.get('__time_source') or '').strip().lower()
    if source_col in ('period_start_time', 'period start time'):
        v = row.get('timestamp')
        if v is not None and str(v).strip().lower() not in ('', 'nan', 'nat', 'none'):
            return v, False
    if source_col in ('date',):
        v = row.get('timestamp')
        if v is not None and str(v).strip().lower() not in ('', 'nan', 'nat', 'none'):
            return v, True

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
        if k in ('Date', 'date'):
            return v, True
        if k == 'PERIOD_START_TIME':
            return v, False
        if '/' in s and not (len(s) >= 10 and s[4] == '-'):
            return v, True
        if '.' in s and not (len(s) >= 10 and s[4] == '-'):
            return v, False
        return v, None
    return None, None


def _trend_row_sort_key(row: dict, granularity: str = 'hour') -> tuple:
    ts_raw, prefer_dayfirst = _pick_trend_time_value(row, granularity)
    dt = _parse_trend_ts(ts_raw, prefer_dayfirst=prefer_dayfirst)
    if dt is None:
        return (0, datetime.min)
    return (1, dt)


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
            'parsed_ts': format_pm_timestamp(dt) if dt else None,
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
    Output ``timestamp`` is always canonical ``YYYY-MM-DD HH:MM:SS``.
    """
    if not rows:
        return rows
    gran = (granularity or 'hour').lower()
    if gran not in ('hour', 'day', 'month'):
        gran = 'hour'

    def bucket_label(dt: datetime) -> str:
        if gran == 'hour':
            z = dt.replace(minute=0, second=0, microsecond=0)
            return format_pm_timestamp(z)
        if gran == 'day':
            return format_pm_timestamp(datetime(dt.year, dt.month, dt.day))
        return format_pm_timestamp(datetime(dt.year, dt.month, 1))

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
        ts_raw, prefer_dayfirst = _pick_trend_time_value(group[0], gran)
        dt = _parse_trend_ts(ts_raw, prefer_dayfirst=prefer_dayfirst)
        merged['timestamp'] = label
        if dt is not None:
            merged[PM_REPORT_DATE_COL] = format_pm_report_date(dt)
            if gran == 'hour':
                merged[PM_REPORT_TIME_COL] = format_pm_report_time(
                    dt.replace(minute=0, second=0, microsecond=0)
                )
        for raw_key in _VENDOR_TIME_COLS:
            merged.pop(raw_key, None)
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
_CELL_LIST_CACHE_TTL_SEC = 120
_TREND_CACHE = {}
_TREND_CACHE_TTL_SEC = 300
_TREND_CACHE_SCHEMA_VER = "v6"
_PM_TABLE_CACHE_SCHEMA_VER = "v5"
_PM_TABLE_CACHE = {}
_PM_TABLE_CACHE_TTL_SEC = 180
_PM_CELL_NAMES_CACHE = {}
_PM_CELL_NAMES_CACHE_TTL_SEC = 300
_PM_CELL_NAMES_CACHE_LOCK = threading.Lock()
_PM_CELL_NAMES_CACHE_INFLIGHT: set[str] = set()
_FILTERS_CACHE = {}
_FILTERS_CACHE_TTL_SEC = 180


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


_PM_EXPORT_MAX_ROWS = PM_EXPORT_MAX_ROWS
_PM_CHARTS_MAX_ROWS = PM_CHARTS_MAX_ROWS


def _pm_table_csv_response(
    columns: list[str],
    column_labels: dict[str, str],
    rows: list[dict],
    vendor: str,
    technology: str,
) -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator='\r\n')
    writer.writerow([column_labels.get(c, c) for c in columns])
    for row in rows:
        writer.writerow(['' if row.get(c) is None else row.get(c) for c in columns])
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'pm_{vendor}_{technology}_{ts}.csv'
    return Response(
        '\ufeff' + buf.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


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
    apply_pm_read_pragmas(conn)
    conn.row_factory = sqlite3.Row
    return conn


_PM_INDEX_ENSURED_PATHS: set[str] = set()
_PM_INDEX_ENSURE_LOCK = threading.Lock()
_PM_TABLE_META_CACHE: dict[str, dict] = {}


def _pm_table_meta_cache_key(db_path: str, vendor: str, technology: str) -> str:
    return '||'.join([
        os.path.abspath(str(db_path)),
        str(vendor or ''),
        str(technology or ''),
        _db_mtime_token(db_path),
    ])


def _resolve_pm_table_bundle(
    conn: sqlite3.Connection,
    db_path: str,
    vendor: str,
    technology: str,
    preferred: str | None = None,
) -> dict | None:
    data_scope = _scope_from_pm_db(db_path)
    key = _pm_table_meta_cache_key(db_path, vendor, technology) + f'||{preferred or ""}||{data_scope}'
    hit = _PM_TABLE_META_CACHE.get(key)
    if hit:
        return hit
    table = _resolve_pm_table_sqlite(
        conn, vendor, technology, '', preferred, scope=data_scope
    )
    if not table:
        return None
    cell_col, time_col = _resolve_pm_axis_columns_sqlite(conn, table)
    if not cell_col or not time_col:
        return None
    all_cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
    if not all_cols:
        return None
    existing_static, ordered_cols = _build_pm_table_column_layout(
        vendor, technology, all_cols, cell_col, time_col, scope=data_scope,
    )
    bundle = {
        'table': table,
        'cell_col': cell_col,
        'time_col': time_col,
        'existing_static': existing_static,
        'ordered_cols': ordered_cols,
    }
    _PM_TABLE_META_CACHE[key] = bundle
    return bundle


def _pm_table_output_columns(
    existing_static: list[str],
    ordered_cols: list[str],
    requested_kpis: list[str] | None,
    *,
    export_csv: bool,
    for_charts: bool,
) -> list[str]:
    if export_csv or for_charts:
        if requested_kpis:
            allowed = set(existing_static) | set(requested_kpis)
            return [c for c in ordered_cols if c in allowed]
        return ordered_cols
    if requested_kpis:
        allowed = set(existing_static) | set(requested_kpis)
        return [c for c in ordered_cols if c in allowed]
    return list(existing_static)


def _pm_table_cell_scope_sql(resolved_cell_col: str, scoped_cell_names: list[str]) -> tuple[str, list]:
    """Index-friendly cell filter (no LOWER/TRIM expression on the column)."""
    if not scoped_cell_names:
        return '', []
    placeholders = ','.join(['?'] * len(scoped_cell_names))
    clause = f'{_sqlite_ident(resolved_cell_col)} IN ({placeholders})'
    return clause, list(scoped_cell_names)


def _open_pm_db(db_path: str) -> sqlite3.Connection:
    """Open PM SQLite with read-friendly pragmas (large DBs on Windows)."""
    abs_path = os.path.normpath(os.path.abspath(db_path))
    with _PM_INDEX_ENSURE_LOCK:
        if abs_path not in _PM_INDEX_ENSURED_PATHS and os.path.isfile(abs_path):
            _PM_INDEX_ENSURED_PATHS.add(abs_path)
            try:
                from core.pm_indexes import ensure_pm_database
                ensure_pm_database(abs_path, analyze=False)
            except Exception:
                pass
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    apply_pm_read_pragmas(conn)
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


def _axis_column_sample_score(conn: sqlite3.Connection, table: str, col: str, *, sample: int = 64) -> int:
    """Cheap populated-ness score from the first rows (avoids full-table COUNT)."""
    try:
        rows = conn.execute(
            f'SELECT {_sqlite_ident(col)} FROM {_sqlite_ident(table)} LIMIT ?',
            (sample,),
        ).fetchall()
    except sqlite3.OperationalError:
        return 0
    score = 0
    for (val,) in rows:
        if val is None:
            continue
        if str(val).strip():
            score += 1
    return score


def _pick_time_column_from_aliases(
    conn: sqlite3.Connection,
    table: str,
    cols: list[str],
    aliases: tuple[str, ...],
) -> str | None:
    """Prefer canonical PrimeNet time columns in alias order (not vendor Date)."""
    low_to_real = {_norm_col_name(c): c for c in cols}
    for alias in aliases:
        real = low_to_real.get(alias)
        if real and _axis_column_sample_score(conn, table, real) > 0:
            return real
    return None


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
    return max(candidates, key=lambda c: _axis_column_sample_score(conn, table, c))


_PM_AXIS_COL_CACHE: dict[str, tuple[str | None, str | None]] = {}


def _resolve_pm_axis_columns_sqlite(conn: sqlite3.Connection, table: str) -> tuple[str | None, str | None]:
    cached = _PM_AXIS_COL_CACHE.get(table)
    if cached is not None:
        return cached
    try:
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info({_sqlite_ident(table)})').fetchall()]
    except sqlite3.OperationalError:
        _PM_AXIS_COL_CACHE[table] = (None, None)
        return None, None
    cell_col = _pick_axis_column_from_aliases(conn, table, cols, _CELL_COL_ALIASES)
    time_col = _pick_time_column_from_aliases(conn, table, cols, _TIME_COL_ALIASES)
    _PM_AXIS_COL_CACHE[table] = (cell_col, time_col)
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


def _pm_report_static_cols(scope: str) -> list[str]:
    if _normalize_data_scope(scope) == 'daily':
        return [PM_REPORT_DATE_COL]
    return [PM_REPORT_DATE_COL, PM_REPORT_TIME_COL]


def _build_pm_table_column_layout(
    vendor: str,
    technology: str,
    all_cols: list[str],
    resolved_cell_col: str | None,
    resolved_time_col: str | None,
    scope: str = 'hourly',
) -> tuple[list[str], list[str]]:
    """
    Legacy pm-table column order: report date/time, cell_name, vendor static IDs, then KPIs.
    Empty legacy cell_name/timestamp slots are mapped to populated vendor-native axes.
    """
    static_cfg = _PM_STATIC_COLS.get(vendor, {}).get(technology, [])
    report_static = _pm_report_static_cols(scope)
    existing_static: list[str] = []
    if any(c in all_cols for c in report_static):
        for c in report_static:
            if c in all_cols:
                existing_static.append(c)
    elif resolved_time_col:
        existing_static.append('timestamp')
    for c in static_cfg:
        if c in ('timestamp', PM_REPORT_DATE_COL, PM_REPORT_TIME_COL):
            continue
        if c == 'cell_name':
            if resolved_cell_col:
                existing_static.append('cell_name')
        elif c in all_cols:
            existing_static.append(c)
    static_set = set(existing_static)
    axis_source_cols = {c for c in (resolved_cell_col, resolved_time_col) if c}
    axis_source_cols.update(_VENDOR_TIME_COLS)
    kpi_cols = [
        c for c in all_cols
        if c not in _PM_EXCLUDE_COLS
        and c not in static_set
        and c not in _DUPLICATE_KPI_NAMES
        and c not in axis_source_cols
        and c not in ('timestamp', PM_REPORT_DATE_COL, PM_REPORT_TIME_COL)
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
    scope: str = 'hourly',
) -> str | None:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name DESC"
    ).fetchall()
    tables = [r[0] for r in rows]
    tech = '4G' if technology in ('4G-FDD', '4G-TDD') else technology
    data_scope = _normalize_data_scope(scope)
    base = pm_table_name(tech, data_scope) if tech else None
    if not preferred and cell_name:
        preferred = _preferred_pm_table_for_cell_name(technology, cell_name, data_scope)

    candidates: list[str] = []
    for t in tables:
        tt = _table_technology(t)
        if tech and tt and tt != tech:
            continue
        c_col, t_col = _resolve_pm_axis_columns_sqlite(conn, t)
        if c_col and t_col:
            candidates.append(t)

    def _prefer_first(name: str | None) -> None:
        if name and name in candidates:
            candidates.insert(0, candidates.pop(candidates.index(name)))

    # Prefer exact area table, then monotable, then remaining partitions.
    _prefer_first(base)
    if preferred:
        _prefer_first(preferred)
    if not cell_name:
        return candidates[0] if candidates else None

    needle = str(cell_name).strip()
    needle_l = needle.lower()

    def _table_has_cell(t: str) -> bool:
        c_col, _ = _resolve_pm_axis_columns_sqlite(conn, t)
        if not c_col:
            return False
        # Index-friendly equality first (area tables are keyed on vendor-native names).
        try:
            if conn.execute(
                f'SELECT 1 FROM {_sqlite_ident(t)} '
                f'WHERE {_sqlite_ident(c_col)} = ? LIMIT 1',
                (needle,),
            ).fetchone():
                return True
        except sqlite3.OperationalError:
            pass
        try:
            return bool(conn.execute(
                f'SELECT 1 FROM {_sqlite_ident(t)} '
                f'WHERE LOWER(TRIM(CAST({_sqlite_ident(c_col)} AS TEXT))) = ? '
                f'LIMIT 1',
                (needle_l,),
            ).fetchone())
        except sqlite3.OperationalError:
            return False

    for t in candidates:
        if _table_has_cell(t):
            return t
    # Fallback: tolerate minor naming drift (suffix/prefix/noise) via contains match.
    for t in candidates:
        c_col, _ = _resolve_pm_axis_columns_sqlite(conn, t)
        if not c_col:
            continue
        q = (
            f"SELECT 1 FROM {_sqlite_ident(t)} "
            f"WHERE LOWER(TRIM(CAST({_sqlite_ident(c_col)} AS TEXT))) LIKE ? "
            f"LIMIT 1"
        )
        try:
            if conn.execute(q, (f"%{needle_l}%",)).fetchone():
                return t
        except sqlite3.OperationalError:
            continue
    return candidates[0] if candidates else None


def _preferred_pm_table_for_site(technology: str, site_id, scope: str = 'hourly') -> str:
    tech = '4G' if technology in ('4G-FDD', '4G-TDD') else (technology or '4G')
    return preferred_pm_table(pm_table_name(tech, _normalize_data_scope(scope)), site_id)


def _preferred_pm_table_for_cell_name(technology: str, cell_name: str, scope: str = 'hourly') -> str | None:
    sid = site_id_from_cell_name(cell_name)
    if not sid:
        return None
    return _preferred_pm_table_for_site(technology, sid, scope)


def _sqlite_table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {r[0] for r in rows}


def _pm_dual_read_tables(
    conn: sqlite3.Connection,
    technology: str,
    site_id=None,
    *,
    preferred: str | None = None,
    scope: str = 'hourly',
) -> list[str]:
    """
    Tables to read during the dual-read window.

    Order: area partition first (new ingest), then legacy monotable (pre-cutover
    history). After retention drains the monotable it simply stops contributing.
    No migration required.
    """
    tech = '4G' if technology in ('4G-FDD', '4G-TDD') else (technology or '4G')
    data_scope = _normalize_data_scope(scope)
    base = pm_table_name(tech, data_scope)
    area = preferred or (
        preferred_pm_table(base, site_id) if site_id is not None else None
    )
    existing = _sqlite_table_names(conn)
    out: list[str] = []
    for name in (area, base):
        if name and name in existing and name not in out:
            out.append(name)
    # Daily DBs are still monotables today; tolerate a stale hourly preferred name.
    if not out and base in existing:
        out.append(base)
    if not out:
        for t in existing:
            if _table_technology(t) == tech and ('CELLS' in t.upper()):
                out.append(t)
                break
    return out


def _query_cell_trend_from_tables(
    pm_conn: sqlite3.Connection,
    tables: list[str],
    cell_name: str,
    requested_kpis: list[str] | None,
    pm_db: str,
) -> tuple[list[dict], str | None, str | None, str | None]:
    """
    UNION-style merge across dual-read tables.

    Prefer area-partition rows when the same timestamp exists in both (first
    table wins). Returns (rows, primary_table, cell_col, time_col).
    """
    if not tables:
        return [], None, None, None

    primary = tables[0]
    cell_col, time_col = _resolve_pm_axis_columns_sqlite(pm_conn, primary)
    if not cell_col or not time_col:
        return [], primary, cell_col, time_col

    full_kpi = _get_pm_cols_for_table(pm_db, primary)
    kpi_cols = _trend_kpi_columns(full_kpi, requested_kpis)
    extra_time = _pm_extra_trend_time_columns(pm_conn, primary)
    base_cols = (
        f'{_sqlite_ident(cell_col)} AS "cell_name", '
        f'{_sqlite_ident(time_col)} AS "timestamp", '
        f'{_sqlite_text_lit(time_col)} AS "__time_source"'
    )
    if kpi_cols:
        col_list = base_cols + extra_time + ', ' + ', '.join(f'"{c}"' for c in kpi_cols)
    else:
        col_list = base_cols + extra_time

    merged: list[dict] = []
    seen_ts: set[str] = set()

    def _absorb(rows: list) -> None:
        for r in rows:
            row = dict(r)
            key = str(row.get('timestamp') or '').strip()
            if key and key in seen_ts:
                continue
            if key:
                seen_ts.add(key)
            merged.append(row)

    for table in tables:
        c_col, t_col = _resolve_pm_axis_columns_sqlite(pm_conn, table)
        if not c_col or not t_col:
            continue
        # Re-resolve column list when schemas differ across tables.
        if c_col != cell_col or t_col != time_col:
            et = _pm_extra_trend_time_columns(pm_conn, table)
            bc = (
                f'{_sqlite_ident(c_col)} AS "cell_name", '
                f'{_sqlite_ident(t_col)} AS "timestamp", '
                f'{_sqlite_text_lit(t_col)} AS "__time_source"'
            )
            # KPI cols that exist on this table only.
            table_kpis = [c for c in (kpi_cols or []) if c in _get_pm_cols_for_table(pm_db, table)]
            cl = bc + et + (', ' + ', '.join(f'"{c}"' for c in table_kpis) if table_kpis else '')
        else:
            cl = col_list
            c_col, t_col = cell_col, time_col

        rows = pm_conn.execute(
            f'''
            SELECT {cl}
            FROM {_sqlite_ident(table)}
            WHERE LOWER(TRIM(CAST({_sqlite_ident(c_col)} AS TEXT))) = LOWER(TRIM(?))
            ORDER BY {_sqlite_ident(t_col)} ASC
            ''',
            (cell_name,),
        ).fetchall()
        if not rows:
            rows = pm_conn.execute(
                f'''
                SELECT {cl}
                FROM {_sqlite_ident(table)}
                WHERE LOWER(TRIM(CAST({_sqlite_ident(c_col)} AS TEXT))) LIKE LOWER(TRIM(?))
                ORDER BY {_sqlite_ident(t_col)} ASC
                ''',
                (f'%{cell_name}%',),
            ).fetchall()
        _absorb(rows)

    merged.sort(key=lambda r: _trend_row_sort_key(r, 'hour'))
    return merged, primary, cell_col, time_col


def _pm_cell_names_for_vendor_technology(vendor: str, technology: str, scope: str) -> set[str]:
    """Cell names with retained PM rows for the current Performance object scope."""
    db_path = _pm_db_for_vendor(vendor, scope)
    if not os.path.isfile(db_path):
        return set()

    names: set[str] = set()
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        existing = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        tech = '4G' if technology in ('4G-FDD', '4G-TDD') else technology
        data_scope = _normalize_data_scope(scope)
        base = pm_table_name(tech, data_scope)
        tables = list_pm_partition_tables(existing, base)
        if not tables:
            hit = _resolve_pm_table_sqlite(conn, vendor, technology, scope=data_scope)
            tables = [hit] if hit else []
        for table in tables:
            cell_col, _time_col = _resolve_pm_axis_columns_sqlite(conn, table)
            if not cell_col:
                continue
            rows = conn.execute(
                f'''
                SELECT DISTINCT TRIM(CAST({_sqlite_ident(cell_col)} AS TEXT)) AS cell_name
                FROM {_sqlite_ident(table)}
                WHERE {_sqlite_ident(cell_col)} IS NOT NULL
                  AND TRIM(CAST({_sqlite_ident(cell_col)} AS TEXT)) <> ''
                ''',
            ).fetchall()
            names.update(
                str(r['cell_name'] or '').strip().lower()
                for r in rows
                if str(r['cell_name'] or '').strip()
            )
    except sqlite3.Error:
        try:
            current_app.logger.exception(
                'Could not load PM-backed cell names for vendor=%s technology=%s scope=%s',
                vendor,
                technology,
                scope,
            )
        except RuntimeError:
            # Background cache warmers may run outside a Flask app context.
            pass
        return set()
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return names


def _pm_cell_names_cache_key(vendor: str, technology: str, scope: str) -> str:
    vendor = _norm_vendor_for_pm(vendor)
    tech = '4G' if technology in ('4G-FDD', '4G-TDD') else str(technology or '').strip()
    version = _pm_data_version_token(vendor, include_metadata=False, scope=scope)
    return '||'.join([version, vendor, tech, _normalize_data_scope(scope)])


def _warm_pm_cell_names_cache(vendor: str, technology: str, scope: str, key: str) -> None:
    try:
        names = _pm_cell_names_for_vendor_technology(vendor, technology, scope)
        with _PM_CELL_NAMES_CACHE_LOCK:
            _PM_CELL_NAMES_CACHE[key] = (time.time() + _PM_CELL_NAMES_CACHE_TTL_SEC, names)
    finally:
        with _PM_CELL_NAMES_CACHE_LOCK:
            _PM_CELL_NAMES_CACHE_INFLIGHT.discard(key)


def _cached_pm_cell_names_for_vendor_technology(
    vendor: str,
    technology: str,
    scope: str,
    *,
    warm: bool = True,
) -> set[str] | None:
    """Return cached PM cell names, warming them in the background on cache miss."""
    vendor = _norm_vendor_for_pm(vendor)
    tech = '4G' if technology in ('4G-FDD', '4G-TDD') else str(technology or '').strip()
    key = _pm_cell_names_cache_key(vendor, tech, scope)
    now = time.time()
    with _PM_CELL_NAMES_CACHE_LOCK:
        item = _PM_CELL_NAMES_CACHE.get(key)
        if item:
            expires_at, names = item
            if expires_at >= now:
                return names
            _PM_CELL_NAMES_CACHE.pop(key, None)
        if warm and key not in _PM_CELL_NAMES_CACHE_INFLIGHT:
            _PM_CELL_NAMES_CACHE_INFLIGHT.add(key)
            threading.Thread(
                target=_warm_pm_cell_names_cache,
                args=(vendor, tech, scope, key),
                daemon=True,
            ).start()
    return None


def _mark_rows_with_pm_data(rows: list[dict], scope: str) -> list[dict]:
    """Annotate metadata cells with retained PM-row availability when cached.

    On cache miss, start a background warm-up and leave ``has_pm_data`` as None
    so object-tree loading remains metadata-fast.
    """
    availability: dict[tuple[str, str], set[str] | None] = {}

    def available_for(row: dict) -> set[str] | None:
        vendor = _norm_vendor_for_pm(row.get('vendor') or '')
        tech = str(row.get('technology') or '').strip()
        pm_tech = '4G' if tech in ('4G-FDD', '4G-TDD') else tech
        key = (vendor, pm_tech)
        if key not in availability:
            availability[key] = _cached_pm_cell_names_for_vendor_technology(vendor, pm_tech, scope)
        return availability[key]

    for row in rows:
        cell_name = str(row.get('cell_name') or '').strip().lower()
        pm_names = available_for(row)
        row['has_pm_data'] = None if pm_names is None else bool(cell_name and cell_name in pm_names)
    return rows


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
    data_scope = _scope_from_pm_db(db_path)
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        existing = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        for tech in techs:
            base = pm_table_name(tech, data_scope)
            tables = list_pm_partition_tables(existing, base)
            if not tables:
                # Fall back to any tech-matching cells table (legacy name drift).
                tables = [
                    t for t in existing
                    if _table_technology(t) == ('4G' if tech in ('4G-FDD', '4G-TDD') else tech)
                    and 'CELLS' in t.upper()
                ] or [base]
            for table in tables:
                try:
                    result.update(_kpi_columns_for_sqlite_table(conn, table))
                except sqlite3.OperationalError:
                    continue
        conn.close()
    except Exception:
        pass
    return _drop_duplicate_kpis(sorted(result))


def _pm_extra_trend_time_columns(conn, table: str) -> str:
    """Extra SELECT columns: PrimeNet report date/time (never vendor Date/Time)."""
    try:
        names = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
    except sqlite3.OperationalError:
        return ''
    extras = []
    for col in (PM_REPORT_DATE_COL, PM_REPORT_TIME_COL):
        if col in names:
            extras.append(f'"{col}"')
    return (', ' + ', '.join(extras)) if extras else ''


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
        data_scope = _scope_from_pm_db(db_path)
        tables = [
            pm_table_name(t, data_scope)
            for t in ([technology] if technology else PM_TECHNOLOGIES)
        ]

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
        data_scope = _scope_from_pm_db(db_path)
        tables = [
            pm_table_name(t, data_scope)
            for t in ([technology] if technology else PM_TECHNOLOGIES)
        ]

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
    hours = _hours_from_request(data_scope)
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

        select_cols = [
            f'{_sqlite_ident(tcol)} AS "timestamp"',
            f'{_sqlite_text_lit(tcol)} AS "__time_source"',
        ] + [f'{_sqlite_ident(c)}' for c in kpi_cols]
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
        _hours, _gran, _start, _end = _resolved_time_frame(data_scope)
        rows = _apply_time_frame_rows(rows, _hours, _gran, _start, _end)
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

    meta_ver = _db_mtime_token(METADATA_DB)
    cached = _FILTERS_CACHE.get(meta_ver)
    if cached:
        expires_at, payload = cached
        if expires_at >= time.time():
            out = dict(payload)
            out['cached'] = True
            return jsonify(out)

    conn = _meta_conn()
    raw_sites = [dict(r) for r in _meta_exec(conn, '''
        SELECT site_id, site_name, vendor, latitude, longitude
        FROM sites
        WHERE site_id IS NOT NULL
        ORDER BY site_name
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

    payload = {'success': True, 'clusters': clusters, 'areas': areas, 'sites': sites, 'cached': False}
    _FILTERS_CACHE[meta_ver] = (time.time() + _FILTERS_CACHE_TTL_SEC, payload)
    return jsonify(payload)


# ---------------------------------------------------------------------------
# API: time-frame config (retention limits + presets)
# ---------------------------------------------------------------------------

@performance_bp.route('/api/performance/time-frame', methods=['GET'])
def get_time_frame_config():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data_scope = _normalize_data_scope(request.args.get('data_scope'))
    retention_days = _retention_days_for_scope(data_scope)
    retention_hours = retention_days * 24
    if data_scope == 'daily':
        presets = [
            {'id': '7d', 'label': 'Last 7 days', 'hours': min(168, retention_hours)},
            {'id': '14d', 'label': 'Last 14 days', 'hours': min(336, retention_hours)},
            {'id': '30d', 'label': 'Last 30 days', 'hours': min(720, retention_hours)},
            {'id': '60d', 'label': 'Last 60 days', 'hours': min(1440, retention_hours)},
            {'id': '90d', 'label': 'Last 90 days', 'hours': min(2160, retention_hours)},
            {'id': 'full', 'label': f'Full retention ({retention_days} days)', 'hours': None},
        ]
    else:
        presets = [
            {'id': '24h', 'label': 'Last 24 hours', 'hours': min(24, retention_hours)},
            {'id': '48h', 'label': 'Last 48 hours', 'hours': min(48, retention_hours)},
            {'id': '72h', 'label': 'Last 72 hours', 'hours': min(72, retention_hours)},
            {'id': '7d', 'label': 'Last 7 days', 'hours': min(168, retention_hours)},
            {'id': '14d', 'label': 'Last 14 days', 'hours': min(336, retention_hours)},
            {'id': 'full', 'label': f'Full retention ({retention_days} days)', 'hours': None},
        ]
    presets = [p for p in presets if p['hours'] is None or p['hours'] <= retention_hours]
    if not any(p['hours'] is None for p in presets):
        presets.append({
            'id': 'full',
            'label': f'Full retention ({retention_days} days)',
            'hours': None,
        })

    return jsonify({
        'success': True,
        'data_scope': data_scope,
        'retention_days': retention_days,
        'retention_hours': retention_hours,
        'presets': presets,
    })


def _cells_filter_where(vendor, technology, site_id, cluster, area, search=''):
    """Shared metadata WHERE clause for cell list / area summary queries."""
    where = ['1=1']
    params: list = []

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
        where.append('CAST(v.site_id AS TEXT) = ?')
        params.append(str(site_id).strip())
    if search:
        q = f'%{str(search).strip().lower()}%'
        where.append('''(
            LOWER(v.cell_name) LIKE ?
            OR LOWER(COALESCE(st.site_name, '')) LIKE ?
            OR CAST(v.site_id AS TEXT) LIKE ?
            OR LOWER(COALESCE(v.technology, '')) LIKE ?
        )''')
        params.extend([q, q, q, q])

    return where, params


def _cells_matching_site_ids(meta, area_index, cluster, area):
    if not cluster and not area:
        return None
    all_sites = [dict(r) for r in _meta_exec(
        meta,
        "SELECT site_id FROM sites WHERE site_id IS NOT NULL",
    ).fetchall()]
    matching_ids = []
    for s in all_sites:
        c_num, a_name = area_index.get(str(s['site_id']), _derive_cluster_area(s['site_id']))
        if cluster and str(c_num) != str(cluster):
            continue
        if area:
            normalized = (a_name or '').strip() or '—'
            if area == '—':
                if normalized != '—':
                    continue
            elif normalized != area:
                continue
        matching_ids.append(s['site_id'])
    return matching_ids


# ---------------------------------------------------------------------------
# API: cell area summaries (lazy tree — load cells per area on expand)
# ---------------------------------------------------------------------------

@performance_bp.route('/api/performance/cells/areas', methods=['GET'])
def get_cell_areas():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    vendor = request.args.get('vendor', '')
    technology = request.args.get('technology', '')
    site_id = request.args.get('site_id', '')
    cluster = request.args.get('cluster', '')
    area = request.args.get('area', '')
    search = request.args.get('search', '').strip()
    cache_key = _cell_cache_key(
        vendor,
        technology,
        site_id,
        cluster,
        area,
        _db_mtime_token(METADATA_DB) + '||areas||' + search.lower(),
    )
    cached = _cell_cache_get(cache_key)
    if cached is not None:
        return jsonify({'success': True, 'areas': cached['areas'], 'total_cells': cached['total_cells'], 'cached': True})

    where, params = _cells_filter_where(vendor, technology, site_id, cluster, area, search)

    meta = _meta_conn()
    area_index = _build_site_area_index(meta)

    matching_ids = _cells_matching_site_ids(meta, area_index, cluster, area)
    if matching_ids is not None:
        if matching_ids:
            placeholders = ','.join(['?'] * len(matching_ids))
            where.append(f'v.site_id IN ({placeholders})')
            params.extend(matching_ids)
        else:
            meta.close()
            payload = {'areas': [], 'total_cells': 0}
            _cell_cache_set(cache_key, payload)
            return jsonify({'success': True, 'areas': [], 'total_cells': 0, 'cached': False})
    meta.close()

    where_sql = ' AND '.join(where)
    source_sql = perf_cell_source_sql_with_activity(technology)

    conn = _meta_conn()
    try:
        sql = f'''
            SELECT v.cell_name, v.site_id
            FROM ({source_sql}) v
            WHERE {where_sql}
        '''
        rows = [dict(r) for r in _meta_exec(conn, sql, params).fetchall()]
    finally:
        conn.close()

    area_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        _c_num, a_name = area_index.get(str(row.get('site_id')), _derive_cluster_area(row.get('site_id')))
        key = (a_name or '').strip() or '—'
        area_counts[key] += 1

    areas_out = [
        {'area': k, 'cell_count': area_counts[k]}
        for k in sorted(area_counts.keys(), key=lambda x: (x == '—', x.lower()))
    ]
    total_cells = len(rows)
    payload = {'areas': areas_out, 'total_cells': total_cells}
    _cell_cache_set(cache_key, payload)
    return jsonify({'success': True, 'areas': areas_out, 'total_cells': total_cells, 'cached': False})


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
    search     = request.args.get('search', '').strip()
    data_scope = _normalize_data_scope(request.args.get('data_scope'))
    cache_key = _cell_cache_key(
        vendor,
        technology,
        site_id,
        cluster,
        area,
        _db_mtime_token(METADATA_DB) + '||' + search.lower(),
    )
    cached_cells = _cell_cache_get(cache_key)
    if cached_cells is not None:
        return jsonify({'success': True, 'cells': cached_cells, 'cached': True})

    where, params = _cells_filter_where(vendor, technology, site_id, cluster, area, search)

    meta = _meta_conn()
    area_index = _build_site_area_index(meta)

    matching_ids = _cells_matching_site_ids(meta, area_index, cluster, area)
    if matching_ids is not None:
        if matching_ids:
            placeholders = ','.join(['?'] * len(matching_ids))
            where.append(f'v.site_id IN ({placeholders})')
            params.extend(matching_ids)
        else:
            meta.close()
            return jsonify({'success': True, 'cells': []})
    meta.close()

    where_sql = ' AND '.join(where)
    source_sql = perf_cell_source_sql_with_activity(technology)

    # Metadata-only query — do not ATTACH multi-GB PM databases (was causing ~60s opens).
    conn = _meta_conn()
    try:
        sql = f'''
            SELECT
                v.cell_name AS cell_id,
                v.cell_name, v.technology, v.vendor,
                v.frequency_band, v.azimuth, v.pci,
                v.activity_status,
                st.site_id, st.site_name, st.latitude, st.longitude,
                NULL AS kpi_ts
            FROM ({source_sql}) v
            LEFT JOIN sites st ON CAST(v.site_id AS TEXT) = CAST(st.site_id AS TEXT)
            WHERE {where_sql}
            ORDER BY st.site_name, v.cell_name
        '''
        rows = [dict(r) for r in _meta_exec(conn, sql, params).fetchall()]
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
    hours = _hours_from_request(data_scope)

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
    table = _preferred_pm_table_for_site(cell_tech, cell.get('site_id'), data_scope)

    requested_kpis = _requested_trend_kpi_names()
    trend_cache_key = _trend_cache_key(
        "cell_id",
        str(cell_id),
        str(vendor or ""),
        str(table or ""),
        hours or 0,
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
            pm_conn = _open_pm_db(pm_db)
            pm_conn.row_factory = sqlite3.Row
            tables = _pm_dual_read_tables(
                pm_conn, str(cell_tech or ''), cell.get('site_id'), preferred=table, scope=data_scope
            )
            if not tables:
                hit = _resolve_pm_table_sqlite(
                    pm_conn, str(vendor or ''), str(cell_tech or ''), cell_name, table, scope=data_scope
                )
                tables = [hit] if hit else []
            trend, table, cell_col, time_col = _query_cell_trend_from_tables(
                pm_conn, tables, cell_name, requested_kpis, pm_db
            )
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
                "get_cell_trend(cell_id=%s) vendor=%s tables=%s cell_col=%s time_col=%s rows=%s",
                cell_id, vendor, tables, cell_col, time_col, len(trend)
            )
            pm_conn.close()
    except Exception:
        current_app.logger.exception('get_cell_trend: PM query failed cell_id=%s', cell_id)
        trend = []

    trend = _aggregate_trend_rows(trend, granularity)
    _hours, _gran, _start, _end = _resolved_time_frame(data_scope)
    trend = _apply_time_frame_rows(trend, _hours, _gran, _start, _end)
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
    hours = _hours_from_request(data_scope)

    meta_conn = _meta_conn()
    area_index = _build_site_area_index(meta_conn)
    source_sql = perf_cell_source_sql_with_activity(technology or None)
    where = ['v.cell_name = ?']
    params = [cell_name]
    if technology:
        if technology == '4G':
            where.append("(v.technology = '4G-FDD' OR v.technology = '4G-TDD')")
        else:
            where.append('v.technology = ?')
            params.append(technology)
    if site_id:
        where.append('CAST(v.site_id AS TEXT) = ?')
        params.append(site_id)
    if vendor:
        where.append('LOWER(TRIM(COALESCE(v.vendor, \'\'))) = LOWER(TRIM(?))')
        params.append(vendor)

    cell = _meta_exec(meta_conn, f'''
        SELECT
            v.cell_name AS cell_id,
            v.cell_name, v.technology, v.vendor,
            v.frequency_band, v.azimuth, v.pci,
            st.site_id, st.site_name, st.latitude, st.longitude
        FROM ({source_sql}) v
        LEFT JOIN sites st ON CAST(v.site_id AS TEXT) = CAST(st.site_id AS TEXT)
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
    table = _preferred_pm_table_for_site(pm_tech, cell.get('site_id'), data_scope)

    requested_kpis = _requested_trend_kpi_names()
    trend_cache_key = _trend_cache_key(
        "cell_name",
        "||".join([str(cell_name), str(technology), str(site_id)]),
        str(vendor or ""),
        str(table or ""),
        hours or 0,
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
            pm_conn = _open_pm_db(pm_db)
            pm_conn.row_factory = sqlite3.Row
            tables = _pm_dual_read_tables(
                pm_conn, str(pm_tech or ''), cell.get('site_id'), preferred=table, scope=data_scope
            )
            if not tables:
                hit = _resolve_pm_table_sqlite(
                    pm_conn, str(vendor or ''), str(pm_tech or ''), cell_name, table, scope=data_scope
                )
                tables = [hit] if hit else []
            trend, table, cell_col, time_col = _query_cell_trend_from_tables(
                pm_conn, tables, cell_name, requested_kpis, pm_db
            )
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
                "get_cell_trend_by_name(cell=%r vendor=%r tech=%r tables=%s cell_col=%s time_col=%s rows=%s",
                cell_name, vendor, pm_tech, tables, cell_col, time_col, len(trend)
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
    _hours, _gran, _start, _end = _resolved_time_frame(data_scope)
    trend = _apply_time_frame_rows(trend, _hours, _gran, _start, _end)
    _trend_cache_set(trend_cache_key, trend)
    return jsonify({'success': True, 'cell': cell, 'trend': trend, 'cached': False})


# ---------------------------------------------------------------------------
# API: PM raw data table (paginated, with static identifier columns)
# ---------------------------------------------------------------------------

@performance_bp.route('/api/performance/pm-table')
@heavy_query_required
def get_pm_table():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    vendor     = request.args.get('vendor', '')
    technology = request.args.get('technology', '')
    search     = request.args.get('search', '').strip()
    scoped_cell_names = [str(x).strip() for x in request.args.getlist('cell_name') if str(x).strip()]
    scoped_group_refs = [str(x).strip() for x in request.args.getlist('group_ref') if str(x).strip()]
    export_csv = request.args.get('export', '').lower() in ('1', 'true', 'csv')
    for_charts = request.args.get('for_charts', '').lower() in ('1', 'true', 'yes')
    page       = request.args.get('page', 1, type=int)
    page_size  = min(request.args.get('page_size', 100, type=int), 500)
    data_scope = _normalize_data_scope(request.args.get('data_scope'))
    hours, trend_granularity, date_start, date_end = _resolved_time_frame(data_scope)
    tf_token = _time_frame_cache_token(data_scope)

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

        if hours is not None or (date_start is not None and date_end is not None):
            all_rows = _apply_time_frame_rows(all_rows, hours, trend_granularity, date_start, date_end)

        total = len(all_rows)

        static_cols = [c for c in ('group_name', 'vendor', 'group_ref') if c in merged_cols]
        ordered_cols = static_cols + [c for c in merged_cols if c not in static_cols]
        column_labels = {'group_name': 'Group', 'group_ref': 'Group Ref', 'vendor': 'Vendor'}
        if export_csv:
            if total > _PM_EXPORT_MAX_ROWS:
                return jsonify({
                    'error': (
                        f'Export is limited to {_PM_EXPORT_MAX_ROWS:,} rows '
                        f'({total:,} matched). Narrow your selection or search.'
                    ),
                }), 400
            return _pm_table_csv_response(ordered_cols, column_labels, all_rows, vendor, technology)

        offset = (page - 1) * page_size
        page_rows = all_rows[offset:offset + page_size]
        payload = {
            'success': True,
            'columns': ordered_cols,
            'static_cols': static_cols,
            'column_labels': column_labels,
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

    empty = {
        'success': True, 'columns': [], 'static_cols': [],
        'column_labels': {}, 'rows': [], 'total': 0,
        'page': page, 'page_size': page_size, 'cell_label': cell_label,
    }

    db_path = _pm_db_for_vendor(vendor, data_scope)
    empty['cached'] = False
    requested_kpis = _requested_trend_kpi_names()
    try:
        conn = _open_pm_db(db_path)
        preferred = None
        if scoped_cell_names:
            preferred = _preferred_pm_table_for_cell_name(
                technology, scoped_cell_names[0], data_scope
            )
            preferred = _resolve_pm_table_sqlite(
                conn, vendor, technology, scoped_cell_names[0], preferred, scope=data_scope
            )
        bundle = _resolve_pm_table_bundle(conn, db_path, vendor, technology, preferred=preferred)
        if not bundle:
            conn.close()
            return jsonify(empty)

        table = bundle['table']
        dual_tables = _pm_dual_read_tables(
            conn, technology, None, preferred=preferred or table, scope=data_scope
        ) or [table]
        # Include bundle table if dual-read missed it (e.g. unexpected name).
        if table not in dual_tables:
            dual_tables.insert(0, table)
        resolved_cell_col = bundle['cell_col']
        resolved_time_col = bundle['time_col']
        existing_static = bundle['existing_static']
        ordered_cols = _pm_table_output_columns(
            existing_static,
            bundle['ordered_cols'],
            requested_kpis,
            export_csv=export_csv,
            for_charts=for_charts,
        )
        col_select = ', '.join(
            _pm_table_select_col(
                c,
                resolved_cell_col=resolved_cell_col,
                resolved_time_col=resolved_time_col,
            )
            for c in ordered_cols
        )
        table_cache_key_name = '+'.join(dual_tables)

        scoped_sig = '|'.join(sorted({n.lower() for n in scoped_cell_names}))
        group_sig = '|'.join(sorted({g.lower() for g in scoped_group_refs}))
        kpi_sig = '|'.join(sorted(requested_kpis or [])) if requested_kpis else '__static__'
        table_cache_key = _pm_table_cache_key(
            vendor,
            technology,
            table_cache_key_name,
            f'{search}||{scoped_sig}||{group_sig}||{kpi_sig}||{tf_token}',
            page,
            page_size,
            _pm_data_version_token(vendor, include_metadata=False, scope=data_scope),
        )
        charts_cache_key = table_cache_key + '||for_charts' if for_charts else table_cache_key
        if not export_csv:
            cached_table_payload = _pm_table_cache_get(charts_cache_key if for_charts else table_cache_key)
            if cached_table_payload is not None:
                out = dict(cached_table_payload)
                out['cached'] = True
                conn.close()
                return jsonify(out)

        where_parts = ['1=1']
        params: list = []
        if search:
            where_parts.append(f'{_sqlite_ident(resolved_cell_col)} LIKE ?')
            params.append(f'%{search}%')
        scope_sql, scope_params = _pm_table_cell_scope_sql(resolved_cell_col, scoped_cell_names)
        if scope_sql:
            where_parts.append(scope_sql)
            params.extend(scope_params)
        where_clause = ' AND '.join(where_parts)

        def _fetch_from_dual(
            order_sql: str,
            *,
            limit: int | None = None,
            offset: int | None = None,
            ascending_dedupe: bool = True,
        ) -> tuple[list[dict], int]:
            """
            Dual-read: query area partition + legacy monotable, dedupe by
            (cell, timestamp) preferring the first table (area / new data).
            """
            if len(dual_tables) == 1:
                lim = ''
                qparams = list(params)
                if limit is not None:
                    lim = ' LIMIT ?'
                    qparams.append(limit)
                    if offset is not None:
                        lim += ' OFFSET ?'
                        qparams.append(offset)
                rows = conn.execute(
                    f'''
                    SELECT {col_select} FROM {_sqlite_ident(dual_tables[0])}
                    WHERE {where_clause}
                    ORDER BY {order_sql}{lim}
                    ''',
                    qparams,
                ).fetchall()
                total_n = conn.execute(
                    f'SELECT COUNT(*) FROM {_sqlite_ident(dual_tables[0])} WHERE {where_clause}',
                    params,
                ).fetchone()[0]
                return [dict(r) for r in rows], int(total_n)

            seen: set[tuple[str, str]] = set()
            merged: list[dict] = []
            for tname in dual_tables:
                c_col, t_col = _resolve_pm_axis_columns_sqlite(conn, tname)
                if not c_col or not t_col:
                    continue
                # Rebuild select against this table's axis columns.
                t_col_select = ', '.join(
                    _pm_table_select_col(
                        c,
                        resolved_cell_col=c_col,
                        resolved_time_col=t_col,
                    )
                    for c in ordered_cols
                )
                t_where = list(where_parts)
                t_params = list(params)
                # where_parts may reference primary cell col — rebuild for this table.
                t_where = ['1=1']
                t_params = []
                if search:
                    t_where.append(f'{_sqlite_ident(c_col)} LIKE ?')
                    t_params.append(f'%{search}%')
                scope_sql2, scope_params2 = _pm_table_cell_scope_sql(c_col, scoped_cell_names)
                if scope_sql2:
                    t_where.append(scope_sql2)
                    t_params.extend(scope_params2)
                t_where_clause = ' AND '.join(t_where)
                rows = conn.execute(
                    f'''
                    SELECT {t_col_select} FROM {_sqlite_ident(tname)}
                    WHERE {t_where_clause}
                    ORDER BY {_sqlite_ident(t_col)} {'ASC' if ascending_dedupe else 'DESC'}
                    ''',
                    t_params,
                ).fetchall()
                for r in rows:
                    row = dict(r)
                    key = (
                        str(row.get('cell_name') or row.get(c_col) or '').strip().lower(),
                        str(row.get('timestamp') or row.get(t_col) or '').strip(),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    merged.append(row)
            merged.sort(
                key=lambda r: _trend_row_sort_key(r, trend_granularity),
                reverse=not ascending_dedupe,
            )
            total_n = len(merged)
            if offset is not None or limit is not None:
                start = offset or 0
                end = start + limit if limit is not None else None
                merged = merged[start:end]
            return merged, total_n

        column_labels = {
            PM_REPORT_DATE_COL: 'Report Date',
            PM_REPORT_TIME_COL: 'Report Time',
            'cell_name': cell_label,
        }
        if data_scope == 'daily':
            column_labels.pop(PM_REPORT_TIME_COL, None)

        scoped_query = bool(scoped_cell_names)
        if scoped_query and not export_csv and not for_charts:
            offset = (page - 1) * page_size
            if hours is not None or (date_start is not None and date_end is not None):
                row_dicts, _total_raw = _fetch_from_dual(
                    f'{_sqlite_ident(resolved_time_col)} DESC',
                    ascending_dedupe=False,
                )
                row_dicts = _apply_time_frame_rows(row_dicts, hours, trend_granularity, date_start, date_end)
                total = len(row_dicts)
                row_dicts = row_dicts[offset:offset + page_size]
            else:
                row_dicts, total = _fetch_from_dual(
                    f'{_sqlite_ident(resolved_time_col)} DESC',
                    limit=page_size,
                    offset=offset,
                    ascending_dedupe=False,
                )
            conn.close()
            payload = {
                'success':       True,
                'columns':       ordered_cols,
                'static_cols':   existing_static,
                'column_labels': column_labels,
                'rows':          row_dicts,
                'total':         total,
                'page':          page,
                'page_size':     page_size,
                'cell_label':    cell_label,
                'kpi_limited':   not bool(requested_kpis),
            }
            _pm_table_cache_set(table_cache_key, payload)
            out = dict(payload)
            out['cached'] = False
            return jsonify(out)

        row_dicts, total = _fetch_from_dual(
            f'{_sqlite_ident(resolved_time_col)} DESC',
            ascending_dedupe=False,
        )

        if hours is not None or (date_start is not None and date_end is not None):
            row_dicts = _apply_time_frame_rows(row_dicts, hours, trend_granularity, date_start, date_end)
            total = len(row_dicts)

        if export_csv:
            if total > _PM_EXPORT_MAX_ROWS:
                conn.close()
                return jsonify({
                    'error': (
                        f'Export is limited to {_PM_EXPORT_MAX_ROWS:,} rows '
                        f'({total:,} matched). Narrow your selection or search.'
                    ),
                }), 400
            conn.close()
            return _pm_table_csv_response(ordered_cols, column_labels, row_dicts, vendor, technology)

        if for_charts:
            if total > _PM_CHARTS_MAX_ROWS:
                conn.close()
                return jsonify({
                    'error': (
                        f'Too many rows ({total:,}) to chart at once '
                        f'(limit {_PM_CHARTS_MAX_ROWS:,}). Narrow your cell selection.'
                    ),
                }), 400
            # Charts want ascending time.
            row_dicts.sort(key=lambda r: _trend_row_sort_key(r, trend_granularity))
            conn.close()
            payload = {
                'success':       True,
                'columns':       ordered_cols,
                'static_cols':   existing_static,
                'column_labels': column_labels,
                'rows':          row_dicts,
                'total':         total,
                'page':          1,
                'page_size':     total,
                'cell_label':    cell_label,
                'for_charts':    True,
                'cached':        False,
            }
            _pm_table_cache_set(charts_cache_key, payload)
            return jsonify(payload)

        offset = (page - 1) * page_size
        if hours is not None or (date_start is not None and date_end is not None):
            page_rows = row_dicts[offset:offset + page_size]
        else:
            page_rows, total = _fetch_from_dual(
                f'{_sqlite_ident(resolved_time_col)} DESC',
                limit=page_size,
                offset=offset,
                ascending_dedupe=False,
            )
        conn.close()

        payload = {
            'success':       True,
            'columns':       ordered_cols,
            'static_cols':   existing_static,
            'column_labels': column_labels,
            'rows':          page_rows,
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
