"""
User Profile & Dashboard Personalization Routes
Allows users to update their profile, change password, and customize the dashboard.
"""

from flask import Blueprint, request, jsonify, render_template, redirect, url_for
from functools import wraps
import sqlite3
import json

from database_enhanced import (
    get_user_by_session, log_activity,
    verify_password, hash_password
)
from sync_config import NCMUSERS_DB

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
    row = conn.execute('''
        SELECT id, username, email, full_name, department, role, created_at, last_login
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
    return jsonify({'success': True, 'profile': profile})


# ── API: update profile ───────────────────────────────────────────────────────

@user_profile_bp.route('/api/profile/update', methods=['POST'])
@login_required
def update_profile():
    user = get_current_user()
    data = request.get_json()

    full_name  = (data.get('full_name',  '') or '').strip()
    department = (data.get('department', '') or '').strip()
    email      = (data.get('email',      '') or '').strip()

    if not email:
        return jsonify({'error': 'Email is required'}), 400
    if '@' not in email:
        return jsonify({'error': 'Invalid email address'}), 400

    conn = _db()
    try:
        conn.execute('''
            UPDATE users SET full_name = ?, department = ?, email = ?
            WHERE id = ?
        ''', (full_name, department, email, user['id']))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Email already in use by another account'}), 400
    conn.close()

    log_activity(user['id'], 'profile_update', 'User updated their profile')
    return jsonify({'success': True, 'message': 'Profile updated successfully'})


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
    conn.execute('UPDATE users SET password_hash = ? WHERE id = ?', (new_hash, user['id']))
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
    conn = _db()
    rows = conn.execute('''
        SELECT action, details, ip_address, timestamp
        FROM activity_log
        WHERE user_id = ?
        ORDER BY timestamp DESC
        LIMIT 20
    ''', (user['id'],)).fetchall()
    conn.close()
    return jsonify({'success': True, 'activity': [dict(r) for r in rows]})
