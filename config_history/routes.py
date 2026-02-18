"""
Config Version History Routes
Handles uploading, versioning, diffing, and downloading XML config files.
"""

from flask import Blueprint, request, jsonify, render_template, redirect, url_for, send_file
from werkzeug.utils import secure_filename
from functools import wraps
import os, io, difflib, sqlite3

from database_enhanced import get_user_by_session, log_activity
from sync_config import NCMUSERS_DB

config_history_bp = Blueprint(
    'config_history', __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/config_history/static',
)


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


def _db():
    conn = sqlite3.connect(NCMUSERS_DB)
    conn.row_factory = sqlite3.Row
    return conn


# ── Page ──────────────────────────────────────────────────────────────────────

@config_history_bp.route('/config-history')
@login_required
def config_history_page():
    user = get_current_user()
    return render_template('config_history.html', user=format_user(user))


# ── API: upload new version ────────────────────────────────────────────────────

@config_history_bp.route('/api/config-history/upload', methods=['POST'])
@login_required
def upload_version():
    user = get_current_user()
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    f = request.files['file']
    comment = request.form.get('comment', '')
    if not f.filename.lower().endswith('.xml'):
        return jsonify({'error': 'Only XML files are allowed'}), 400

    filename = secure_filename(f.filename)
    ne_name = os.path.splitext(filename)[0]
    xml_content = f.read().decode('utf-8', errors='replace')

    conn = _db()
    cur = conn.cursor()
    cur.execute(
        'SELECT COALESCE(MAX(version_num), 0) + 1 FROM config_versions WHERE ne_name = ?',
        (ne_name,)
    )
    version_num = cur.fetchone()[0]

    cur.execute('''
        INSERT INTO config_versions (ne_name, file_name, version_num, xml_content, comment, uploaded_by)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (ne_name, filename, version_num, xml_content, comment, user['id']))
    version_id = cur.lastrowid
    conn.commit()
    conn.close()

    log_activity(user['id'], 'config_upload', f'Uploaded version {version_num} for {ne_name}')
    return jsonify({'success': True, 'version_id': version_id, 'version_num': version_num, 'ne_name': ne_name})


# ── API: list NEs ──────────────────────────────────────────────────────────────

@config_history_bp.route('/api/config-history/list')
@login_required
def list_nes():
    conn = _db()
    rows = conn.execute('''
        SELECT ne_name, COUNT(*) as version_count,
               MAX(created_at) as last_updated,
               MAX(version_num) as latest_version
        FROM config_versions
        GROUP BY ne_name
        ORDER BY last_updated DESC
    ''').fetchall()
    conn.close()
    return jsonify({'success': True, 'nes': [dict(r) for r in rows]})


# ── API: list versions for a specific NE ──────────────────────────────────────

@config_history_bp.route('/api/config-history/<ne_name>/versions')
@login_required
def list_versions(ne_name):
    conn = _db()
    rows = conn.execute('''
        SELECT cv.id, cv.version_num, cv.file_name, cv.comment, cv.created_at,
               u.username as uploaded_by_name,
               LENGTH(cv.xml_content) as content_length
        FROM config_versions cv
        LEFT JOIN users u ON cv.uploaded_by = u.id
        WHERE cv.ne_name = ?
        ORDER BY cv.version_num DESC
    ''', (ne_name,)).fetchall()
    conn.close()
    return jsonify({'success': True, 'ne_name': ne_name, 'versions': [dict(r) for r in rows]})


# ── API: diff two versions ─────────────────────────────────────────────────────

@config_history_bp.route('/api/config-history/diff', methods=['POST'])
@login_required
def diff_versions():
    data = request.get_json()
    v1_id = data.get('version1_id')
    v2_id = data.get('version2_id')
    if not v1_id or not v2_id:
        return jsonify({'error': 'Both version IDs required'}), 400

    conn = _db()
    v1 = conn.execute('SELECT * FROM config_versions WHERE id = ?', (v1_id,)).fetchone()
    v2 = conn.execute('SELECT * FROM config_versions WHERE id = ?', (v2_id,)).fetchone()
    conn.close()

    if not v1 or not v2:
        return jsonify({'error': 'Version not found'}), 404

    v1, v2 = dict(v1), dict(v2)
    lines1 = v1['xml_content'].splitlines()
    lines2 = v2['xml_content'].splitlines()

    diff_lines = list(difflib.unified_diff(
        lines1, lines2,
        fromfile=f"v{v1['version_num']} ({v1['created_at'][:10]})",
        tofile=f"v{v2['version_num']} ({v2['created_at'][:10]})",
        lineterm=''
    ))

    added   = sum(1 for l in diff_lines if l.startswith('+') and not l.startswith('+++'))
    removed = sum(1 for l in diff_lines if l.startswith('-') and not l.startswith('---'))

    return jsonify({
        'success': True,
        'diff': '\n'.join(diff_lines),
        'v1': {'version_num': v1['version_num'], 'ne_name': v1['ne_name'], 'created_at': v1['created_at']},
        'v2': {'version_num': v2['version_num'], 'ne_name': v2['ne_name'], 'created_at': v2['created_at']},
        'stats': {
            'added': added,
            'removed': removed,
            'total_lines_v1': len(lines1),
            'total_lines_v2': len(lines2)
        }
    })


# ── API: download a specific version ──────────────────────────────────────────

@config_history_bp.route('/api/config-history/version/<int:version_id>/download')
@login_required
def download_version(version_id):
    user = get_current_user()
    conn = _db()
    row = conn.execute('SELECT * FROM config_versions WHERE id = ?', (version_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'Version not found'}), 404
    row = dict(row)
    log_activity(user['id'], 'config_download', f"Downloaded v{row['version_num']} of {row['ne_name']}")
    buf = io.BytesIO(row['xml_content'].encode('utf-8'))
    buf.seek(0)
    fname = f"{row['ne_name']}_v{row['version_num']}.xml"
    return send_file(buf, as_attachment=True, download_name=fname, mimetype='application/xml')


# ── API: delete a version (admin only) ────────────────────────────────────────

@config_history_bp.route('/api/config-history/version/<int:version_id>', methods=['DELETE'])
@login_required
def delete_version(version_id):
    user = get_current_user()
    if user.get('role') != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    conn = _db()
    conn.execute('DELETE FROM config_versions WHERE id = ?', (version_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})
