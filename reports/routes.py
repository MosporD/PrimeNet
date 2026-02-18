"""
Scheduled Report Generation Routes
Generates Excel reports on demand or on a schedule.
"""

from flask import Blueprint, request, jsonify, render_template, redirect, url_for, send_file
from functools import wraps
import sqlite3, os, io
from datetime import datetime, timedelta

from database_enhanced import get_user_by_session, log_activity
from sync_config import NCMUSERS_DB, METADATA_DB, NOKIA_PM_DB, HUAWEI_PM_DB, PROJECT_ROOT, pm_table_name, PM_TECHNOLOGIES

reports_bp = Blueprint(
    'reports', __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/reports/static',
)

REPORTS_DIR = os.path.join(PROJECT_ROOT, 'generated_reports')
os.makedirs(REPORTS_DIR, exist_ok=True)


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


def _ncm():
    conn = sqlite3.connect(NCMUSERS_DB)
    conn.row_factory = sqlite3.Row
    return conn


def _meta():
    conn = sqlite3.connect(METADATA_DB, timeout=15)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.row_factory = sqlite3.Row
    return conn


# ── Page ──────────────────────────────────────────────────────────────────────

@reports_bp.route('/reports')
@login_required
def reports_page():
    user = get_current_user()
    return render_template('reports.html', user=format_user(user))


# ── Report generators ─────────────────────────────────────────────────────────

def _generate_site_inventory():
    """Excel: one row per cell with all metadata."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        raise RuntimeError('openpyxl is required for report generation')

    conn = _meta()
    rows = conn.execute('''
        SELECT s.site_id, s.site_name, s.latitude, s.longitude, s.vendor as site_vendor,
               c.cell_name, c.technology, c.vendor as cell_vendor,
               c.frequency_band, c.azimuth, c.pci,
               c.electrical_tilt, c.mechanical_tilt
        FROM cells c
        LEFT JOIN sites s ON c.site_id = s.site_id
        WHERE c.status = 'Active'
        ORDER BY s.site_name, c.technology, c.cell_name
    ''').fetchall()
    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.title = 'Site Inventory'

    headers = ['Site ID', 'Site Name', 'Latitude', 'Longitude', 'Vendor',
               'Cell Name', 'Technology', 'Frequency Band', 'Azimuth', 'PCI',
               'E-Tilt', 'M-Tilt']
    hdr_fill = PatternFill(start_color='2C3E50', end_color='2C3E50', fill_type='solid')
    hdr_font = Font(color='FFFFFF', bold=True)

    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = hdr_fill
        cell.font = hdr_font
        cell.alignment = Alignment(horizontal='center')

    for row_idx, r in enumerate(rows, 2):
        ws.append([r['site_id'], r['site_name'], r['latitude'], r['longitude'], r['site_vendor'],
                   r['cell_name'], r['technology'], r['frequency_band'],
                   r['azimuth'], r['pci'], r['electrical_tilt'], r['mechanical_tilt']])

    # Auto-width
    for col in ws.columns:
        max_len = max((len(str(cell.value)) if cell.value else 0) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf, f"Site_Inventory_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx", len(rows)


def _generate_pci_conflicts():
    """Excel: list all PCI conflict groups."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        raise RuntimeError('openpyxl required')

    conn = _meta()
    rows = conn.execute('''
        SELECT c.cell_name, c.technology, c.vendor, c.pci, c.azimuth, c.frequency_band,
               s.site_id, s.site_name, s.latitude, s.longitude
        FROM cells c
        LEFT JOIN sites s ON c.site_id = s.site_id
        WHERE c.pci IS NOT NULL AND c.pci != '' AND c.status = 'Active'
        ORDER BY c.pci, s.site_name
    ''').fetchall()
    conn.close()

    from collections import defaultdict
    groups = defaultdict(list)
    for r in rows:
        groups[r['pci']].append(dict(r))

    conflicts = [(pci, grp) for pci, grp in groups.items() if len({g['site_id'] for g in grp}) > 1]
    conflicts.sort(key=lambda x: len(x[1]), reverse=True)

    wb = Workbook()
    ws = wb.active
    ws.title = 'PCI Conflicts'

    headers = ['PCI', 'Conflict Sites', 'Conflict Cells', 'Cell Name', 'Site', 'Technology', 'Vendor', 'Azimuth', 'Band']
    hdr_fill = PatternFill(start_color='C0392B', end_color='C0392B', fill_type='solid')
    hdr_font = Font(color='FFFFFF', bold=True)
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = hdr_fill
        cell.font = hdr_font

    row_idx = 2
    for pci, grp in conflicts:
        site_count = len({g['site_id'] for g in grp})
        for c in grp:
            ws.append([pci, site_count, len(grp), c['cell_name'], c['site_name'],
                       c['technology'], c['vendor'], c['azimuth'], c['frequency_band']])
            row_idx += 1

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf, f"PCI_Conflicts_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx", len(conflicts)


