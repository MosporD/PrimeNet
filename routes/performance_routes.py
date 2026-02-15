"""
Performance Routes
Standalone performance analytics page with KPI trends per cell.
"""

from flask import Blueprint, request, jsonify, render_template, redirect, url_for
from functools import wraps
import sqlite3

from database_enhanced import get_user_by_session, log_activity

performance_bp = Blueprint('performance', __name__)


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


@performance_bp.route('/performance')
@login_required
def performance_page():
    user = get_current_user()
    return render_template('performance.html', user=format_user(user))


# ---------------------------------------------------------------------------
# API: filter options
# ---------------------------------------------------------------------------

@performance_bp.route('/api/performance/filters', methods=['GET'])
def get_filters():
    """Return available regions, technologies, and sites for filter dropdowns."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    conn = sqlite3.connect('ncm_users.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT DISTINCT region FROM sites WHERE region IS NOT NULL ORDER BY region")
    regions = [r['region'] for r in cursor.fetchall()]

    cursor.execute("SELECT DISTINCT technology FROM sectors WHERE technology IS NOT NULL ORDER BY technology")
    technologies = [r['technology'] for r in cursor.fetchall()]

    cursor.execute("SELECT site_id, site_name, region FROM sites WHERE status='Active' ORDER BY site_name")
    sites = [dict(r) for r in cursor.fetchall()]

    conn.close()
    return jsonify({'success': True, 'regions': regions, 'technologies': technologies, 'sites': sites})


# ---------------------------------------------------------------------------
# API: cells list with latest KPI snapshot
# ---------------------------------------------------------------------------

@performance_bp.route('/api/performance/cells', methods=['GET'])
def get_cells():
    """Return cells with their latest KPI snapshot, filtered by tech/site/region."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    technology = request.args.get('technology', '')
    site_id    = request.args.get('site_id', '')
    region     = request.args.get('region', '')

    where = ['c.status = "Active"']
    params = []

    if technology:
        where.append('sec.technology = ?')
        params.append(technology)
    if site_id:
        where.append('st.site_id = ?')
        params.append(site_id)
    if region:
        where.append('st.region = ?')
        params.append(region)

    where_clause = ' AND '.join(where)

    conn = sqlite3.connect('ncm_users.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(f'''
        SELECT
            c.cell_id, c.cell_name, c.pci,
            sec.sector_id, sec.sector_name, sec.technology, sec.frequency_band, sec.azimuth,
            st.site_id, st.site_name, st.region,
            k.avg_users, k.data_volume_gb, k.rsrp, k.rsrq, k.sinr, k.cqi,
            k.throughput_dl_mbps, k.throughput_ul_mbps,
            k.rrc_success_rate, k.erab_success_rate,
            k.call_drop_rate, k.handover_success_rate,
            k.availability_percent, k.timestamp
        FROM cells c
        JOIN sectors sec ON c.sector_id = sec.sector_id
        JOIN sites   st  ON sec.site_id  = st.site_id
        LEFT JOIN cell_kpis k ON k.cell_id = c.cell_id
            AND k.timestamp = (
                SELECT MAX(timestamp) FROM cell_kpis WHERE cell_id = c.cell_id
            )
        WHERE {where_clause}
        ORDER BY st.site_name, c.cell_name
    ''', params)

    cells = [dict(r) for r in cursor.fetchall()]
    conn.close()

    log_activity(
        (user.get('id') if isinstance(user, dict) else user[0]),
        'performance_view', 'Viewed performance page'
    )
    return jsonify({'success': True, 'cells': cells})


# ---------------------------------------------------------------------------
# API: time-series KPI trend for a single cell
# ---------------------------------------------------------------------------

@performance_bp.route('/api/performance/cell/<cell_id>/trend', methods=['GET'])
def get_cell_trend(cell_id):
    """Return hourly KPI trend for a cell over the requested time range."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    hours = request.args.get('hours', 24, type=int)
    hours = min(hours, 168)  # cap at 1 week

    conn = sqlite3.connect('ncm_users.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Cell meta
    cursor.execute('''
        SELECT c.cell_id, c.cell_name, c.pci,
               sec.technology, sec.frequency_band,
               st.site_name, st.site_id
        FROM cells c
        JOIN sectors sec ON c.sector_id = sec.sector_id
        JOIN sites   st  ON sec.site_id  = st.site_id
        WHERE c.cell_id = ?
    ''', (cell_id,))
    cell = cursor.fetchone()
    if not cell:
        conn.close()
        return jsonify({'error': 'Cell not found'}), 404

    # Time series
    cursor.execute('''
        SELECT timestamp,
               avg_users, data_volume_gb, rsrp, rsrq, sinr, cqi,
               throughput_dl_mbps, throughput_ul_mbps,
               rrc_success_rate, erab_success_rate,
               call_drop_rate, handover_success_rate,
               availability_percent
        FROM cell_kpis
        WHERE cell_id = ?
          AND timestamp >= datetime('now', ? || ' hours')
        ORDER BY timestamp ASC
    ''', (cell_id, f'-{hours}'))

    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    return jsonify({'success': True, 'cell': dict(cell), 'trend': rows})
