"""
User Profile & Dashboard Personalization Routes
Allows users to update their profile, change password, and customize the dashboard.
"""

from flask import Blueprint, request, jsonify, render_template, redirect, url_for
from functools import wraps
import sqlite3
import json
import os
import uuid
from werkzeug.utils import secure_filename

from database_enhanced import (
    get_db,
    get_user_by_session,
    hash_password,
    log_activity,
    verify_password,
    _unique_constraint_error,
)
from core.user_vendor_credentials import (
    delete_user_vendor_credentials,
    list_user_vendor_credential_status,
    save_user_vendor_credentials,
)
from db.runtime import execute_query
from sync_config import PROJECT_ROOT

user_profile_bp = Blueprint(
    'user_profile', __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/user_profile/static',
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
    return {
        'id':         user.get('id'),
        'username':   user.get('username'),
        'email':      user.get('email'),
        'full_name':  user.get('full_name'),
        'department': user.get('department'),
        'role':       user.get('role'),
        'created_at': user.get('created_at'),
        'last_login': user.get('last_login'),
    }


def _db():
    conn = get_db()
    if isinstance(conn, sqlite3.Connection):
        conn.row_factory = sqlite3.Row
    return conn


_PROFILE_PHOTO_DIR = os.path.join(PROJECT_ROOT, 'uploads', 'profile_photos')
_PHOTO_APPROVER_ROLES = {'admin', 'noc_sys'}


def _ensure_profile_photo_schema(conn):
    if not isinstance(conn, sqlite3.Connection):
        return
    conn.execute('''
        CREATE TABLE IF NOT EXISTS profile_photo_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            original_file_name TEXT NOT NULL,
            stored_file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reviewed_by INTEGER,
            reviewed_at TIMESTAMP,
            review_note TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (reviewed_by) REFERENCES users(id)
        )
    ''')
    cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    if 'profile_photo_path' not in cols:
        conn.execute('ALTER TABLE users ADD COLUMN profile_photo_path TEXT')


def _can_approve_photo(user):
    return (user.get('role') or '').lower() in _PHOTO_APPROVER_ROLES


# ── Page ──────────────────────────────────────────────────────────────────────

@user_profile_bp.route('/profile')
@login_required
def profile_page():
    user = get_current_user()
    return render_template('user_profile.html', user=format_user(user))


# ── API: get full profile ─────────────────────────────────────────────────────

@user_profile_bp.route('/api/profile')
@login_required
def get_profile():
    user = get_current_user()
    conn = _db()
    _ensure_profile_photo_schema(conn)
    row = execute_query(conn, '''
        SELECT id, username, email, full_name, department, role, created_at, last_login,
               password_changed_at, force_password_change, profile_photo_path
        FROM users WHERE id = ?
    ''', (user['id'],)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'User not found'}), 404

    # Activity count
    conn2 = _db()
    ac = execute_query(
        conn2, 'SELECT COUNT(*) AS n FROM activity_log WHERE user_id = ?', (user['id'],)
    ).fetchone()
    activity_count = ac['n'] if isinstance(ac, dict) else ac[0]
    conn2.close()

    profile = dict(row)
    profile['activity_count'] = activity_count
    profile['password_change_required'] = bool(profile.get('force_password_change'))
    return jsonify({'success': True, 'profile': profile})


# ── API: update profile ───────────────────────────────────────────────────────

@user_profile_bp.route('/api/profile/update', methods=['POST'])
@login_required
def update_profile():
    user = get_current_user()
    role = (user.get('role') or '').strip().lower()
    if role in {'user', 'ran_config_user'}:
        return jsonify({'error': 'Profile details update is disabled for your role'}), 403
    data = request.get_json()

    username   = (data.get('username',   '') or '').strip()
    full_name  = (data.get('full_name',  '') or '').strip()
    department = (data.get('department', '') or '').strip()
    email      = (data.get('email',      '') or '').strip()

    if not email:
        return jsonify({'error': 'Email is required'}), 400
    if '@' not in email:
        return jsonify({'error': 'Invalid email address'}), 400
    if not username:
        return jsonify({'error': 'Username is required'}), 400

    conn = _db()
    _ensure_profile_photo_schema(conn)
    try:
        execute_query(conn, '''
            UPDATE users SET username = ?, full_name = ?, department = ?, email = ?
            WHERE id = ?
        ''', (username, full_name, department, email, user['id']))
        conn.commit()
    except Exception as e:
        conn.close()
        if _unique_constraint_error(e):
            return jsonify({'error': 'Username or email already in use by another account'}), 400
        raise
    conn.close()

    log_activity(user['id'], 'profile_update', 'User updated their profile')
    return jsonify({'success': True, 'message': 'Profile updated successfully'})


