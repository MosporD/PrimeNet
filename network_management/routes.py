"""
Network Management Routes
Provides PCI/PSC/BCCH conflict detection and site cell browser.
"""

from flask import Blueprint, request, jsonify, render_template, redirect, url_for
from functools import wraps
import sqlite3, os

from database_enhanced import get_user_by_session, log_activity
from sync_config import METADATA_DB

network_management_bp = Blueprint(
    'network_management', __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/network_management/static',
)

# Cluster → Area mapping (same as performance module)
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


def _area(site_id):
    try:
        cluster = int(site_id) // 100
        return _CLUSTER_AREA.get(cluster, 'Unknown'), cluster
    except (TypeError, ValueError):
        return 'Unknown', None


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get('session_token')
        if not token:
            return redirect(url_for('auth.login_page'))
        user = get_user_by_session(token)
        if not user:
            return redirect(url_for('auth.login_page'))
        request.current_user = user
        return f(*args, **kwargs)
    return decorated


def get_current_user():
    token = request.cookies.get('session_token')
    return get_user_by_session(token) if token else None


def format_user(user):
    if not user:
        return None
    return {'id': user.get('id'), 'username': user.get('username'), 'role': user.get('role')}


def _meta():
    conn = sqlite3.connect(METADATA_DB, timeout=15)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.row_factory = sqlite3.Row
    return conn


# ── Page ──────────────────────────────────────────────────────────────────────

@network_management_bp.route('/network-management')
@login_required
def network_management_page():
    user = get_current_user()
    return render_template('network_management.html', user=format_user(user))


# ── API: PCI / PSC / BCCH conflict detection ──────────────────────────────────

@network_management_bp.route('/api/network-management/pci-conflicts')
@login_required
def pci_conflicts():
    user = get_current_user()
    technology = request.args.get('technology', '')  # '' = all
    scope = request.args.get('scope', 'area')         # 'area' or 'cluster'

    conn = _meta()
    where = ["c.pci IS NOT NULL", "c.pci != ''", "c.status = 'Active'"]
    params = []
    if technology:
        if technology == '4G':
            where.append("(c.technology = '4G' OR c.technology = '4G-FDD' OR c.technology = '4G-TDD')")
        else:
            where.append('c.technology = ?')
            params.append(technology)

    rows = conn.execute(f'''
        SELECT c.cell_id, c.cell_name, c.technology, c.vendor, c.pci,
               c.azimuth, c.frequency_band,
               s.site_id, s.site_name, s.latitude, s.longitude
        FROM cells c
        LEFT JOIN sites s ON c.site_id = s.site_id
        WHERE {" AND ".join(where)}
        ORDER BY c.pci, s.site_name
    ''', params).fetchall()
    conn.close()

    # Enrich with area
    cells = []
    for r in rows:
        d = dict(r)
        area, cluster = _area(d.get('site_id'))
        d['area'] = area
        d['cluster'] = cluster
        cells.append(d)

    # Group by (pci, area) to find conflicts
    from collections import defaultdict
    groups = defaultdict(list)
    for c in cells:
        key = (c['pci'], c['area'] if scope == 'area' else c['cluster'])
        groups[key].append(c)

    conflicts = []
    for (pci, scope_val), group in groups.items():
        # Filter out groups from different technologies if there's only 1 tech
        if len(group) > 1:
            # Only flag conflict if PCI repeats among different sites
            site_ids = {g['site_id'] for g in group}
            if len(site_ids) > 1:  # Same PCI on different sites = conflict
                conflicts.append({
                    'pci': pci,
                    'scope_label': scope_val,
                    'technology': group[0]['technology'],
                    'cell_count': len(group),
                    'site_count': len(site_ids),
                    'cells': group
                })

    conflicts.sort(key=lambda x: x['cell_count'], reverse=True)
    log_activity(user['id'] if isinstance(user, dict) else user[0],
                 'pci_conflict_check', f'Checked PCI conflicts ({len(conflicts)} found)')
    return jsonify({'success': True, 'conflicts': conflicts, 'total_cells': len(cells)})


# ── API: list all sites with cell counts ─────────────────────────────────────

@network_management_bp.route('/api/network-management/sites')
@login_required
def list_sites():
    technology = request.args.get('technology', '')
    vendor = request.args.get('vendor', '')

    conn = _meta()
    where = ["s.status = 'Active'"]
    params = []
    if vendor:
        where.append('s.vendor = ?')
        params.append(vendor)

    rows = conn.execute(f'''
        SELECT s.site_id, s.site_name, s.latitude, s.longitude, s.vendor,
               COUNT(c.cell_id) as cell_count
        FROM sites s
        LEFT JOIN cells c ON s.site_id = c.site_id
            AND c.status = 'Active'
            {"AND (c.technology = ? OR c.technology LIKE '4G%')" if technology == '4G' else
             "AND c.technology = ?" if technology else ""}
        WHERE {" AND ".join(where)}
        GROUP BY s.site_id
        ORDER BY s.site_name
    ''', params + ([technology] if technology else [])).fetchall()
    conn.close()

    sites = []
    for r in rows:
        d = dict(r)
        area, cluster = _area(d['site_id'])
        d['area'] = area
        d['cluster'] = cluster
        sites.append(d)

    return jsonify({'success': True, 'sites': sites})


# ── API: cells for a specific site ───────────────────────────────────────────

@network_management_bp.route('/api/network-management/site/<site_id>/cells')
@login_required
def site_cells(site_id):
    conn = _meta()
    rows = conn.execute('''
        SELECT c.cell_id, c.cell_name, c.technology, c.vendor,
               c.azimuth, c.pci, c.frequency_band,
               c.electrical_tilt, c.mechanical_tilt,
               s.site_name, s.latitude, s.longitude
        FROM cells c
        LEFT JOIN sites s ON c.site_id = s.site_id
        WHERE c.site_id = ? AND c.status = 'Active'
        ORDER BY c.technology, c.cell_name
    ''', (site_id,)).fetchall()
    conn.close()
    return jsonify({'success': True, 'cells': [dict(r) for r in rows]})


# ── API: summary statistics ───────────────────────────────────────────────────

@network_management_bp.route('/api/network-management/summary')
@login_required
def summary():
    try:
        conn = _meta()
        site_count = conn.execute("SELECT COUNT(*) FROM sites WHERE status='Active'").fetchone()[0]
        cell_count = conn.execute("SELECT COUNT(*) FROM cells WHERE status='Active'").fetchone()[0]

        tech_rows = conn.execute("""
            SELECT technology, COUNT(*) as cnt
            FROM cells WHERE status='Active'
            GROUP BY technology ORDER BY cnt DESC
        """).fetchall()

        vendor_rows = conn.execute("""
            SELECT vendor, COUNT(*) as cnt
            FROM cells WHERE status='Active'
            GROUP BY vendor ORDER BY cnt DESC
        """).fetchall()
        conn.close()

        return jsonify({
            'success': True,
            'site_count': site_count,
            'cell_count': cell_count,
            'by_technology': [dict(r) for r in tech_rows],
            'by_vendor': [dict(r) for r in vendor_rows],
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
