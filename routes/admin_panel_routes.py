"""
Admin Panel Routes
Handles user management and administration
"""

from flask import Blueprint, request, jsonify, render_template, redirect, url_for
from functools import wraps

from database_enhanced import get_user_by_session, log_activity, get_all_users

admin_panel_bp = Blueprint('admin_panel', __name__)

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

def admin_required(f):
    """Decorator to require admin role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        session_token = request.cookies.get('session_token')
        if not session_token:
            return redirect(url_for('auth.login_page'))

        user = get_user_by_session(session_token)
        if not user or (user.get('role') if isinstance(user, dict) else user[6]) != 'admin':
            return redirect(url_for('auth.dashboard'))

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


@admin_panel_bp.route('/admin-panel')
@admin_required
def admin_panel_page():
    """Render Admin Panel page"""
    user = get_current_user()
    return render_template('admin_panel.html', user=format_user_data(user))

@admin_panel_bp.route('/api/admin/users', methods=['GET'])
def get_users():
    """Get all users"""
    user = get_current_user()
    if not user or (user.get('role') if isinstance(user, dict) else user[6]) != 'admin':
        return jsonify({'error': 'Admin access required'}), 403

    try:
        users = get_all_users()

        users_data = []
        for u in users:
            users_data.append({
                'id': u['id'],
                'username': u['username'],
                'email': u['email'],
                'created_at': u['created_at'],
                'is_active': bool(u['is_active']),
                'role': u['role'],
                'last_activity': u['last_login'],
            })

        log_activity((user.get('id') if isinstance(user, dict) else user[0]), 'admin_view_users', 'Viewed user list')

        return jsonify({
            'success': True,
            'users': users_data
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@admin_panel_bp.route('/api/admin/users/<int:user_id>/role', methods=['PUT'])
def update_user_role(user_id):
    """Update user role"""
    user = get_current_user()
    if not user or (user.get('role') if isinstance(user, dict) else user[6]) != 'admin':
        return jsonify({'error': 'Admin access required'}), 403

    try:
        data = request.get_json()
        new_role = data.get('role')

        if new_role not in ['admin', 'user']:
            return jsonify({'error': 'Invalid role'}), 400

        import sqlite3
        conn = sqlite3.connect('ncm_users.db')
        cursor = conn.cursor()

        cursor.execute('UPDATE users SET role = ? WHERE id = ?', (new_role, user_id))
        conn.commit()
        conn.close()

        log_activity((user.get('id') if isinstance(user, dict) else user[0]), 'admin_change_role', f'Changed user {user_id} role to {new_role}')

        return jsonify({
            'success': True,
            'message': f'Role updated to {new_role}'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@admin_panel_bp.route('/api/admin/users/<int:user_id>/status', methods=['PUT'])
def update_user_status(user_id):
    """Update user active status"""
    user = get_current_user()
    if not user or (user.get('role') if isinstance(user, dict) else user[6]) != 'admin':
        return jsonify({'error': 'Admin access required'}), 403

    try:
        data = request.get_json()
        is_active = data.get('is_active')

        if is_active is None:
            return jsonify({'error': 'is_active required'}), 400

        import sqlite3
        conn = sqlite3.connect('ncm_users.db')
        cursor = conn.cursor()

        cursor.execute('UPDATE users SET is_active = ? WHERE id = ?', (int(is_active), user_id))
        conn.commit()
        conn.close()

        status_text = 'activated' if is_active else 'deactivated'
        log_activity((user.get('id') if isinstance(user, dict) else user[0]), 'admin_change_status', f'User {user_id} {status_text}')

        return jsonify({
            'success': True,
            'message': f'User {status_text}'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