@user_profile_bp.route('/api/profile/photo-request', methods=['POST'])
@login_required
def upload_profile_photo_request():
    user = get_current_user()
    file = request.files.get('photo')
    if not file or not file.filename:
        return jsonify({'error': 'Photo file is required'}), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in {'.png', '.jpg', '.jpeg', '.webp'}:
        return jsonify({'error': 'Only png/jpg/jpeg/webp are allowed'}), 400
    os.makedirs(_PROFILE_PHOTO_DIR, exist_ok=True)
    stored_name = f"{user['id']}_{uuid.uuid4().hex[:12]}_{secure_filename(file.filename)}"
    file_path = os.path.join(_PROFILE_PHOTO_DIR, stored_name)
    file.save(file_path)

    conn = _db()
    _ensure_profile_photo_schema(conn)
    execute_query(conn, '''
        INSERT INTO profile_photo_requests (user_id, original_file_name, stored_file_name, file_path, status)
        VALUES (?, ?, ?, ?, 'pending')
    ''', (user['id'], secure_filename(file.filename), stored_name, file_path))
    conn.commit()
    conn.close()
    log_activity(user['id'], 'profile_photo_request', 'Requested profile photo approval')
    return jsonify({'success': True, 'message': 'Photo uploaded and pending Owner/NOC SYS approval'})


@user_profile_bp.route('/api/profile/photo-requests', methods=['GET'])
@login_required
def list_photo_requests():
    user = get_current_user()
    if not _can_approve_photo(user):
        return jsonify({'error': 'Only Owner and NOC SYS can review photo requests'}), 403
    conn = _db()
    _ensure_profile_photo_schema(conn)
    rows = execute_query(conn, '''
        SELECT r.id, r.user_id, r.original_file_name, r.status, r.requested_at, u.username
        FROM profile_photo_requests r
        LEFT JOIN users u ON u.id = r.user_id
        WHERE r.status = 'pending'
        ORDER BY r.requested_at ASC
    ''', ()).fetchall()
    conn.close()
    return jsonify({'success': True, 'requests': [dict(r) for r in rows]})


