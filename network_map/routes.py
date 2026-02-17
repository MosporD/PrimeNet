"""
Network Map Routes
Handles network visualization and KPI display
"""

from flask import Blueprint, request, jsonify, render_template, redirect, url_for
from functools import wraps
import sqlite3, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sync_config import NOKIA_PM_DB, HUAWEI_PM_DB, METADATA_DB, pm_table_name
from database_enhanced import get_user_by_session, log_activity

network_map_bp = Blueprint(
    'network_map', __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/network_map/static',
)


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
    """Get all network sites from metadata.db, optionally filtered by technology."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    tech = request.args.get('tech', '').strip()

    try:
        conn = sqlite3.connect(METADATA_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if tech and tech != 'all':
            cursor.execute('''
                SELECT DISTINCT s.site_id, s.site_name, s.latitude, s.longitude,
                       s.region, s.site_type, s.vendor, s.status
                FROM sites s
                JOIN cells c ON s.site_id = c.site_id
                WHERE s.status = 'Active' AND c.technology = ? AND c.status = 'Active'
                  AND s.latitude IS NOT NULL AND s.longitude IS NOT NULL
                ORDER BY s.site_name
            ''', (tech,))
        else:
            cursor.execute('''
                SELECT site_id, site_name, latitude, longitude, region, site_type, vendor, status
                FROM sites
                WHERE status = 'Active' AND latitude IS NOT NULL AND longitude IS NOT NULL
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
        conn = sqlite3.connect(METADATA_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT site_id, site_name, latitude, longitude, region, site_type, vendor, status
            FROM sites
            WHERE site_id = ?
        ''', (site_id,))

        site = cursor.fetchone()
        if not site:
            conn.close()
            return jsonify({'error': 'Site not found'}), 404

        site_data = dict(site)

        # Cells are the sectors — query them with all fields needed for map drawing
        cursor.execute('''
            SELECT cell_id, cell_name, technology, vendor, frequency_band,
                   azimuth, mechanical_tilt, electrical_tilt, pci, status
            FROM cells
            WHERE site_id = ? AND status = 'Active'
            ORDER BY technology, cell_name
        ''', (site_id,))
        site_data['cells'] = [dict(row) for row in cursor.fetchall()]

        conn.close()

        log_activity((user.get('id') if isinstance(user, dict) else user[0]), 'site_view', f'Viewed site {site_id}')
        return jsonify({'success': True, 'site': site_data})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@network_map_bp.route('/api/map/cell/<int:cell_id>/kpis', methods=['GET'])
def get_cell_kpis(cell_id):
    """Get the latest KPI snapshot for a cell from the appropriate PM database."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        meta_conn = sqlite3.connect(METADATA_DB)
        meta_conn.row_factory = sqlite3.Row
        cell = meta_conn.execute('''
            SELECT c.cell_id, c.cell_name, c.technology, c.vendor,
                   c.azimuth, c.mechanical_tilt, c.electrical_tilt, c.pci,
                   st.site_id, st.site_name, st.region
            FROM cells c
            LEFT JOIN sites st ON c.site_id = st.site_id
            WHERE c.cell_id = ?
        ''', (cell_id,)).fetchone()
        meta_conn.close()

        if not cell:
            return jsonify({'error': 'Cell not found'}), 404

        cell_data = dict(cell)
        vendor    = cell_data.get('vendor', '')
        cell_name = cell_data['cell_name']
        cell_tech = cell_data.get('technology', '4G')
        pm_db     = NOKIA_PM_DB if vendor == 'Nokia' else HUAWEI_PM_DB
        table     = pm_table_name(cell_tech)

        try:
            pm_conn = sqlite3.connect(pm_db)
            pm_conn.row_factory = sqlite3.Row
            kpi = pm_conn.execute(f'''
                SELECT *
                FROM "{table}"
                WHERE cell_name = ?
                ORDER BY timestamp DESC
                LIMIT 1
            ''', (cell_name,)).fetchone()
            pm_conn.close()
            cell_data['kpis'] = dict(kpi) if kpi else None
        except sqlite3.OperationalError:
            cell_data['kpis'] = None

        log_activity((user.get('id') if isinstance(user, dict) else user[0]),
                     'cell_kpi_view', f'Viewed KPIs for cell {cell_name}')
        return jsonify({'success': True, 'cell': cell_data})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@network_map_bp.route('/api/map/stats', methods=['GET'])
