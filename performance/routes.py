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
from datetime import datetime
import sqlite3
import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sync_config import (
    NOKIA_PM_DB,
    HUAWEI_PM_DB,
    METADATA_DB,
    NOKIA_GROUPS_DB,
    HUAWEI_GROUPS_DB,
    PM_TECHNOLOGIES,
    SCHEMA_HUAWEI_PM,
    pm_table_name,
    use_postgresql,
)
from database_enhanced import get_user_by_session, log_activity
from sync.metadata_active_sql import perf_per_tech_union_sql, perf_per_tech_union_sql_with_activity
from performance.kpi_catalog import KPI_HEADERS_MAP

performance_bp = Blueprint(
    'performance', __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/performance/static',
)

_FIXED_COLS = {'id', 'cell_name', 'timestamp', 'Date', 'date'}


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


def _parse_trend_ts(val):
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
    try:
        if s.endswith('Z'):
            s = s[:-1] + '+00:00'
        if 'T' not in s and len(s) >= 10:
            s = s.replace(' ', 'T', 1)
        dt = datetime.fromisoformat(s.split('.')[0])
        if dt.tzinfo:
            return dt.replace(tzinfo=None)
        return dt
    except ValueError:
        pass
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    return None


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
        ts_raw = row.get('timestamp') or row.get('Date') or row.get('date')
        dt = _parse_trend_ts(ts_raw)
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
_VENDOR_TECH_SCOPE = {
    'Nokia': ['2G', '3G', '4G', '5G'],
    'Huawei': ['2G', '3G', '4G'],
}


def _kpi_headers_static_for(vendor: str, technology: str) -> list[str]:
    return list(KPI_HEADERS_MAP.get(f'{vendor}|{technology}', []))


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

# Human-readable label for the cell_name column per vendor/technology
_PM_CELL_LABEL = {
    'Huawei': {'2G': 'Cell Name', '3G': 'Cell Name', '4G': 'Cell Name'},
    'Nokia':  {'2G': 'BTS name', '3G': 'WCEL name', '4G': 'LNCEL name', '5G': 'NRCEL name'},
}

# ---------------------------------------------------------------------------
# Lightweight in-memory cache for cell list queries
# ---------------------------------------------------------------------------
_CELL_LIST_CACHE = {}
_CELL_LIST_CACHE_TTL_SEC = 45