def _generate_performance_summary():
    """Excel: latest KPI snapshot per cell for all technologies."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
    except ImportError:
        raise RuntimeError('openpyxl required')

    wb = Workbook()
    first = True
    total_rows = 0

    for tech in PM_TECHNOLOGIES:
        table = pm_table_name(tech)
        for db_path, vendor in [(NOKIA_PM_DB, 'Nokia'), (HUAWEI_PM_DB, 'Huawei')]:
            try:
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                cols_info = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
                col_names = [c[1] for c in cols_info]
                if not col_names:
                    conn.close()
                    continue

                rows = conn.execute(f'''
                    SELECT * FROM "{table}"
                    WHERE timestamp = (SELECT MAX(timestamp) FROM "{table}")
                    ORDER BY cell_name
                    LIMIT 5000
                ''').fetchall()
                conn.close()

                if not rows:
                    continue

                ws = wb.active if first else wb.create_sheet()
                ws.title = f'{tech}_{vendor}'[:31]
                first = False

                hdr_fill = PatternFill(start_color='2C3E50', end_color='2C3E50', fill_type='solid')
                hdr_font = Font(color='FFFFFF', bold=True)
                for col_i, name in enumerate(col_names, 1):
                    cell = ws.cell(row=1, column=col_i, value=name)
                    cell.fill = hdr_fill
                    cell.font = hdr_font

                for r in rows:
                    ws.append(list(r))

                total_rows += len(rows)
            except Exception:
                continue

    if first:  # No data at all — create empty sheet
        wb.active.title = 'No Data'
        wb.active.cell(row=1, column=1, value='No performance data available')

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf, f"Performance_Summary_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx", total_rows


def _generate_config_versions_report():
    """Excel: all config versions uploaded."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
    except ImportError:
        raise RuntimeError('openpyxl required')

    conn = _ncm()
    rows = conn.execute('''
        SELECT cv.ne_name, cv.version_num, cv.file_name, cv.comment,
               cv.created_at, u.username as uploaded_by,
               LENGTH(cv.xml_content) as file_size_bytes
        FROM config_versions cv
        LEFT JOIN users u ON cv.uploaded_by = u.id
        ORDER BY cv.ne_name, cv.version_num
    ''').fetchall()
    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.title = 'Config Versions'

    headers = ['NE Name', 'Version', 'File Name', 'Comment', 'Uploaded At', 'Uploaded By', 'Size (bytes)']
    hdr_fill = PatternFill(start_color='1A5276', end_color='1A5276', fill_type='solid')
    hdr_font = Font(color='FFFFFF', bold=True)
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = hdr_fill
        cell.font = hdr_font

    for r in rows:
        ws.append([r['ne_name'], r['version_num'], r['file_name'],
                   r['comment'], r['created_at'], r['uploaded_by'], r['file_size_bytes']])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf, f"Config_Versions_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx", len(rows)


REPORT_TYPES = {
    'site_inventory':     ('Site Inventory',       _generate_site_inventory),
    'pci_conflicts':      ('PCI Conflict Report',  _generate_pci_conflicts),
    'performance_summary':('Performance Summary',  _generate_performance_summary),
    'config_versions':    ('Config Version Log',   _generate_config_versions_report),
}


# ── API: generate on-demand ───────────────────────────────────────────────────

@reports_bp.route('/api/reports/generate', methods=['POST'])
@login_required
def generate_report():
    user = get_current_user()
    data = request.get_json()
    report_type = data.get('report_type', '')

    if report_type not in REPORT_TYPES:
        return jsonify({'error': f'Unknown report type: {report_type}'}), 400

    label, generator = REPORT_TYPES[report_type]
    try:
        buf, filename, row_count = generator()
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    # Save to disk and record in archive
    file_path = os.path.join(REPORTS_DIR, filename)
    with open(file_path, 'wb') as fh:
        fh.write(buf.getvalue())

    conn = _ncm()
    conn.execute('''
        INSERT INTO report_archive (report_name, report_type, file_path, file_size, generated_by)
        VALUES (?, ?, ?, ?, ?)
    ''', (filename, report_type, file_path, os.path.getsize(file_path), user['id']))
    archive_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.commit()
    conn.close()

    log_activity(user['id'], 'report_generated', f'Generated {label} report ({row_count} rows)')
    return jsonify({'success': True, 'archive_id': archive_id, 'filename': filename, 'rows': row_count})


# ── API: download report ──────────────────────────────────────────────────────

@reports_bp.route('/api/reports/download/<int:report_id>')
@login_required
def download_report(report_id):
    conn = _ncm()
    row = conn.execute('SELECT * FROM report_archive WHERE id = ?', (report_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'Report not found'}), 404
    row = dict(row)
    if not os.path.exists(row['file_path']):
        return jsonify({'error': 'Report file no longer exists on disk'}), 404
    return send_file(row['file_path'], as_attachment=True, download_name=row['report_name'],
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# ── API: report archive ───────────────────────────────────────────────────────

@reports_bp.route('/api/reports/archive')
@login_required
def report_archive():
    conn = _ncm()
    rows = conn.execute('''
        SELECT ra.id, ra.report_name, ra.report_type, ra.file_size, ra.generated_at,
               u.username as generated_by_name
        FROM report_archive ra
        LEFT JOIN users u ON ra.generated_by = u.id
        ORDER BY ra.generated_at DESC
        LIMIT 100
    ''').fetchall()
    conn.close()
    return jsonify({'success': True, 'reports': [dict(r) for r in rows]})


# ── API: delete report from archive ──────────────────────────────────────────

@reports_bp.route('/api/reports/archive/<int:report_id>', methods=['DELETE'])
@login_required
def delete_report(report_id):
    user = get_current_user()
    conn = _ncm()
    row = conn.execute('SELECT * FROM report_archive WHERE id = ?', (report_id,)).fetchone()
    if row:
        try:
            if os.path.exists(row['file_path']):
                os.remove(row['file_path'])
        except OSError:
            pass
        conn.execute('DELETE FROM report_archive WHERE id = ?', (report_id,))
        conn.commit()
    conn.close()
    return jsonify({'success': True})


# ── API: list report types ────────────────────────────────────────────────────

@reports_bp.route('/api/reports/types')
@login_required
def report_types():
    return jsonify({
        'success': True,
        'types': [{'id': k, 'label': v[0]} for k, v in REPORT_TYPES.items()]
    })