def get_network_stats():
    """Get overall network statistics from metadata.db"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        conn = sqlite3.connect(METADATA_DB)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM sites WHERE status = 'Active'")
        total_sites = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM cells WHERE status = 'Active'")
        total_cells = cursor.fetchone()[0]

        cursor.execute('''
            SELECT technology, COUNT(*) FROM cells
            WHERE status = 'Active' GROUP BY technology ORDER BY technology
        ''')
        tech_counts = {row[0]: row[1] for row in cursor.fetchall()}

        conn.close()

        return jsonify({'success': True, 'stats': {
            'total_sites':   total_sites,
            'total_sectors': total_cells,
            'total_cells':   total_cells,
            'tech_counts':   tech_counts,
        }})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@network_map_bp.route('/api/map/search/cell-code', methods=['GET'])
def search_by_cell_code():
    """Search cells by PCI (4G), Scrambling Code (3G), or BCCH (2G) stored in the pci column."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    code = request.args.get('code', '').strip()
    tech = request.args.get('tech', '').strip()

    if not code or not code.lstrip('-').isdigit():
        return jsonify({'success': True, 'matches': []})

    try:
        conn = sqlite3.connect(METADATA_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = '''
            SELECT c.cell_id, c.cell_name, c.technology, c.vendor, c.frequency_band,
                   c.azimuth, c.mechanical_tilt, c.electrical_tilt, c.pci,
                   s.site_id, s.site_name, s.latitude, s.longitude
            FROM cells c
            JOIN sites s ON c.site_id = s.site_id
            WHERE c.pci = ? AND c.status = 'Active'
              AND s.status = 'Active'
              AND s.latitude IS NOT NULL AND s.longitude IS NOT NULL
        '''
        params = [int(code)]

        if tech and tech != 'all':
            query += ' AND c.technology = ?'
            params.append(tech)

        query += ' ORDER BY s.site_name, c.technology, c.cell_name'

        cursor.execute(query, params)
        matches = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return jsonify({'success': True, 'matches': matches})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@network_map_bp.route('/api/map/export/cell-code', methods=['GET'])
@login_required
def export_cell_code():
    """Export cells matching a PCI / SC / BCCH code as an Excel file."""
    from io import BytesIO
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from flask import send_file

    code = request.args.get('code', '').strip()
    tech = request.args.get('tech', '').strip()

    if not code or not code.lstrip('-').isdigit():
        return jsonify({'error': 'Invalid code'}), 400

    try:
        conn = sqlite3.connect(METADATA_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = '''
            SELECT c.cell_name, s.site_name, s.site_id, c.technology, c.vendor,
                   c.frequency_band, c.pci, c.azimuth, c.mechanical_tilt,
                   c.electrical_tilt, s.latitude, s.longitude
            FROM cells c
            JOIN sites s ON c.site_id = s.site_id
            WHERE c.pci = ? AND c.status = 'Active'
              AND s.status = 'Active'
              AND s.latitude IS NOT NULL AND s.longitude IS NOT NULL
        '''
        params = [int(code)]
        if tech and tech != 'all':
            query += ' AND c.technology = ?'
            params.append(tech)
        query += ' ORDER BY s.site_name, c.technology, c.cell_name'

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        code_label = 'PSC' if tech == '3G' else ('BCCH' if tech == '2G' else 'PCI')

        wb  = openpyxl.Workbook()
        ws  = wb.active
        ws.title = f'{code_label}_{code}'

        headers = ['Cell Name', 'Site Name', 'Site ID', 'Technology', 'Vendor',
                   'Band', code_label, 'Azimuth (°)', 'M.Tilt (°)', 'E.Tilt (°)',
                   'Latitude', 'Longitude']
        ws.append(headers)

        hdr_fill = PatternFill(start_color='1F4E79', end_color='1F4E79', fill_type='solid')
        for cell in ws[1]:
            cell.font      = Font(bold=True, color='FFFFFF')
            cell.fill      = hdr_fill
            cell.alignment = Alignment(horizontal='center')

        for row in rows:
            ws.append([
                row['cell_name'], row['site_name'], row['site_id'],
                row['technology'], row['vendor'], row['frequency_band'],
                row['pci'], row['azimuth'], row['mechanical_tilt'],
                row['electrical_tilt'], row['latitude'], row['longitude']
            ])

        for col in ws.columns:
            max_len = max((len(str(c.value or '')) for c in col), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)

        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)

        uid = (request.current_user.get('id')
               if isinstance(request.current_user, dict)
               else request.current_user[0])
        log_activity(uid, 'export', f'Exported {len(rows)} cells with {code_label}={code}')

        return send_file(
            buf,
            download_name=f'{code_label}_{code}_cells.xlsx',
            as_attachment=True,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@network_map_bp.route('/api/map/refresh', methods=['POST'])
@login_required
def refresh_metadata():
    """Trigger a metadata sync in the background and return immediately."""
    import threading
    try:
        from sync.scheduler import trigger_metadata_now
        t = threading.Thread(target=trigger_metadata_now, daemon=True)
        t.start()
        uid = (request.current_user.get('id')
               if isinstance(request.current_user, dict)
               else request.current_user[0])
        log_activity(uid, 'metadata_refresh', 'Triggered metadata refresh from network map')
        return jsonify({'success': True, 'message': 'Metadata sync started'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