def _cell_cache_key(vendor: str, technology: str, site_id: str, cluster: str, area: str) -> str:
    return '||'.join([
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

# ---------------------------------------------------------------------------
# PM KPI column discovery (PRAGMA + per-column counts) — cache briefly
# ---------------------------------------------------------------------------
_KPI_COLS_CACHE = {}
_KPI_COLS_CACHE_TTL_SEC = 90


def _pm_cols_cache_key(db_path, table: str) -> str:
    try:
        m = int(os.path.getmtime(db_path))
    except OSError:
        m = 0
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


def _groups_db_for_vendor(vendor: str) -> str:
    return NOKIA_GROUPS_DB if vendor == 'Nokia' else HUAWEI_GROUPS_DB


def _groups_conn(vendor: str):
    conn = sqlite3.connect(_groups_db_for_vendor(vendor), timeout=15)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.row_factory = sqlite3.Row
    return conn


def _reports_conn():
    from sync_config import NCMUSERS_DB
    conn = sqlite3.connect(NCMUSERS_DB, timeout=15)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.row_factory = sqlite3.Row
    return conn


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
        return os.path.normpath(os.path.abspath(db_path)) == os.path.normpath(
            os.path.abspath(HUAWEI_PM_DB)
        )
    except Exception:
        return False


def _sqlite_ident(name: str) -> str:
    """Quote a SQLite identifier (handles embedded double quotes)."""
    return '"' + str(name).replace('"', '""') + '"'


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
    from sync.pm_processor import huawei_pm_kpi_tables, huawei_table_matches_technology

    result = set()
    if _is_huawei_pm_db(db_path):
        tables = huawei_pm_kpi_tables(db_path)
        if technology:
            tables = [t for t in tables if huawei_table_matches_technology(t, technology)]

        if use_postgresql():
            from db.runtime import connect_huawei_pm, postgres_table_columns, quote_ident
            import psycopg2.extensions

            fixed_lower = {c.lower() for c in _FIXED_COLS}
            qschema = quote_ident(SCHEMA_HUAWEI_PM)
            conn = connect_huawei_pm()
            try:
                for table in tables:
                    try:
                        raw = postgres_table_columns(conn, SCHEMA_HUAWEI_PM, table)
                        cols = [c for c in raw if c.lower() not in fixed_lower]
                        if not cols:
                            continue
                        qtbl = quote_ident(table)
                        counts_sql = ', '.join(
                            f'SUM(CASE WHEN {quote_ident(c)} IS NOT NULL THEN 1 ELSE 0 END)'
                            for c in cols
                        )
                        cur = conn.cursor(cursor_factory=psycopg2.extensions.Cursor)
                        cur.execute(f'SELECT {counts_sql} FROM {qschema}.{qtbl}')
                        row = cur.fetchone()
                        cur.close()
                        if row:
                            result.update(
                                col for col, cnt in zip(cols, row) if cnt is not None and cnt > 0
                            )
                    except Exception:
                        continue
            finally:
                conn.close()
            return sorted(result)

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
        return sorted(result)

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
    return sorted(result)


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


def _pg_pm_extra_trend_time_select(conn, schema: str, table: str) -> str:
    """PostgreSQL: optional Date/date column fragment for Huawei trend SELECT lists."""
    try:
        from db.runtime import postgres_table_columns, quote_ident

        names = set(postgres_table_columns(conn, schema, table))
    except Exception:
        return ''
    if 'Date' in names:
        return f', {quote_ident("Date")}'
    if 'date' in names:
        return f', {quote_ident("date")}'
    return ''


def _fetch_huawei_trend_postgresql(table: str, cell_name: str, hours: int, kpi_cols: list) -> list:
    """Load time-series rows for one Huawei PM table from PostgreSQL."""
    from db.runtime import connect_huawei_pm, execute_query, quote_ident

    conn = connect_huawei_pm()
    try:
        qschema = quote_ident(SCHEMA_HUAWEI_PM)
        qtbl = quote_ident(table)
        q_cell = quote_ident('cell_name')
        q_ts = quote_ident('timestamp')
        extra = _pg_pm_extra_trend_time_select(conn, SCHEMA_HUAWEI_PM, table)
        col_list = f'{q_cell}, {q_ts}{extra}'
        if kpi_cols:
            col_list += ', ' + ', '.join(quote_ident(c) for c in kpi_cols)

        h = max(0, int(hours))
        sql = f'''
            SELECT {col_list}
            FROM {qschema}.{qtbl}
            WHERE {q_cell} = %s
              AND {q_ts} >= (
                  SELECT MAX({q_ts}) FROM {qschema}.{qtbl} WHERE {q_cell} = %s
              ) - (%s * INTERVAL '1 hour')
            ORDER BY {q_ts} ASC
        '''
        cur = execute_query(conn, sql, (cell_name, cell_name, h))
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _load_pm_cols_for_table(db_path, table):
    """Return non-empty KPI columns for a specific table (uncached)."""
    try:
        if _is_huawei_pm_db(db_path) and use_postgresql():
            from db.runtime import connect_huawei_pm, postgres_table_columns, quote_ident
            import psycopg2.extensions

            fixed_lower = {c.lower() for c in _FIXED_COLS}
            qschema = quote_ident(SCHEMA_HUAWEI_PM)
            qtbl = quote_ident(table)
            conn = connect_huawei_pm()
            try:
                raw = postgres_table_columns(conn, SCHEMA_HUAWEI_PM, table)
                cols = [c for c in raw if c.lower() not in fixed_lower]
                if not cols:
                    return []
                counts_sql = ', '.join(
                    f'SUM(CASE WHEN {quote_ident(c)} IS NOT NULL THEN 1 ELSE 0 END)'
                    for c in cols
                )
                cur = conn.cursor(cursor_factory=psycopg2.extensions.Cursor)
                cur.execute(f'SELECT {counts_sql} FROM {qschema}.{qtbl}')
                row = cur.fetchone()
                cur.close()
                if not row:
                    return []
                return [col for col, cnt in zip(cols, row) if cnt is not None and cnt > 0]
            finally:
                conn.close()

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


def _pm_conn(vendor=None):
    """
    Open metadata.db and ATTACH the right PM db(s).
    Returns (conn, pm_alias_or_None).
    """
    conn = sqlite3.connect(METADATA_DB, timeout=15)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.row_factory = sqlite3.Row

    if vendor == 'Nokia':
        conn.execute(f"ATTACH DATABASE '{NOKIA_PM_DB}'  AS pm")
        return conn, 'pm'
    elif vendor == 'Huawei':
        conn.execute(f"ATTACH DATABASE '{HUAWEI_PM_DB}' AS pm")
        return conn, 'pm'
    else:
        conn.execute(f"ATTACH DATABASE '{NOKIA_PM_DB}'  AS nokia_pm")
        conn.execute(f"ATTACH DATABASE '{HUAWEI_PM_DB}' AS huawei_pm")
        return conn, None


def _build_pm_union(alias, db_path, technology=None):
    """
    Build UNION ALL subqueries across per-technology tables.

    Returns (data_sql, max_sql) where:
      data_sql — full UNION ALL with all KPI columns (for LEFT JOIN)
      max_sql  — minimal UNION ALL with just cell_name + timestamp (for MAX subquery)

    Both are None when no tables have data.
    """
    from sync.pm_processor import huawei_pm_kpi_tables, huawei_table_matches_technology

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
    from sync.pm_processor import huawei_pm_kpi_tables, huawei_table_matches_technology

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
    if vendor and vendor not in ('Nokia', 'Huawei'):
        vendor = ''
    allowed_tech = {'2G', '3G', '4G', '5G'}
    if technology and technology not in allowed_tech:
        technology = ''

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
        db_path = NOKIA_PM_DB if vendor == 'Nokia' else HUAWEI_PM_DB
        columns = _get_pm_cols(db_path, technology)
        return jsonify({
            'success': True,
            'columns': columns,
            'vendor': vendor,
            'technology': technology,
            'source': 'dynamic',
        })

    if vendor and not technology:
        db_path = NOKIA_PM_DB if vendor == 'Nokia' else HUAWEI_PM_DB
        columns = _get_pm_cols(db_path, None)
        return jsonify({'success': True, 'columns': columns, 'vendor': vendor, 'source': 'dynamic'})

    if technology and not vendor:
        n = _get_pm_cols(NOKIA_PM_DB, technology)
        h = _get_pm_cols(HUAWEI_PM_DB, technology)
        columns = sorted(set(n) | set(h))
        return jsonify({'success': True, 'columns': columns, 'technology': technology, 'source': 'dynamic'})

    nokia = _get_pm_cols(NOKIA_PM_DB)
    huawei = _get_pm_cols(HUAWEI_PM_DB)
    columns = sorted(set(nokia) | set(huawei))
    return jsonify({
        'success': True,
        'columns': columns,
        'nokia': nokia,
        'huawei': huawei,
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

    mapping = {}
    for vendor, techs in _VENDOR_TECH_SCOPE.items():
        db_path = NOKIA_PM_DB if vendor == 'Nokia' else HUAWEI_PM_DB
        for tech in techs:
            cols = _get_pm_cols(db_path, tech)
            mapping[f'{vendor}|{tech}'] = cols
    return jsonify({'success': True, 'mapping': mapping, 'source': 'dynamic'})


@performance_bp.route('/api/performance/groups', methods=['GET'])
def get_cell_groups():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    uid = _user_id(user)
    req_vendor = (request.args.get('vendor') or '').strip()
    req_tech = (request.args.get('technology') or '').strip()
    vendors = [req_vendor] if req_vendor in ('Nokia', 'Huawei') else ['Nokia', 'Huawei']
    rows = []
    for vendor in vendors:
        conn = _groups_conn(vendor)
        where = ['(g.user_id = ? OR g.is_shared = 1)']
        params = [uid]
        if req_tech:
            where.append('gc.technology = ?')
            params.append(req_tech)
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
        conn.close()
        for r in v_rows:
            if req_tech and int(r.get('cell_count') or 0) <= 0:
                continue
            r['vendor'] = vendor
            r['group_ref'] = f'{vendor}:{r["id"]}'
        rows.extend(v_rows)
    rows.sort(key=lambda r: (str(r.get('updated_at') or ''), str(r.get('group_ref') or '')), reverse=True)
    return jsonify({'success': True, 'groups': rows})


@performance_bp.route('/api/performance/groups/<group_ref>/cell_keys', methods=['GET'])
def get_group_cell_keys(group_ref):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    uid = _user_id(user)
    vendor = (request.args.get('vendor') or '').strip()
    technology = (request.args.get('technology') or '').strip()
    try:
        source_vendor, raw_gid = group_ref.split(':', 1)
        group_id = int(raw_gid)
    except Exception:
        return jsonify({'error': 'Invalid group reference'}), 400
    if source_vendor not in ('Nokia', 'Huawei'):
        return jsonify({'error': 'Invalid group vendor'}), 400

    conn = _groups_conn(source_vendor)
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


@performance_bp.route('/api/performance/reports', methods=['GET'])
def get_performance_reports():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    _ensure_reports_table()
    uid = _user_id(user)
    conn = _reports_conn()
    rows = [dict(r) for r in conn.execute(
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
    cur = conn.cursor()
    row = cur.execute(
        'SELECT id FROM performance_reports WHERE user_id = ? AND report_name = ?',
        (uid, name),
    ).fetchone()
    if row:
        rid = int(row['id'])
        cur.execute(
            '''
            UPDATE performance_reports
            SET report_config = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            ''',
            (cfg_text, rid),
        )
    else:
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
    cur = conn.cursor()
    cur.execute('DELETE FROM performance_reports WHERE id = ? AND user_id = ?', (report_id, uid))
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
    raw_sites = [dict(r) for r in conn.execute(f'''
        SELECT DISTINCT s.site_id, s.site_name, s.vendor
        FROM ({union_sql}) v
        JOIN sites s ON s.site_id = v.site_id
        ORDER BY s.site_name
    ''').fetchall()]
    conn.close()

    # Derive cluster/area from site_id (same logic as network map)
    cluster_set = set()
    area_pairs  = set()      # (cluster, area)
    sites = []
    for s in raw_sites:
        cluster, area = _derive_cluster_area(s['site_id'])
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
    cache_key = _cell_cache_key(vendor, technology, site_id, cluster, area)
    cached_cells = _cell_cache_get(cache_key)
    if cached_cells is not None:
        return jsonify({'success': True, 'cells': cached_cells, 'cached': True})

    where  = ["1=1"]
    params = []

    if vendor:
        where.append('v.vendor = ?')
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

    # cluster / area filtering: derive from site_id, then filter by matching site_ids
    if cluster or area:
        meta = _meta_conn()
        all_sites = [dict(r) for r in meta.execute(
            "SELECT site_id FROM sites"
        ).fetchall()]
        meta.close()
        matching_ids = []
        for s in all_sites:
            c_num, a_name = _derive_cluster_area(s['site_id'])
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
            # No sites match — return empty
            return jsonify({'success': True, 'cells': []})

    where_sql = ' AND '.join(where)
    union_sql = perf_per_tech_union_sql_with_activity()

    conn, _pm_alias = _pm_conn(vendor if vendor else None)

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
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

    except sqlite3.OperationalError:
        # PM db doesn't exist yet (first run before any sync)
        rows = [dict(r) for r in conn.execute(f'''
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

    # Enrich each row with derived cluster / area
    for row in rows:
        c_num, a_name = _derive_cluster_area(row.get('site_id'))
        row['cluster'] = c_num
        row['area']    = a_name
        row['cell_key'] = '||'.join([
            str(row.get('vendor') or ''),
            str(row.get('technology') or ''),
            str(row.get('site_id') or ''),
            str(row.get('cell_name') or ''),
        ])

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

    hours = _clamp_trend_hours(request.args.get('hours', 168, type=int))
    granularity = _normalize_granularity(request.args.get('granularity'))

    meta_conn = _meta_conn()
    cell = meta_conn.execute('''
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
    cluster, area = _derive_cluster_area(cell.get('site_id'))
    cell['cluster'] = cluster
    cell['area']    = area
    vendor    = cell.get('vendor')
    cell_name = cell['cell_name']
    cell_tech = cell.get('technology', '4G')
    pm_db     = NOKIA_PM_DB if vendor == 'Nokia' else HUAWEI_PM_DB
    if vendor == 'Huawei':
        from sync.pm_processor import huawei_pm_table_for_cell

        table = huawei_pm_table_for_cell(cell_name, cell_tech, pm_db)
    else:
        table = pm_table_name(cell_tech)

    trend = []
    try:
        if table:
            full_kpi = _get_pm_cols_for_table(pm_db, table)
            kpi_cols = _trend_kpi_columns(full_kpi, _requested_trend_kpi_names())
            if vendor == 'Huawei' and use_postgresql():
                trend = _fetch_huawei_trend_postgresql(table, cell_name, hours, kpi_cols)
            else:
                pm_conn = sqlite3.connect(pm_db)
                pm_conn.row_factory = sqlite3.Row
                extra_time = _pm_extra_trend_time_columns(pm_conn, table)
                if kpi_cols:
                    col_list = 'cell_name, timestamp' + extra_time + ', ' + ', '.join(f'"{c}"' for c in kpi_cols)
                else:
                    col_list = 'cell_name, timestamp' + extra_time

                trend = [dict(r) for r in pm_conn.execute(f'''
                    SELECT {col_list}
                    FROM "{table}"
                    WHERE cell_name = ?
                      AND timestamp >= datetime(
                          (SELECT MAX(timestamp) FROM "{table}" WHERE cell_name = ?),
                          ? || ' hours'
                      )
                    ORDER BY timestamp ASC
                ''', (cell_name, cell_name, f'-{hours}')).fetchall()]
                pm_conn.close()
    except Exception:
        current_app.logger.exception('get_cell_trend: PM query failed cell_id=%s', cell_id)
        trend = []

    trend = _aggregate_trend_rows(trend, granularity)
    return jsonify({'success': True, 'cell': cell, 'trend': trend})


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
    hours = _clamp_trend_hours(request.args.get('hours', 168, type=int))
    granularity = _normalize_granularity(request.args.get('granularity'))

    meta_conn = _meta_conn()
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

    cell = meta_conn.execute(f'''
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
    cluster, area = _derive_cluster_area(cell.get('site_id'))
    cell['cluster'] = cluster
    cell['area'] = area

    vendor = cell.get('vendor')
    tech = cell.get('technology', '4G')
    pm_db = NOKIA_PM_DB if vendor == 'Nokia' else HUAWEI_PM_DB
    pm_tech = '4G' if tech in ('4G-FDD', '4G-TDD') else tech
    if vendor == 'Huawei':
        from sync.pm_processor import huawei_pm_table_for_cell

        table = huawei_pm_table_for_cell(cell_name, pm_tech, pm_db)
    else:
        table = pm_table_name(pm_tech)

    trend = []
    try:
        if table:
            full_kpi = _get_pm_cols_for_table(pm_db, table)
            kpi_cols = _trend_kpi_columns(full_kpi, _requested_trend_kpi_names())
            if vendor == 'Huawei' and use_postgresql():
                trend = _fetch_huawei_trend_postgresql(table, cell_name, hours, kpi_cols)
            else:
                pm_conn = sqlite3.connect(pm_db)
                pm_conn.row_factory = sqlite3.Row
                extra_time = _pm_extra_trend_time_columns(pm_conn, table)
                col_list = (
                    'cell_name, timestamp' + extra_time
                    + (', ' + ', '.join(f'"{c}"' for c in kpi_cols) if kpi_cols else '')
                )
                trend = [dict(r) for r in pm_conn.execute(f'''
                    SELECT {col_list}
                    FROM "{table}"
                    WHERE cell_name = ?
                      AND timestamp >= datetime(
                          (SELECT MAX(timestamp) FROM "{table}" WHERE cell_name = ?),
                          ? || ' hours'
                      )
                    ORDER BY timestamp ASC
                ''', (cell_name, cell_name, f'-{hours}')).fetchall()]
                pm_conn.close()
    except Exception:
        current_app.logger.exception(
            'get_cell_trend_by_name: PM query failed cell_name=%r vendor=%r',
            cell_name,
            vendor,
        )
        trend = []

    trend = _aggregate_trend_rows(trend, granularity)
    return jsonify({'success': True, 'cell': cell, 'trend': trend})


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
    page       = request.args.get('page', 1, type=int)
    page_size  = min(request.args.get('page_size', 100, type=int), 500)

    if vendor not in ('Nokia', 'Huawei'):
        return jsonify({'error': 'Vendor must be Nokia or Huawei'}), 400
    if not technology:
        return jsonify({'error': 'Technology is required'}), 400

    static_cfg = _PM_STATIC_COLS.get(vendor, {}).get(technology, [])
    cell_label = _PM_CELL_LABEL.get(vendor, {}).get(technology, 'Cell Name')
    ts_label   = 'Period Start' if vendor == 'Nokia' else 'Date'

    empty = {
        'success': True, 'columns': [], 'static_cols': [],
        'column_labels': {}, 'rows': [], 'total': 0,
        'page': page, 'page_size': page_size, 'cell_label': cell_label,
    }

    db_path = NOKIA_PM_DB if vendor == 'Nokia' else HUAWEI_PM_DB
    if vendor == 'Huawei':
        from sync.pm_processor import resolve_huawei_pm_table

        table = resolve_huawei_pm_table(technology, db_path)
        if not table:
            return jsonify(empty)
    else:
        table = pm_table_name(technology)

    try:
        conn     = sqlite3.connect(db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        all_cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]

        if not all_cols:
            conn.close()
            return jsonify(empty)

        # Build column order: static first (only those that exist in the table),
        # then every other column except excluded ones.
        existing_static = [c for c in static_cfg if c in all_cols]
        # Huawei exports often include a literal ``Date`` column; keep it next to ``timestamp``,
        # not in the KPI block.
        if vendor == 'Huawei':
            for dc in ('Date', 'date'):
                if dc in all_cols and dc not in existing_static:
                    if 'timestamp' in existing_static:
                        i = existing_static.index('timestamp') + 1
                        existing_static.insert(i, dc)
                    else:
                        existing_static.insert(0, dc)
                    break
        static_set      = set(existing_static)
        kpi_cols        = [c for c in all_cols
                           if c not in _PM_EXCLUDE_COLS and c not in static_set]
        ordered_cols    = existing_static + kpi_cols
        col_select      = ', '.join(f'"{c}"' for c in ordered_cols)

        where_clause = '1=1'
        params       = []
        if search:
            where_clause = 'cell_name LIKE ?'
            params.append(f'%{search}%')

        total  = conn.execute(
            f'SELECT COUNT(*) FROM "{table}" WHERE {where_clause}', params
        ).fetchone()[0]
        offset = (page - 1) * page_size
        rows   = conn.execute(f'''
            SELECT {col_select} FROM "{table}"
            WHERE  {where_clause}
            ORDER  BY timestamp DESC
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

        return jsonify({
            'success':       True,
            'columns':       ordered_cols,
            'static_cols':   existing_static,
            'column_labels': column_labels,
            'rows':          [dict(r) for r in rows],
            'total':         total,
            'page':          page,
            'page_size':     page_size,
            'cell_label':    cell_label,
        })

    except sqlite3.OperationalError:
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
    from sync.scheduler import trigger_nokia_pm_now
    threading.Thread(target=trigger_nokia_pm_now, daemon=True).start()
    return jsonify({'success': True, 'message': 'Nokia PM pull triggered.'})


@performance_bp.route('/api/sync/trigger/huawei', methods=['POST'])
def trigger_huawei():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    import threading
    from sync.scheduler import trigger_huawei_pm_now
    threading.Thread(target=trigger_huawei_pm_now, daemon=True).start()
    return jsonify({'success': True, 'message': 'Huawei PM pull triggered.'})
