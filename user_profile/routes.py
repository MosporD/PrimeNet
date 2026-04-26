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
    get_user_by_session, log_activity,
    verify_password, hash_password
)
from sync_config import NCMUSERS_DB
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
    conn = sqlite3.connect(NCMUSERS_DB)
    conn.row_factory = sqlite3.Row
    return conn


_PROFILE_PHOTO_DIR = os.path.join(PROJECT_ROOT, 'uploads', 'profile_photos')
_PHOTO_APPROVER_ROLES = {'admin', 'noc_sys'}


def _ensure_profile_photo_schema(conn):
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
    row = conn.execute('''
        SELECT id, username, email, full_name, department, role, created_at, last_login,
               password_changed_at, force_password_change, profile_photo_path
        FROM users WHERE id = ?
    ''', (user['id'],)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'User not found'}), 404

    # Activity count
    conn2 = _db()
    activity_count = conn2.execute(
        'SELECT COUNT(*) FROM activity_log WHERE user_id = ?', (user['id'],)
    ).fetchone()[0]
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
        conn.execute('''
            UPDATE users SET username = ?, full_name = ?, department = ?, email = ?
            WHERE id = ?
        ''', (username, full_name, department, email, user['id']))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Username or email already in use by another account'}), 400
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
    conn.execute('''
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
    rows = conn.execute('''
        SELECT r.id, r.user_id, r.original_file_name, r.status, r.requested_at, u.username
        FROM profile_photo_requests r
        LEFT JOIN users u ON u.id = r.user_id
        WHERE r.status = 'pending'
        ORDER BY r.requested_at ASC
    ''').fetchall()
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
    row = conn.execute('SELECT * FROM profile_photo_requests WHERE id = ?', (req_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Request not found'}), 404
    if row['status'] != 'pending':
        conn.close()
        return jsonify({'error': 'Request already reviewed'}), 400

    new_status = 'approved' if decision == 'approve' else 'rejected'
    conn.execute('''
        UPDATE profile_photo_requests
        SET status = ?, reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP, review_note = ?
        WHERE id = ?
    ''', (new_status, user['id'], note, req_id))
    if decision == 'approve':
        conn.execute('UPDATE users SET profile_photo_path = ? WHERE id = ?', (row['file_path'], row['user_id']))
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
    row = conn.execute('SELECT password_hash FROM users WHERE id = ?', (user['id'],)).fetchone()
    if not row or not verify_password(current_password, row['password_hash']):
        conn.close()
        return jsonify({'error': 'Current password is incorrect'}), 401

    new_hash = hash_password(new_password)
    conn.execute(
        'UPDATE users SET password_hash = ?, password_changed_at = CURRENT_TIMESTAMP, force_password_change = 0 WHERE id = ?',
        (new_hash, user['id'])
    )
    conn.commit()
    conn.close()

    log_activity(user['id'], 'password_change', 'User changed their password')
    return jsonify({'success': True, 'message': 'Password changed successfully'})


# ── API: preferences ──────────────────────────────────────────────────────────

@user_profile_bp.route('/api/profile/preferences')
@login_required
def get_preferences():
    user = get_current_user()
    conn = _db()
    row = conn.execute('SELECT preferences FROM user_preferences WHERE user_id = ?', (user['id'],)).fetchone()
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
    conn.execute('''
        INSERT INTO user_preferences (user_id, preferences)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET preferences = excluded.preferences, updated_at = CURRENT_TIMESTAMP
    ''', (user['id'], prefs_json))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Preferences saved'})


# ── API: recent activity ──────────────────────────────────────────────────────

@user_profile_bp.route('/api/profile/activity')
@login_required
def recent_activity():
    user = get_current_user()
    role = (user.get('role') or '').strip().lower()
    if role != 'admin':
        return jsonify({'error': 'Only Owner can view activity history'}), 403
    conn = _db()
    rows = conn.execute('''
        SELECT a.action, a.details, a.ip_address, a.timestamp, a.user_id, u.username
        FROM activity_log a
        LEFT JOIN users u ON u.id = a.user_id
        ORDER BY timestamp DESC
        LIMIT 200
    ''').fetchall()
    conn.close()
    return jsonify({'success': True, 'activity': [dict(r) for r in rows]})