@user_profile_bp.route('/api/profile/photo-requests/<int:req_id>/review', methods=['POST'])
@login_required
def review_photo_request(req_id: int):
    user = get_current_user()
    if not _can_approve_photo(user):
        return jsonify({'error': 'Only Owner and NOC SYS can review photo requests'}), 403
    data = request.get_json(silent=True) or {}
    decision = (data.get('decision') or '').strip().lower()
    if decision not in {'approve', 'reject'}:
        return jsonify({'error': 'decision must be approve or reject'}), 400
    note = (data.get('note') or '').strip()

    conn = _db()
    _ensure_profile_photo_schema(conn)
    row = execute_query(conn, 'SELECT * FROM profile_photo_requests WHERE id = ?', (req_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Request not found'}), 404
    if row['status'] != 'pending':
        conn.close()
        return jsonify({'error': 'Request already reviewed'}), 400

    new_status = 'approved' if decision == 'approve' else 'rejected'
    execute_query(conn, '''
        UPDATE profile_photo_requests
        SET status = ?, reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP, review_note = ?
        WHERE id = ?
    ''', (new_status, user['id'], note, req_id))
    if decision == 'approve':
        execute_query(conn, 'UPDATE users SET profile_photo_path = ? WHERE id = ?', (row['file_path'], row['user_id']))
    conn.commit()
    conn.close()
    log_activity(user['id'], 'profile_photo_review', f'{decision}d profile photo request {req_id}')
    return jsonify({'success': True, 'message': f'Request {new_status}.'})


# ── API: change password ──────────────────────────────────────────────────────

@user_profile_bp.route('/api/profile/change-password', methods=['POST'])
@login_required
def change_password():
    user = get_current_user()
    data = request.get_json()

    current_password = data.get('current_password', '')
    new_password     = data.get('new_password', '')
    confirm_password = data.get('confirm_password', '')

    if not current_password or not new_password:
        return jsonify({'error': 'All password fields are required'}), 400
    if new_password != confirm_password:
        return jsonify({'error': 'New passwords do not match'}), 400
    if len(new_password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400

    # Verify current password
    conn = _db()
    row = execute_query(conn, 'SELECT password_hash FROM users WHERE id = ?', (user['id'],)).fetchone()
    if not row or not verify_password(current_password, row['password_hash']):
        conn.close()
        return jsonify({'error': 'Current password is incorrect'}), 401

    new_hash = hash_password(new_password)
    execute_query(
        conn,
        'UPDATE users SET password_hash = ?, password_changed_at = CURRENT_TIMESTAMP, force_password_change = ? WHERE id = ?',
        (new_hash, False, user['id']),
    )
    conn.commit()
    conn.close()

    log_activity(user['id'], 'password_change', 'User changed their password')
    return jsonify({'success': True, 'message': 'Password changed successfully'})


# ── API: vendor CM credentials (RET management) ───────────────────────────────

@user_profile_bp.route('/api/profile/vendor-credentials')
@login_required
def get_vendor_credentials():
    user = get_current_user()
    status = list_user_vendor_credential_status(user['id'])
    return jsonify({'success': True, 'credentials': status})


@user_profile_bp.route('/api/profile/vendor-credentials', methods=['POST'])
@login_required
def save_vendor_credentials():
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    vendor = (data.get('vendor') or '').strip().lower()
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    if vendor not in ('nokia', 'huawei'):
        return jsonify({'error': 'vendor must be nokia or huawei'}), 400
    try:
        save_user_vendor_credentials(user['id'], vendor, username, password)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    label = 'MantaRay' if vendor == 'nokia' else 'U2020'
    log_activity(user['id'], 'vendor_credentials_save', f'Saved {label} credentials for RET management')
    return jsonify({
        'success': True,
        'message': f'{label} credentials saved.',
        'credentials': list_user_vendor_credential_status(user['id']),
    })


@user_profile_bp.route('/api/profile/vendor-credentials/<vendor>', methods=['DELETE'])
@login_required
def remove_vendor_credentials(vendor: str):
    user = get_current_user()
    vendor = (vendor or '').strip().lower()
    if vendor not in ('nokia', 'huawei'):
        return jsonify({'error': 'vendor must be nokia or huawei'}), 400
    try:
        deleted = delete_user_vendor_credentials(user['id'], vendor)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if deleted:
        label = 'MantaRay' if vendor == 'nokia' else 'U2020'
        log_activity(user['id'], 'vendor_credentials_clear', f'Cleared {label} credentials')
    return jsonify({
        'success': True,
        'message': 'Credentials removed.' if deleted else 'No credentials were stored.',
        'credentials': list_user_vendor_credential_status(user['id']),
    })


# ── API: preferences ──────────────────────────────────────────────────────────

@user_profile_bp.route('/api/profile/preferences')
@login_required
def get_preferences():
    user = get_current_user()
    conn = _db()
    row = execute_query(conn, 'SELECT preferences FROM user_preferences WHERE user_id = ?', (user['id'],)).fetchone()
    conn.close()
    prefs = json.loads(row['preferences']) if row else {}
    return jsonify({'success': True, 'preferences': prefs})


@user_profile_bp.route('/api/profile/preferences', methods=['POST'])
@login_required
def save_preferences():
    user = get_current_user()
    data = request.get_json()
    prefs_json = json.dumps(data)

    conn = _db()
    execute_query(conn, '''
        INSERT INTO user_preferences (user_id, preferences)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET preferences = excluded.preferences, updated_at = CURRENT_TIMESTAMP
    ''', (user['id'], prefs_json))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Preferences saved'})


# ── API: saved views (shareable filter snapshots) ────────────────────────────


def _generate_view_id() -> str:
    """Short, URL-safe identifier (10 hex chars from a fresh UUID4)."""
    return uuid.uuid4().hex[:10]


def _ensure_saved_views_schema(conn):
    if not isinstance(conn, sqlite3.Connection):
        return
    conn.execute('''
        CREATE TABLE IF NOT EXISTS saved_views (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            module TEXT NOT NULL,
            name TEXT NOT NULL,
            state TEXT NOT NULL,
            is_public INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_saved_views_user_module ON saved_views(user_id, module)'
    )


def _row_to_view(row, *, include_state=False):
    if not row:
        return None
    base = {
        'id': row['id'],
        'user_id': row['user_id'],
        'module': row['module'],
        'name': row['name'],
        'is_public': bool(row['is_public']),
        'created_at': row['created_at'],
        'updated_at': row['updated_at'],
    }
    if include_state:
        try:
            base['state'] = json.loads(row['state'] or '{}')
        except Exception:
            base['state'] = {}
    return base


@user_profile_bp.route('/api/profile/views', methods=['GET'])
@login_required
def list_saved_views():
    """List the current user's saved views, optionally scoped to one module."""
    user = get_current_user()
    module = (request.args.get('module') or '').strip()
    conn = _db()
    _ensure_saved_views_schema(conn)
    if module:
        rows = execute_query(conn, '''
            SELECT id, user_id, module, name, state, is_public, created_at, updated_at
            FROM saved_views
            WHERE user_id = ? AND module = ?
            ORDER BY updated_at DESC
        ''', (user['id'], module)).fetchall()
    else:
        rows = execute_query(conn, '''
            SELECT id, user_id, module, name, state, is_public, created_at, updated_at
            FROM saved_views
            WHERE user_id = ?
            ORDER BY updated_at DESC
        ''', (user['id'],)).fetchall()
    conn.close()
    views = [_row_to_view(r, include_state=False) for r in rows]
    return jsonify({'success': True, 'views': views})


@user_profile_bp.route('/api/profile/views', methods=['POST'])
@login_required
def create_saved_view():
    """Create or upsert a saved view for the current user."""
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    module = (data.get('module') or '').strip()
    name = (data.get('name') or '').strip()
    state = data.get('state')
    is_public = 1 if bool(data.get('is_public')) else 0
    if not module:
        return jsonify({'error': 'module is required'}), 400
    if not name:
        return jsonify({'error': 'name is required'}), 400
    if state is None:
        return jsonify({'error': 'state is required'}), 400
    if len(name) > 80:
        return jsonify({'error': 'name must be <= 80 characters'}), 400
    try:
        state_json = json.dumps(state)
    except (TypeError, ValueError):
        return jsonify({'error': 'state must be JSON-serializable'}), 400
    if len(state_json) > 64 * 1024:
        return jsonify({'error': 'state too large'}), 400

    conn = _db()
    _ensure_saved_views_schema(conn)
    existing = execute_query(conn, '''
        SELECT id FROM saved_views WHERE user_id = ? AND module = ? AND name = ?
    ''', (user['id'], module, name)).fetchone()
    if existing:
        view_id = existing['id']
        execute_query(conn, '''
            UPDATE saved_views
            SET state = ?, is_public = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (state_json, is_public, view_id))
    else:
        view_id = _generate_view_id()
        execute_query(conn, '''
            INSERT INTO saved_views (id, user_id, module, name, state, is_public)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (view_id, user['id'], module, name, state_json, is_public))
    conn.commit()
    conn.close()
    log_activity(user['id'], 'saved_view_save', f'Saved view {name} ({module})')
    return jsonify({'success': True, 'id': view_id, 'name': name, 'module': module, 'is_public': bool(is_public)})


@user_profile_bp.route('/api/profile/views/<view_id>', methods=['GET'])
@login_required
def get_saved_view(view_id: str):
    """Return a single saved view; allowed if owned or public."""
    user = get_current_user()
    conn = _db()
    _ensure_saved_views_schema(conn)
    row = execute_query(conn, '''
        SELECT id, user_id, module, name, state, is_public, created_at, updated_at
        FROM saved_views WHERE id = ?
    ''', (view_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'View not found'}), 404
    if int(row['user_id']) != int(user['id']) and not row['is_public']:
        return jsonify({'error': 'You do not have access to this view'}), 403
    return jsonify({'success': True, 'view': _row_to_view(row, include_state=True)})


@user_profile_bp.route('/api/profile/views/<view_id>', methods=['DELETE'])
@login_required
def delete_saved_view(view_id: str):
    user = get_current_user()
    conn = _db()
    _ensure_saved_views_schema(conn)
    row = execute_query(conn, 'SELECT user_id FROM saved_views WHERE id = ?', (view_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'View not found'}), 404
    if int(row['user_id']) != int(user['id']):
        conn.close()
        return jsonify({'error': 'You can only delete your own views'}), 403
    execute_query(conn, 'DELETE FROM saved_views WHERE id = ?', (view_id,))
    conn.commit()
    conn.close()
    log_activity(user['id'], 'saved_view_delete', f'Deleted saved view {view_id}')
    return jsonify({'success': True})


# ── API: recent activity ──────────────────────────────────────────────────────

@user_profile_bp.route('/api/profile/activity')
@login_required
def recent_activity():
    user = get_current_user()
    role = (user.get('role') or '').strip().lower()
    if role != 'admin':
        return jsonify({'error': 'Only Owner can view activity history'}), 403
    conn = _db()
    rows = execute_query(conn, '''
        SELECT a.action, a.details, a.ip_address, a.timestamp, a.user_id, u.username
        FROM activity_log a
        LEFT JOIN users u ON u.id = a.user_id
        ORDER BY timestamp DESC
        LIMIT 200
    ''', ()).fetchall()
    conn.close()
    return jsonify({'success': True, 'activity': [dict(r) for r in rows]})
