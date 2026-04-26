"""
Admin Panel Routes
Handles user management and administration
"""

import os
import sqlite3
from datetime import datetime
from flask import Blueprint, request, jsonify, render_template, redirect, url_for
from functools import wraps

from database_enhanced import get_user_by_session, log_activity, get_all_users
from db.runtime import (
    connect_huawei_pm,
    connect_nokia_pm,
    execute_query,
    is_postgresql,
    postgres_table_columns,
)
from sync_config import (
    HUAWEI_PM_DAILY_DB,
    HUAWEI_PM_DB,
    NCMUSERS_DB,
    NOKIA_PM_DAILY_DB,
    NOKIA_PM_DB,
    PROJECT_ROOT,
    SCHEMA_HUAWEI_PM,
    SCHEMA_NOKIA_PM,
)

admin_panel_bp = Blueprint(
    'admin_panel', __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/admin_panel/static',
)

ROLE_LABELS = {
    'admin': 'Owner',
    'user': 'User',
    'ran_config_user': 'RNC User',
    'noc_sys': 'NOC SYS',
}


def _user_role(user) -> str:
    if not user:
        return ''
    raw = user.get('role') if isinstance(user, dict) else user[6]
    return str(raw or '').strip().lower()


def _is_owner(user) -> bool:
    return _user_role(user) == 'admin'


def _can_access_user_admin(user) -> bool:
    return _user_role(user) in {'admin', 'noc_sys'}

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
    """Decorator to require Owner or NOC SYS role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        session_token = request.cookies.get('session_token')
        if not session_token:
            return redirect(url_for('auth.login_page'))

        user = get_user_by_session(session_token)
        if not _can_access_user_admin(user):
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
    role = _user_role(user)
    return render_template(
        'admin_panel.html',
        user=format_user_data(user),
        role_labels=ROLE_LABELS,
        can_manage_sync=role == 'admin',
    )

@admin_panel_bp.route('/api/admin/users', methods=['GET'])
def get_users():
    """Get all users"""
    user = get_current_user()
    if not _can_access_user_admin(user):
        return jsonify({'error': 'Owner or NOC SYS access required'}), 403

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
                'role_label': ROLE_LABELS.get(str(u.get('role', '')).strip().lower(), u.get('role', '')),
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
    if not _can_access_user_admin(user):
        return jsonify({'error': 'Owner or NOC SYS access required'}), 403

    try:
        data = request.get_json()
        new_role = data.get('role')

        if new_role not in ['admin', 'user', 'ran_config_user', 'noc_sys']:
            return jsonify({'error': 'Invalid role'}), 400

        import sqlite3
        conn = sqlite3.connect(NCMUSERS_DB)
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
    if not _can_access_user_admin(user):
        return jsonify({'error': 'Owner or NOC SYS access required'}), 403

    try:
        data = request.get_json()
        is_active = data.get('is_active')

        if is_active is None:
            return jsonify({'error': 'is_active required'}), 400

        import sqlite3
        conn = sqlite3.connect(NCMUSERS_DB)
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


def _sqlite_quote_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _pick_time_column(cols: list) -> str | None:
    """First usable time column (same priority idea as performance routes)."""
    by_lower = {str(c).lower(): c for c in cols}
    for key in ('timestamp', 'period_start_time', 'time', 'date'):
        if key in by_lower:
            return str(by_lower[key])
    return None


def _compare_pm_timestamp(a, b) -> bool:
    """True if b is strictly newer than a (None treated as smallest)."""
    if b is None or str(b).strip() == '':
        return False
    if a is None or str(a).strip() == '':
        return True
    da = _parse_pm_timestamp(a)
    db = _parse_pm_timestamp(b)
    if da is not None and db is not None:
        return db > da
    sa, sb = str(a).strip(), str(b).strip()
    if sa == sb:
        return False
    return sb > sa


def _parse_pm_timestamp(value):
    """Best-effort parser for Nokia/Huawei date-time strings."""
    s = str(value or '').strip()
    if not s:
        return None
    for fmt in (
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %H:%M:%S.%f',
        '%Y-%m-%d',
        '%d/%m/%Y %H:%M',
        '%d/%m/%y %H:%M',
        '%d/%m/%Y',
        '%d/%m/%y',
        '%m.%d.%y %H:%M:%S',
        '%d.%m.%Y %H:%M:%S',
        '%d.%m.%Y',
        '%m.%d.%Y %H:%M:%S',
        '%m.%d.%Y',
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _normalize_pm_timestamp(value):
    dt = _parse_pm_timestamp(value)
    if dt is None:
        return str(value) if value is not None else None
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def _best_timestamp_sqlite(conn, table_name: str, time_column: str):
    """
    Return chronologically latest timestamp by parsing row values, not lexical MAX().
    This avoids wrong ordering for text formats like dd/mm/yyyy.
    """
    best_raw = None
    best_dt = None
    qtbl = _sqlite_quote_ident(table_name)
    qcol = _sqlite_quote_ident(time_column)
    try:
        cur = conn.execute(f'SELECT {qcol} FROM {qtbl}')
        for row in cur.fetchall():
            raw = row[0] if row else None
            dt = _parse_pm_timestamp(raw)
            if dt is None:
                continue
            if best_dt is None or dt > best_dt:
                best_dt = dt
                best_raw = raw
    except Exception:
        return None
    return best_raw


def _sqlite_pm_survey(path: str) -> dict:
    """Return last timestamp across tables that expose a ``timestamp`` column."""
    out = {
        'backend': 'sqlite',
        'path': path,
        'exists': os.path.isfile(path),
        'last_timestamp': None,
        'latest_table': None,
        'per_table': [],
        'error': None,
    }
    if not out['exists']:
        return out
    try:
        conn = sqlite3.connect(path, timeout=20)
        try:
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]
            best_ts, best_tbl = None, None
            for tbl in tables:
                cols = [
                    r[1]
                    for r in conn.execute(f'PRAGMA table_info({_sqlite_quote_ident(tbl)})').fetchall()
                ]
                tcol = _pick_time_column(cols)
                if not tcol:
                    continue
                mx = _best_timestamp_sqlite(conn, tbl, tcol)
                if mx is not None and str(mx).strip() != '':
                    out['per_table'].append({'table': tbl, 'last_timestamp': _normalize_pm_timestamp(mx)})
                    if _compare_pm_timestamp(best_ts, mx):
                        best_ts, best_tbl = mx, tbl
            out['last_timestamp'] = _normalize_pm_timestamp(best_ts) if best_ts is not None else None
            out['latest_table'] = best_tbl
        finally:
            conn.close()
    except Exception as e:
        out['error'] = str(e)
    return out


def _postgresql_pm_survey(connect_fn, schema: str) -> dict:
    out = {
        'backend': 'postgresql',
        'path': None,
        'schema': schema,
        'exists': True,
        'last_timestamp': None,
        'latest_table': None,
        'per_table': [],
        'error': None,
    }
    conn = None
    try:
        conn = connect_fn()
        cur = execute_query(
            conn,
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = ? AND table_type = 'BASE TABLE'
            """,
            (schema,),
        )
        tables = [r['table_name'] if isinstance(r, dict) else r[0] for r in cur.fetchall()]
        best_ts, best_tbl = None, None
        for tbl in tables:
            cols = postgres_table_columns(conn, schema, tbl)
            tcol = _pick_time_column(cols)
            if not tcol:
                continue
            qtbl = _sqlite_quote_ident(tbl)
            cur2 = execute_query(
                conn, f'SELECT MAX({_sqlite_quote_ident(tcol)}) AS m FROM {qtbl}'
            )
            row = cur2.fetchone()
            mx = None
            if row:
                mx = row['m'] if isinstance(row, dict) else row[0]
            if mx is not None and str(mx).strip() != '':
                out['per_table'].append({'table': tbl, 'last_timestamp': _normalize_pm_timestamp(mx)})
                if _compare_pm_timestamp(best_ts, mx):
                    best_ts, best_tbl = mx, tbl
        out['last_timestamp'] = _normalize_pm_timestamp(best_ts) if best_ts is not None else None
        out['latest_table'] = best_tbl
    except Exception as e:
        out['error'] = str(e)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return out


