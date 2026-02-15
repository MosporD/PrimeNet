"""
Network Map Routes
Handles network visualization and KPI display
"""

from flask import Blueprint, request, jsonify, render_template, redirect, url_for
from functools import wraps
import sqlite3

from database_enhanced import get_user_by_session, log_activity

network_map_bp = Blueprint('network_map', __name__)

def login_required(f):
    """Decorator to require login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        session_token = request.cookies.get('session_token')
        if not session_token:
            return redirect(url_for('auth.login_page'))

        user = get_user_by_session(session_token)
        if not user:
            return redirect(url_for('auth.login_page'))

        request.current_user = user
        return f(*args, **kwargs)

    return decorated_function

def get_current_user():
    """Get current logged-in user"""
    session_token = request.cookies.get('session_token')
    if session_token:
        return get_user_by_session(session_token)
    return None
def format_user_data(user):
    """Format user data for templates"""
    if not user:
        return None
    if isinstance(user, dict):
        return {'username': user.get('username'), 'email': user.get('email'), 'role': user.get('role'), 'id': user.get('id')}
    return {'username': (user.get('username') if isinstance(user, dict) else user[1]), 'email': (user.get('email') if isinstance(user, dict) else user[2]), 'role': (user.get('role') if isinstance(user, dict) else user[6]), 'id': (user.get('id') if isinstance(user, dict) else user[0])}


@network_map_bp.route('/network-map')
@login_required
def network_map_page():
    """Render Network Map page"""
    user = get_current_user()
    return render_template('network_map.html', user=format_user_data(user))

@network_map_bp.route('/api/map/sites', methods=['GET'])
def get_all_sites():
    """Get all network sites"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        conn = sqlite3.connect('ncm_users.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT site_id, site_name, latitude, longitude, region, site_type, status
            FROM sites
            WHERE status = 'Active'
            ORDER BY site_name
        ''')

        sites = [dict(row) for row in cursor.fetchall()]
        conn.close()

        log_activity((user.get('id') if isinstance(user, dict) else user[0]), 'map_view', 'Viewed network map sites')
        return jsonify({'success': True, 'sites': sites})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@network_map_bp.route('/api/map/site/<site_id>', methods=['GET'])
def get_site_details(site_id):
    """Get detailed information about a specific site"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        conn = sqlite3.connect('ncm_users.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT site_id, site_name, latitude, longitude, region, site_type, status
            FROM sites
            WHERE site_id = ?
        ''', (site_id,))

        site = cursor.fetchone()
        if not site:
            conn.close()
            return jsonify({'error': 'Site not found'}), 404

        site_data = dict(site)

        cursor.execute('''
            SELECT sector_id, sector_name, azimuth, beamwidth, technology, frequency_band, status
            FROM sectors
            WHERE site_id = ? AND status = 'Active'
            ORDER BY sector_name
        ''', (site_id,))

        sectors = [dict(row) for row in cursor.fetchall()]
        site_data['sectors'] = sectors

        conn.close()

        log_activity((user.get('id') if isinstance(user, dict) else user[0]), 'site_view', f'Viewed site {site_id}')
        return jsonify({'success': True, 'site': site_data})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@network_map_bp.route('/api/map/sector/<sector_id>/kpis', methods=['GET'])
def get_sector_kpis(sector_id):
    """Get KPI data for all cells in a sector"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        conn = sqlite3.connect('ncm_users.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT s.sector_id, s.sector_name, s.site_id, s.azimuth, s.beamwidth,
                   s.technology, s.frequency_band, st.site_name
            FROM sectors s
            JOIN sites st ON s.site_id = st.site_id
            WHERE s.sector_id = ?
        ''', (sector_id,))

        sector = cursor.fetchone()
        if not sector:
            conn.close()
            return jsonify({'error': 'Sector not found'}), 404

        sector_data = dict(sector)

        cursor.execute('''
            SELECT cell_id, cell_name, pci, tac, status
            FROM cells
            WHERE sector_id = ?
            ORDER BY cell_name
        ''', (sector_id,))

        cells = [dict(row) for row in cursor.fetchall()]

        for cell in cells:
            cursor.execute('''
                SELECT avg_users, data_volume_gb, rsrp, rsrq, sinr, cqi,
                       throughput_dl_mbps, throughput_ul_mbps, rrc_success_rate,
                       erab_success_rate, call_drop_rate, handover_success_rate,
                       availability_percent, timestamp
                FROM cell_kpis
                WHERE cell_id = ?
                ORDER BY timestamp DESC
                LIMIT 1
            ''', (cell['cell_id'],))

            kpi = cursor.fetchone()
            cell['kpis'] = dict(kpi) if kpi else None

        sector_data['cells'] = cells
        conn.close()

        log_activity((user.get('id') if isinstance(user, dict) else user[0]), 'sector_kpi_view', f'Viewed KPIs for sector {sector_id}')
        return jsonify({'success': True, 'sector': sector_data})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@network_map_bp.route('/api/map/stats', methods=['GET'])
def get_network_stats():
    """Get overall network statistics"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        conn = sqlite3.connect('ncm_users.db')
        cursor = conn.cursor()

        cursor.execute('SELECT COUNT(*) FROM sites WHERE status = "Active"')
        total_sites = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM sectors WHERE status = "Active"')
        total_sectors = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM cells WHERE status = "Active"')
        total_cells = cursor.fetchone()[0]

        cursor.execute('''
            SELECT AVG(k.availability_percent)
            FROM (
                SELECT cell_id, MAX(timestamp) as latest
                FROM cell_kpis
                GROUP BY cell_id
            ) latest_kpis
            JOIN cell_kpis k ON k.cell_id = latest_kpis.cell_id
                            AND k.timestamp = latest_kpis.latest
        ''')

        avg_availability = cursor.fetchone()[0] or 100.0

        conn.close()

        stats = {
            'total_sites': total_sites,
            'total_sectors': total_sectors,
            'total_cells': total_cells,
            'avg_availability': round(avg_availability, 2)
        }

        return jsonify({'success': True, 'stats': stats})

    except Exception as e:
        return jsonify({'error': str(e)}), 500
