"""
Performance Routes
==================
Three-database architecture:
  metadata.db   → sites, cells (source of truth, all vendors)
  nokia_pm.db   → Nokia hourly KPIs keyed by cell_name
  huawei_pm.db  → Huawei hourly KPIs keyed by cell_name

Queries open metadata.db and ATTACH the relevant PM db so SQLite
can do cross-db JOINs on cell_name without any application-level merge.
"""

from flask import Blueprint, request, jsonify, render_template, redirect, url_for
from functools import wraps
import sqlite3

from database_enhanced import get_user_by_session, log_activity

performance_bp = Blueprint('performance', __name__)

METADATA_DB  = 'metadata.db'
NOKIA_PM_DB  = 'nokia_pm.db'
HUAWEI_PM_DB = 'huawei_pm.db'


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
# DB connection helpers
# ---------------------------------------------------------------------------

def _meta_conn():
    """Open metadata.db with row_factory."""
    conn = sqlite3.connect(METADATA_DB)
    conn.row_factory = sqlite3.Row
    return conn


def _pm_conn(vendor=None):
    """
    Open metadata.db and ATTACH the right PM db based on vendor.
    If vendor is None or 'all', ATTACH both as nokia_pm and huawei_pm.
    Returns (conn, attached_alias_or_None).
    """
    conn = sqlite3.connect(METADATA_DB)
    conn.row_factory = sqlite3.Row

    if vendor == 'Nokia':
        conn.execute(f"ATTACH DATABASE '{NOKIA_PM_DB}'  AS pm")
        return conn, 'pm'
    elif vendor == 'Huawei':
        conn.execute(f"ATTACH DATABASE '{HUAWEI_PM_DB}' AS pm")
        return conn, 'pm'
    else:
        # Both attached under separate aliases
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
# API: filter options (regions, technologies, sites) — from metadata.db
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

    sites = [dict(r) for r in conn.execute(
        "SELECT site_id, site_name, region, vendor FROM sites WHERE status='Active' ORDER BY site_name"
    ).fetchall()]

    conn.close()
    return jsonify({'success': True, 'regions': regions, 'sites': sites})


# ---------------------------------------------------------------------------
# API: cells list with latest KPI snapshot
# Vendor filter decides which PM db to ATTACH.
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

    # Build WHERE clause for metadata.db cells table
    where  = ["c.status = 'Active'"]
    params = []

    if vendor:
        where.append('c.vendor = ?')
        params.append(vendor)
    if technology:
        # 4G matches both 4G-FDD and 4G-TDD
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

    where_sql = ' AND '.join(where)

    conn, pm_alias = _pm_conn(vendor if vendor else None)

    try:
        if pm_alias:
            # Single vendor — ATTACH as 'pm'
            sql = f'''
                SELECT
                    c.cell_id, c.cell_name, c.technology, c.vendor,
                    c.frequency_band, c.azimuth, c.pci,
                    st.site_id, st.site_name, st.region, st.latitude, st.longitude,
                    k.avg_users, k.data_volume_gb, k.rsrp, k.rsrq, k.sinr,
                    k.throughput_dl_mbps, k.throughput_ul_mbps,
                    k.rrc_success_rate, k.erab_success_rate,
                    k.call_drop_rate, k.handover_success_rate,
                    k.availability_percent, k.timestamp AS kpi_ts
                FROM cells c
                JOIN sites st ON c.site_id = st.site_id
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
            # Both vendors — UNION from each PM db
            sql = f'''
                SELECT
                    c.cell_id, c.cell_name, c.technology, c.vendor,
                    c.frequency_band, c.azimuth, c.pci,
                    st.site_id, st.site_name, st.region, st.latitude, st.longitude,
                    k.avg_users, k.data_volume_gb, k.rsrp, k.rsrq, k.sinr,
                    k.throughput_dl_mbps, k.throughput_ul_mbps,
                    k.rrc_success_rate, k.erab_success_rate,
                    k.call_drop_rate, k.handover_success_rate,
                    k.availability_percent, k.timestamp AS kpi_ts
                FROM cells c
                JOIN sites st ON c.site_id = st.site_id
                LEFT JOIN (
                    SELECT * FROM nokia_pm.cell_kpis
                    UNION ALL
                    SELECT * FROM huawei_pm.cell_kpis
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
        # PM db might not exist yet (first run before any sync)
        rows = [dict(r) for r in conn.execute(f'''
            SELECT
                c.cell_id, c.cell_name, c.technology, c.vendor,
                c.frequency_band, c.azimuth, c.pci,
                st.site_id, st.site_name, st.region, st.latitude, st.longitude,
                NULL as avg_users, NULL as data_volume_gb,
                NULL as rsrp, NULL as rsrq, NULL as sinr,
                NULL as throughput_dl_mbps, NULL as throughput_ul_mbps,
                NULL as rrc_success_rate, NULL as erab_success_rate,
                NULL as call_drop_rate, NULL as handover_success_rate,
                NULL as availability_percent, NULL as kpi_ts
            FROM cells c
            JOIN sites st ON c.site_id = st.site_id
            WHERE {where_sql}
            ORDER BY st.site_name, c.cell_name
        ''', params).fetchall()]

    finally:
        conn.close()

    log_activity(_user_id(user), 'performance_view', 'Viewed performance cells list')
    return jsonify({'success': True, 'cells': rows})


# ---------------------------------------------------------------------------
# API: time-series KPI trend for a single cell
# cell_id is from metadata.db; we look up vendor to pick the right PM db.
# ---------------------------------------------------------------------------

@performance_bp.route('/api/performance/cell/<int:cell_id>/trend', methods=['GET'])
def get_cell_trend(cell_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    hours = min(request.args.get('hours', 168, type=int), 168)

    # Step 1: look up cell metadata (includes vendor)
    meta_conn = _meta_conn()
    cell = meta_conn.execute('''
        SELECT c.cell_id, c.cell_name, c.technology, c.vendor,
               c.frequency_band, c.azimuth, c.mechanical_tilt, c.pci,
               st.site_id, st.site_name, st.region, st.latitude, st.longitude
        FROM cells c
        JOIN sites st ON c.site_id = st.site_id
        WHERE c.cell_id = ?
    ''', (cell_id,)).fetchone()
    meta_conn.close()

    if not cell:
        return jsonify({'error': 'Cell not found'}), 404

    cell     = dict(cell)
    vendor   = cell.get('vendor')
    cell_name = cell['cell_name']
    pm_db    = NOKIA_PM_DB if vendor == 'Nokia' else HUAWEI_PM_DB

    # Step 2: query the right PM db for the time series
    try:
        pm_conn = sqlite3.connect(pm_db)
        pm_conn.row_factory = sqlite3.Row
        trend = [dict(r) for r in pm_conn.execute('''
            SELECT timestamp,
                   avg_users, data_volume_gb, rsrp, rsrq, sinr, cqi,
                   throughput_dl_mbps, throughput_ul_mbps,
                   rrc_success_rate, erab_success_rate,
                   call_drop_rate, handover_success_rate,
                   availability_percent
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
# API: sync trigger (Nokia/Huawei/Metadata) exposed for admin panel
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