def _pm_database_definitions():
    """Ordered list of (label, kind, path) for PM cell databases."""
    femto = os.path.join(PROJECT_ROOT, 'databases', 'cells', 'femto_pm_cells.db')
    return [
        ('Nokia PM (hourly)', 'nokia_hourly', NOKIA_PM_DB),
        ('Huawei PM (hourly)', 'huawei_hourly', HUAWEI_PM_DB),
        ('Nokia PM (daily)', 'sqlite', NOKIA_PM_DAILY_DB),
        ('Huawei PM (daily)', 'sqlite', HUAWEI_PM_DAILY_DB),
        ('Femto PM', 'sqlite', femto),
    ]


@admin_panel_bp.route('/api/admin/pm-latest-timestamps', methods=['GET'])
def pm_latest_timestamps():
    """Latest ``timestamp`` value per PM database (Owner only)."""
    user = get_current_user()
    if not _is_owner(user):
        return jsonify({'error': 'Owner access required'}), 403

    databases = []
    try:
        for label, kind, path in _pm_database_definitions():
            if kind == 'nokia_hourly':
                if is_postgresql():
                    row = {**_postgresql_pm_survey(connect_nokia_pm, SCHEMA_NOKIA_PM), 'label': label}
                else:
                    row = {**_sqlite_pm_survey(path), 'label': label}
            elif kind == 'huawei_hourly':
                if is_postgresql():
                    row = {**_postgresql_pm_survey(connect_huawei_pm, SCHEMA_HUAWEI_PM), 'label': label}
                else:
                    row = {**_sqlite_pm_survey(path), 'label': label}
            else:
                row = {**_sqlite_pm_survey(path), 'label': label}
            databases.append(row)

        log_activity(
            (user.get('id') if isinstance(user, dict) else user[0]),
            'admin_pm_latest_timestamps',
            'Viewed PM latest timestamps',
        )
        return jsonify({'success': True, 'databases': databases})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
