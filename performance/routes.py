"""
Performance Routes
==================
Three-database architecture:
  metadata.db   → sites, cells (source of truth, all vendors)
  nokia_pm.db   → Nokia hourly KPIs keyed by cell_name
  huawei_pm.db  → Huawei hourly KPIs keyed by cell_name

KPI columns are dynamic — whatever headers were in the source files are stored
as-is in the PM databases. Queries build their SELECT lists by inspecting the
live DB schema so no code changes are needed when the file structure changes.
"""

from flask import Blueprint, request, jsonify, render_template, redirect, url_for
from functools import wraps
import sqlite3, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sync_config import NOKIA_PM_DB, HUAWEI_PM_DB, METADATA_DB, PM_TECHNOLOGIES, pm_table_name
from database_enhanced import get_user_by_session, log_activity

performance_bp = Blueprint(
    'performance', __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/performance/static',
)

_FIXED_COLS = {'id', 'cell_name', 'timestamp'}

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


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _meta_conn():
    conn = sqlite3.connect(METADATA_DB, timeout=15)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.row_factory = sqlite3.Row
    return conn


def _get_pm_cols(db_path, technology=None):
    """
    Return KPI column names that contain actual numeric data.
    Scans all per-technology tables (or a single one when technology is given).
    """
    techs = [technology] if technology else PM_TECHNOLOGIES
    result = set()
    try:
        conn = sqlite3.connect(db_path)
        for tech in techs:
            table = pm_table_name(tech)
            try:
                cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
                        if r[1] not in _FIXED_COLS]
                if not cols:
                    continue
                counts_sql = ', '.join(
                    f'SUM(CASE WHEN "{col}" IS NOT NULL THEN 1 ELSE 0 END)'
                    for col in cols
                )
                row = conn.execute(f'SELECT {counts_sql} FROM "{table}"').fetchone()
                if row:
                    result.update(col for col, cnt in zip(cols, row) if cnt and cnt > 0)
            except sqlite3.OperationalError:
                continue
        conn.close()
    except Exception:
        pass
    return sorted(result)


def _get_pm_cols_for_table(db_path, table):
    """Return non-empty KPI columns for a specific table."""
    try:
        conn = sqlite3.connect(db_path)
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
                if r[1] not in _FIXED_COLS]
        if not cols:
            conn.close()
            return []
        counts_sql = ', '.join(
            f'SUM(CASE WHEN "{col}" IS NOT NULL THEN 1 ELSE 0 END)'
            for col in cols
        )
        row = conn.execute(f'SELECT {counts_sql} FROM "{table}"').fetchone()
        conn.close()
        if not row:
            return []
        return [col for col, cnt in zip(cols, row) if cnt and cnt > 0]
    except Exception:
        return []


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
    techs = [technology] if technology else PM_TECHNOLOGIES
    all_kpi = set()
    table_cols = {}  # {table: [cols_with_data]}

    try:
        conn = sqlite3.connect(db_path)
        for tech in techs:
            table = pm_table_name(tech)
            try:
                cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
                        if r[1] not in _FIXED_COLS]
                if not cols:
                    continue
                counts_sql = ', '.join(
                    f'SUM(CASE WHEN "{c}" IS NOT NULL THEN 1 ELSE 0 END)' for c in cols
                )
                row = conn.execute(f'SELECT {counts_sql} FROM "{table}"').fetchone()
                if row:
                    good = [c for c, cnt in zip(cols, row) if cnt and cnt > 0]
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
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify({
        'success': True,
        'nokia':  _get_pm_cols(NOKIA_PM_DB),
        'huawei': _get_pm_cols(HUAWEI_PM_DB),
    })


# ---------------------------------------------------------------------------
# API: filter options
# ---------------------------------------------------------------------------

