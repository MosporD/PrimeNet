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
from sync_config import NOKIA_PM_DB, HUAWEI_PM_DB, METADATA_DB
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


def _get_pm_cols(db_path):
    """
    Return KPI column names that contain actual numeric data.
    Vendor files include text columns (eNodeB name, Object, BTS ID, etc.)
    which get stored as all-NULL REAL columns — those are excluded here.
    """
    try:
        conn = sqlite3.connect(db_path)
        all_cols = [r[1] for r in conn.execute('PRAGMA table_info(cell_kpis)').fetchall()
                    if r[1] not in _FIXED_COLS]
        if not all_cols:
            conn.close()
            return []

        # Single query: count non-NULL values for every candidate column
        counts_sql = ', '.join(
            f'SUM(CASE WHEN "{col}" IS NOT NULL THEN 1 ELSE 0 END)'
            for col in all_cols
        )
        row = conn.execute(f'SELECT {counts_sql} FROM cell_kpis').fetchone()
        conn.close()

        if not row:
            return []
        return [col for col, cnt in zip(all_cols, row) if cnt and cnt > 0]
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
            # Single vendor — build KPI select from live schema
            pm_db = NOKIA_PM_DB if vendor == 'Nokia' else HUAWEI_PM_DB
            kpi_cols = _get_pm_cols(pm_db)
            kpi_select = (',' + ','.join(f'k."{c}"' for c in kpi_cols)) if kpi_cols else ''

            sql = f'''
                SELECT
                    c.cell_id, c.cell_name, c.technology, c.vendor,
                    c.frequency_band, c.azimuth, c.pci,
                    st.site_id, st.site_name, st.latitude, st.longitude,
                    k.timestamp AS kpi_ts{kpi_select}
                FROM cells c
                LEFT JOIN sites st ON c.site_id = st.site_id
                LEFT JOIN pm.cell_kpis k
                    ON k.cell_name = c.cell_name
                    AND k.timestamp = (
                        SELECT MAX(timestamp) FROM pm.cell_kpis
                        WHERE cell_name = c.cell_name
                    )
                WHERE {where_sql}
                ORDER BY st.site_name, c.cell_name
            '''
            rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

        else:
            # Both vendors — align columns from both PM dbs for UNION ALL
            nokia_cols  = _get_pm_cols(NOKIA_PM_DB)
            huawei_cols = _get_pm_cols(HUAWEI_PM_DB)
            all_cols    = sorted(set(nokia_cols) | set(huawei_cols))

            if all_cols:
                nokia_inner  = ', '.join(f'"{c}"' if c in nokia_cols  else f'NULL AS "{c}"' for c in all_cols)
                huawei_inner = ', '.join(f'"{c}"' if c in huawei_cols else f'NULL AS "{c}"' for c in all_cols)
                outer_kpi    = ',' + ','.join(f'k."{c}"' for c in all_cols)
                union_nokia  = f'SELECT cell_name, timestamp, {nokia_inner}  FROM nokia_pm.cell_kpis'
                union_huawei = f'SELECT cell_name, timestamp, {huawei_inner} FROM huawei_pm.cell_kpis'
            else:
                outer_kpi    = ''
                union_nokia  = 'SELECT cell_name, timestamp FROM nokia_pm.cell_kpis'
                union_huawei = 'SELECT cell_name, timestamp FROM huawei_pm.cell_kpis'

            sql = f'''
                SELECT
                    c.cell_id, c.cell_name, c.technology, c.vendor,
                    c.frequency_band, c.azimuth, c.pci,
                    st.site_id, st.site_name, st.latitude, st.longitude,
                    k.timestamp AS kpi_ts{outer_kpi}
                FROM cells c
                LEFT JOIN sites st ON c.site_id = st.site_id
                LEFT JOIN (
                    {union_nokia}
                    UNION ALL
                    {union_huawei}
                ) k ON k.cell_name = c.cell_name
                    AND k.timestamp = (
                        SELECT MAX(timestamp) FROM (
                            SELECT cell_name, timestamp FROM nokia_pm.cell_kpis
                            UNION ALL
                            SELECT cell_name, timestamp FROM huawei_pm.cell_kpis
                        ) WHERE cell_name = c.cell_name
                    )
                WHERE {where_sql}
                ORDER BY st.site_name, c.cell_name
            '''
            rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

    except sqlite3.OperationalError as e:
        # PM db doesn't exist yet (first run before any sync)
        logger_msg = str(e)
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
    pm_db     = NOKIA_PM_DB if vendor == 'Nokia' else HUAWEI_PM_DB

    try:
        # Only select KPI columns that have real numeric data (not text leftovers)
        kpi_cols = _get_pm_cols(pm_db)
        if kpi_cols:
            col_list = 'cell_name, timestamp, ' + ', '.join(f'"{c}"' for c in kpi_cols)
        else:
            col_list = 'cell_name, timestamp'

        pm_conn = sqlite3.connect(pm_db)
        pm_conn.row_factory = sqlite3.Row
        trend = [dict(r) for r in pm_conn.execute(f'''
            SELECT {col_list}
            FROM cell_kpis
            WHERE cell_name = ?
              AND timestamp >= datetime('now', ? || ' hours')
            ORDER BY timestamp ASC
        ''', (cell_name, f'-{hours}')).fetchall()]
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
