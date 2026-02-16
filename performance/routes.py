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
# One-time schema migration: add cluster / area to sites if missing
# ---------------------------------------------------------------------------

def _ensure_cluster_area_cols():
    try:
        conn = sqlite3.connect(METADATA_DB, timeout=15)
        existing = {r[1] for r in conn.execute('PRAGMA table_info(sites)').fetchall()}
        if 'cluster' not in existing:
            conn.execute('ALTER TABLE sites ADD COLUMN cluster TEXT')
        if 'area' not in existing:
            conn.execute('ALTER TABLE sites ADD COLUMN area TEXT')
        conn.commit()
        conn.close()
    except Exception:
        pass

_ensure_cluster_area_cols()


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
    """Return KPI column names from a PM db (excludes id, cell_name, timestamp)."""
    try:
        conn = sqlite3.connect(db_path)
        cols = [r[1] for r in conn.execute('PRAGMA table_info(cell_kpis)').fetchall()
                if r[1] not in _FIXED_COLS]
        conn.close()
        return cols
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

    regions = [r['region'] for r in conn.execute(
        "SELECT DISTINCT region FROM sites WHERE region IS NOT NULL ORDER BY region"
    ).fetchall()]

    clusters = [r['cluster'] for r in conn.execute(
        "SELECT DISTINCT cluster FROM sites WHERE cluster IS NOT NULL ORDER BY cluster"
    ).fetchall()]

    areas = [dict(r) for r in conn.execute(
        "SELECT DISTINCT cluster, area FROM sites WHERE area IS NOT NULL ORDER BY cluster, area"
    ).fetchall()]

    sites = [dict(r) for r in conn.execute(
        "SELECT site_id, site_name, region, cluster, area, vendor FROM sites WHERE status='Active' ORDER BY site_name"
    ).fetchall()]

    conn.close()
    return jsonify({'success': True, 'regions': regions, 'clusters': clusters, 'areas': areas, 'sites': sites})


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
    region     = request.args.get('region', '')
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
    if region:
        where.append('st.region = ?')
        params.append(region)
    if cluster:
        where.append('st.cluster = ?')
        params.append(cluster)
    if area:
        where.append('st.area = ?')
        params.append(area)

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
                    st.site_id, st.site_name, st.region, st.cluster, st.area, st.latitude, st.longitude,
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
                    st.site_id, st.site_name, st.region, st.cluster, st.area, st.latitude, st.longitude,
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
                st.site_id, st.site_name, st.region, st.cluster, st.area,
                st.latitude, st.longitude, NULL AS kpi_ts
            FROM cells c
            LEFT JOIN sites st ON c.site_id = st.site_id
            WHERE {where_sql}
            ORDER BY st.site_name, c.cell_name
        ''', params).fetchall()]

    finally:
        conn.close()

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
               st.site_id, st.site_name, st.region, st.cluster, st.area,
               st.latitude, st.longitude
        FROM cells c
        LEFT JOIN sites st ON c.site_id = st.site_id
        WHERE c.cell_id = ?
    ''', (cell_id,)).fetchone()
    meta_conn.close()

    if not cell:
        return jsonify({'error': 'Cell not found'}), 404

    cell      = dict(cell)
    vendor    = cell.get('vendor')
    cell_name = cell['cell_name']
    pm_db     = NOKIA_PM_DB if vendor == 'Nokia' else HUAWEI_PM_DB

    try:
        pm_conn = sqlite3.connect(pm_db)
        pm_conn.row_factory = sqlite3.Row
        # SELECT * returns all KPI columns dynamically — no hardcoding needed
        trend = [dict(r) for r in pm_conn.execute('''
            SELECT *
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