@performance_bp.route('/api/performance/filters', methods=['GET'])
def get_filters():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    conn = _meta_conn()

    raw_sites = [dict(r) for r in conn.execute(
        "SELECT site_id, site_name, vendor FROM sites WHERE status='Active' ORDER BY site_name"
    ).fetchall()]
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

    where  = ["c.status = 'Active'"]
    params = []

    if vendor:
        where.append('c.vendor = ?')
        params.append(vendor)
    if technology:
        if technology == '4G':
            where.append("(c.technology = '4G' OR c.technology = '4G-FDD' OR c.technology = '4G-TDD')")
        else:
            where.append('c.technology = ?')
            params.append(technology)
    if site_id:
        where.append('c.site_id = ?')
        params.append(site_id)

    # cluster / area filtering: derive from site_id, then filter by matching site_ids
    if cluster or area:
        meta = _meta_conn()
        all_sites = [dict(r) for r in meta.execute(
            "SELECT site_id FROM sites WHERE status='Active'"
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
            where.append(f'c.site_id IN ({placeholders})')
            params.extend(matching_ids)
        else:
            # No sites match — return empty
            return jsonify({'success': True, 'cells': []})

    where_sql = ' AND '.join(where)

    conn, pm_alias = _pm_conn(vendor if vendor else None)

    try:
        if pm_alias:
            # Single vendor — build UNION ALL across per-technology tables
            pm_db = NOKIA_PM_DB if vendor == 'Nokia' else HUAWEI_PM_DB
            kpi_cols = _get_pm_cols(pm_db, technology if technology else None)
            kpi_select = (',' + ','.join(f'k."{c}"' for c in kpi_cols)) if kpi_cols else ''

            # Build the PM subquery (single table or UNION ALL)
            pm_sub, pm_max = _build_pm_union('pm', pm_db, technology if technology else None)

            if pm_sub:
                sql = f'''
                    SELECT
                        c.cell_id, c.cell_name, c.technology, c.vendor,
                        c.frequency_band, c.azimuth, c.pci,
                        st.site_id, st.site_name, st.latitude, st.longitude,
                        k.timestamp AS kpi_ts{kpi_select}
                    FROM cells c
                    LEFT JOIN sites st ON c.site_id = st.site_id
                    LEFT JOIN ({pm_sub}) k
                        ON k.cell_name = c.cell_name
                        AND k.timestamp = (
                            SELECT MAX(timestamp) FROM ({pm_max})
                            WHERE cell_name = c.cell_name
                        )
                    WHERE {where_sql}
                    ORDER BY st.site_name, c.cell_name
                '''
            else:
                sql = f'''
                    SELECT
                        c.cell_id, c.cell_name, c.technology, c.vendor,
                        c.frequency_band, c.azimuth, c.pci,
                        st.site_id, st.site_name, st.latitude, st.longitude,
                        NULL AS kpi_ts
                    FROM cells c
                    LEFT JOIN sites st ON c.site_id = st.site_id
                    WHERE {where_sql}
                    ORDER BY st.site_name, c.cell_name
                '''
            rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

        else:
            # Both vendors — build UNION ALL across all tech tables in both PM dbs
            nokia_sub,  nokia_max  = _build_pm_union('nokia_pm',  NOKIA_PM_DB,  technology if technology else None)
            huawei_sub, huawei_max = _build_pm_union('huawei_pm', HUAWEI_PM_DB, technology if technology else None)

            nokia_cols  = _get_pm_cols(NOKIA_PM_DB,  technology if technology else None)
            huawei_cols = _get_pm_cols(HUAWEI_PM_DB, technology if technology else None)
            all_cols    = sorted(set(nokia_cols) | set(huawei_cols))
            outer_kpi   = (',' + ','.join(f'k."{c}"' for c in all_cols)) if all_cols else ''

            # Combine UNION parts from both vendors
            union_parts = [p for p in (nokia_sub, huawei_sub) if p]
            max_parts   = [p for p in (nokia_max, huawei_max) if p]

            if union_parts:
                combined_sub = ' UNION ALL '.join(union_parts)
                combined_max = ' UNION ALL '.join(max_parts)
                sql = f'''
                    SELECT
                        c.cell_id, c.cell_name, c.technology, c.vendor,
                        c.frequency_band, c.azimuth, c.pci,
                        st.site_id, st.site_name, st.latitude, st.longitude,
                        k.timestamp AS kpi_ts{outer_kpi}
                    FROM cells c
                    LEFT JOIN sites st ON c.site_id = st.site_id
                    LEFT JOIN ({combined_sub}) k
                        ON k.cell_name = c.cell_name
                        AND k.timestamp = (
                            SELECT MAX(timestamp) FROM ({combined_max})
                            WHERE cell_name = c.cell_name
                        )
                    WHERE {where_sql}
                    ORDER BY st.site_name, c.cell_name
                '''
            else:
                sql = f'''
                    SELECT
                        c.cell_id, c.cell_name, c.technology, c.vendor,
                        c.frequency_band, c.azimuth, c.pci,
                        st.site_id, st.site_name, st.latitude, st.longitude,
                        NULL AS kpi_ts
                    FROM cells c
                    LEFT JOIN sites st ON c.site_id = st.site_id
                    WHERE {where_sql}
                    ORDER BY st.site_name, c.cell_name
                '''
            rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

    except sqlite3.OperationalError as e:
        # PM db doesn't exist yet (first run before any sync)
        rows = [dict(r) for r in conn.execute(f'''
            SELECT
                c.cell_id, c.cell_name, c.technology, c.vendor,
                c.frequency_band, c.azimuth, c.pci,
                st.site_id, st.site_name,
                st.latitude, st.longitude, NULL AS kpi_ts
            FROM cells c
            LEFT JOIN sites st ON c.site_id = st.site_id
            WHERE {where_sql}
            ORDER BY st.site_name, c.cell_name
        ''', params).fetchall()]

    finally:
        conn.close()

    # Enrich each row with derived cluster / area
    for row in rows:
        c_num, a_name = _derive_cluster_area(row.get('site_id'))
        row['cluster'] = c_num
        row['area']    = a_name

    log_activity(_user_id(user), 'performance_view', 'Viewed performance cells list')
    return jsonify({'success': True, 'cells': rows})


# ---------------------------------------------------------------------------
# API: time-series KPI trend for a single cell
# ---------------------------------------------------------------------------

@performance_bp.route('/api/performance/cell/<int:cell_id>/trend', methods=['GET'])
def get_cell_trend(cell_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    hours = min(request.args.get('hours', 168, type=int), 168)

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
    table     = pm_table_name(cell_tech)

    try:
        # Only select KPI columns that have real numeric data (not text leftovers)
        kpi_cols = _get_pm_cols_for_table(pm_db, table)
        if kpi_cols:
            col_list = 'cell_name, timestamp, ' + ', '.join(f'"{c}"' for c in kpi_cols)
        else:
            col_list = 'cell_name, timestamp'

        pm_conn = sqlite3.connect(pm_db)
        pm_conn.row_factory = sqlite3.Row
        # Use time window relative to the latest available data, not 'now'.
        # This ensures imported/historical data always shows up even when
        # the scheduler hasn't run recently.
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
    except sqlite3.OperationalError:
        trend = []

    return jsonify({'success': True, 'cell': cell, 'trend': trend})


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
