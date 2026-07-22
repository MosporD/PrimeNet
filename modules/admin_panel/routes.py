"""
Admin Panel Routes
Handles user management and administration
"""

import os
import sqlite3
from datetime import datetime
from flask import Blueprint, request, jsonify, render_template, redirect, url_for, send_file
from functools import wraps

from database_enhanced import (
    count_active_admins,
    create_user,
    delete_user,
    get_user_by_session,
    log_activity,
    get_all_users,
    reset_user_password,
    set_user_force_password_change,
    update_user_role,
    update_user_status,
    get_db,
)
from db.runtime import execute_query
from core.cm_extractor.config import (
    huawei_configured,
    huawei_defaults,
    nokia_configured,
    nokia_defaults,
)
from core.cm_extractor.huawei_client import HuaweiCmClient, HuaweiCmError
from core.cm_extractor.nokia_client import NokiaCmClient, NokiaCmError
from core.huawei_pm.config import build_pm_client, pm_configured
from core.huawei_pm.client import HuaweiPmError
from modules.admin_panel.export import build_table_workbook
from sync_config import (
    DATABASES_ROOT,
    HUAWEI_PM_DAILY_DB,
    HUAWEI_PM_DB,
    NCM_DEFAULT_USER_PASSWORD,
    NOKIA_PM_DAILY_DB,
    NOKIA_PM_DB,
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
        default_user_password=NCM_DEFAULT_USER_PASSWORD,
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


@admin_panel_bp.route('/api/admin/users', methods=['POST'])
def create_user_account():
    """Create a new application user (Owner or NOC SYS)."""
    user = get_current_user()
    if not _can_access_user_admin(user):
        return jsonify({'error': 'Owner or NOC SYS access required'}), 403

    try:
        data = request.get_json() or {}
        username = str(data.get('username') or '').strip()
        email = str(data.get('email') or '').strip()
        full_name = str(data.get('full_name') or '').strip() or None
        department = str(data.get('department') or '').strip() or None
        role = str(data.get('role') or 'user').strip().lower()
        use_default_password = bool(data.get('use_default_password', True))
        custom_password = str(data.get('password') or '').strip()

        if not username:
            return jsonify({'error': 'Username is required'}), 400
        if not email or '@' not in email:
            return jsonify({'error': 'A valid email is required'}), 400
        if role not in ROLE_LABELS:
            return jsonify({'error': 'Invalid role'}), 400

        if use_default_password:
            password = NCM_DEFAULT_USER_PASSWORD
            force_change = False
        else:
            password = custom_password
            if len(password) < 8:
                return jsonify({'error': 'Password must be at least 8 characters'}), 400
            force_change = bool(data.get('force_password_change', False))

        if not password:
            return jsonify({'error': 'Password is required'}), 400

        success, result = create_user(
            username=username,
            email=email,
            password=password,
            full_name=full_name,
            department=department,
            role=role,
        )
        if not success:
            return jsonify({'error': result}), 400

        user_id = int(result)
        set_user_force_password_change(user_id, force_change)

        log_activity(
            (user.get('id') if isinstance(user, dict) else user[0]),
            'admin_create_user',
            f'Created user {username} ({user_id})',
        )
        return jsonify({
            'success': True,
            'message': f'User {username} created',
            'user_id': user_id,
            'used_default_password': use_default_password,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_panel_bp.route('/api/admin/users/<int:user_id>/reset-password', methods=['POST'])
def reset_user_password_to_default(user_id):
    """Reset a user's password to the configured default."""
    user = get_current_user()
    if not _can_access_user_admin(user):
        return jsonify({'error': 'Owner or NOC SYS access required'}), 403

    try:
        if not NCM_DEFAULT_USER_PASSWORD:
            return jsonify({'error': 'Default user password is not configured'}), 500

        if not reset_user_password(
            user_id,
            NCM_DEFAULT_USER_PASSWORD,
            force_password_change=False,
        ):
            return jsonify({'error': 'User not found'}), 404

        log_activity(
            (user.get('id') if isinstance(user, dict) else user[0]),
            'admin_reset_password',
            f'Reset password to default for user {user_id}',
        )
        return jsonify({
            'success': True,
            'message': 'Password reset to default',
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

        if not update_user_role(user_id, new_role):
            return jsonify({'error': 'User not found'}), 404

        log_activity((user.get('id') if isinstance(user, dict) else user[0]), 'admin_change_role', f'Changed user {user_id} role to {new_role}')

        return jsonify({
            'success': True,
            'message': f'Role updated to {new_role}'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@admin_panel_bp.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
def remove_user_account(user_id):
    """Permanently delete a user account."""
    user = get_current_user()
    if not _can_access_user_admin(user):
        return jsonify({'error': 'Owner or NOC SYS access required'}), 403

    try:
        actor_id = user.get('id') if isinstance(user, dict) else user[0]
        if int(user_id) == int(actor_id):
            return jsonify({'error': 'You cannot delete your own account'}), 400

        target_users = [u for u in get_all_users() if int(u['id']) == int(user_id)]
        if not target_users:
            return jsonify({'error': 'User not found'}), 404

        target = target_users[0]
        if str(target.get('role', '')).strip().lower() == 'admin' and bool(target.get('is_active')):
            if count_active_admins(exclude_user_id=user_id) < 1:
                return jsonify({'error': 'Cannot delete the last active owner account'}), 400

        success, result = delete_user(user_id)
        if not success:
            if result == 'User not found':
                return jsonify({'error': result}), 404
            return jsonify({'error': result}), 500

        log_activity(
            actor_id,
            'admin_delete_user',
            f'Deleted user {result} ({user_id})',
        )
        return jsonify({
            'success': True,
            'message': f'User {result} removed',
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

        if not update_user_status(user_id, int(is_active)):
            return jsonify({'error': 'User not found'}), 404

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


def _pm_database_definitions():
    """Ordered list of (label, kind, path) for PM cell databases."""
    femto = os.path.join(DATABASES_ROOT, 'cells', 'femto_pm_cells.db')
    femto_kpis = os.path.join(DATABASES_ROOT, 'cells', 'femto_user_kpis.db')
    return [
        ('Nokia PM (hourly)', 'nokia_hourly', NOKIA_PM_DB),
        ('Huawei PM (hourly)', 'huawei_hourly', HUAWEI_PM_DB),
        ('Nokia PM (daily)', 'sqlite', NOKIA_PM_DAILY_DB),
        ('Huawei PM (daily)', 'sqlite', HUAWEI_PM_DAILY_DB),
        ('Femto PM', 'sqlite', femto),
        ('Femto user KPIs', 'sqlite', femto_kpis),
    ]


def _api_connection_row(
    label: str,
    *,
    configured: bool,
    endpoint: str = '',
    missing: list[str] | None = None,
) -> dict:
    return {
        'label': label,
        'configured': configured,
        'endpoint': endpoint,
        'missing': missing or [],
        'status': 'skipped',
        'message': '',
        'error': None,
    }


def _test_nokia_cm_connection() -> dict:
    row = _api_connection_row('Nokia CM API', configured=nokia_configured())
    cfg = nokia_defaults()
    host = cfg.get('host') or cfg.get('base_url') or ''
    row['endpoint'] = host
    if not row['configured']:
        row['message'] = 'Not configured (.env: NOKIA_CM_HOST, NOKIA_CM_USER, NOKIA_CM_PASSWORD)'
        return row
    try:
        client = NokiaCmClient(
            host=cfg['host'],
            username=cfg['username'],
            password=cfg['password'],
            base_url=cfg.get('base_url') or '',
            use_https=cfg['use_https'],
            verify_ssl=cfg['verify_ssl'],
            timeout=min(int(cfg.get('timeout') or 180), 60),
            max_retries=cfg.get('max_retries', 2),
            retry_base_delay_sec=cfg.get('retry_base_delay_sec', 2.0),
        )
        client.test_connection()
        row['status'] = 'ok'
        row['message'] = 'Connected to Nokia NetAct CM API'
    except NokiaCmError as exc:
        row['status'] = 'error'
        row['error'] = str(exc)
        row['message'] = str(exc)
    except Exception as exc:
        row['status'] = 'error'
        row['error'] = str(exc)
        row['message'] = f'Connection failed: {exc}'
    return row


def _test_huawei_cm_connection() -> dict:
    import os

    row = _api_connection_row('Huawei CM API', configured=huawei_configured())
    cfg = huawei_defaults()
    row['endpoint'] = f"{cfg.get('host') or ''}:{cfg.get('port') or 31127}".strip(':')
    huawei_enabled = (os.environ.get('CM_HUAWEI_ENABLED') or 'true').strip().lower() not in (
        '0', 'false', 'no', 'off',
    )
    if not huawei_enabled:
        row['message'] = 'Huawei CM feature disabled (CM_HUAWEI_ENABLED=false)'
        return row
    if not row['configured']:
        row['message'] = 'Not configured (.env: HUAWEI_CM_HOST, HUAWEI_CM_USER, HUAWEI_CM_PASSWORD)'
        return row
    try:
        client = HuaweiCmClient(
            host=cfg['host'],
            username=cfg['username'],
            password=cfg['password'],
            port=int(cfg.get('port') or 31127),
            use_https=cfg.get('use_https', True),
            verify_ssl=cfg.get('verify_ssl', False),
            api_style=cfg.get('api_style', 'wireless'),
            client_ip=cfg.get('client_ip', ''),
            timeout=min(int(cfg.get('timeout') or 180), 60),
        )
        result = client.test_connection()
        row['status'] = 'ok'
        row['message'] = result.get('message', 'Authentication successful')
    except HuaweiCmError as exc:
        row['status'] = 'error'
        row['error'] = str(exc)
        row['message'] = str(exc)
    except Exception as exc:
        row['status'] = 'error'
        row['error'] = str(exc)
        row['message'] = f'Connection failed: {exc}'
    return row


def _test_huawei_pm_connection() -> dict:
    row = _api_connection_row('Huawei PM API', configured=pm_configured())
    cfg = huawei_defaults()
    row['endpoint'] = f"{cfg.get('host') or ''}:{cfg.get('port') or 31127}".strip(':')
    if not row['configured']:
        row['message'] = 'Not configured (uses HUAWEI_CM_* / HUAWEI_PM_* in .env)'
        return row
    try:
        client = build_pm_client()
        result = client.test_connection()
        row['status'] = 'ok'
        row['message'] = result.get('message', 'Huawei PM Open API authentication successful')
    except (HuaweiPmError, HuaweiCmError, ValueError) as exc:
        row['status'] = 'error'
        row['error'] = str(exc)
        row['message'] = str(exc)
    except Exception as exc:
        row['status'] = 'error'
        row['error'] = str(exc)
        row['message'] = f'Connection failed: {exc}'
    return row


@admin_panel_bp.route('/api/admin/test-api-connections', methods=['POST'])
def test_api_connections():
    """Live connectivity checks for vendor northbound APIs (Owner only)."""
    user = get_current_user()
    if not _is_owner(user):
        return jsonify({'error': 'Owner access required'}), 403

    data = request.get_json(silent=True) or {}
    vendor = str(data.get('vendor') or 'all').strip().lower()

    tests = {
        'nokia_cm': _test_nokia_cm_connection,
        'huawei_cm': _test_huawei_cm_connection,
        'huawei_pm': _test_huawei_pm_connection,
    }
    if vendor != 'all' and vendor not in tests:
        return jsonify({'error': 'Unknown vendor'}), 400

    try:
        results = {}
        selected = tests if vendor == 'all' else {vendor: tests[vendor]}
        for key, fn in selected.items():
            results[key] = fn()

        tested = [r for r in results.values() if r.get('status') in ('ok', 'error')]
        ok_count = sum(1 for r in tested if r.get('status') == 'ok')
        error_count = sum(1 for r in tested if r.get('status') == 'error')

        log_activity(
            (user.get('id') if isinstance(user, dict) else user[0]),
            'admin_test_api_connections',
            f'Tested API connections ({vendor}): {ok_count} ok, {error_count} failed',
        )
        return jsonify({
            'success': True,
            'results': results,
            'summary': {
                'tested': len(tested),
                'ok': ok_count,
                'failed': error_count,
                'skipped': sum(1 for r in results.values() if r.get('status') == 'skipped'),
            },
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


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
                row = {**_sqlite_pm_survey(path), 'label': label}
            elif kind == 'huawei_hourly':
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


@admin_panel_bp.route('/api/admin/ret-credential-fallbacks', methods=['GET'])
def ret_credential_fallbacks():
    """RET accountability alerts: missing personal credentials or failed credential fallback."""
    user = get_current_user()
    if not _is_owner(user):
        return jsonify({'error': 'Owner access required'}), 403

    limit = min(max(int(request.args.get('limit') or 50), 1), 200)
    conn = get_db()
    rows = execute_query(conn, '''
        SELECT a.timestamp, a.action, a.details, a.user_id, u.username
        FROM activity_log a
        LEFT JOIN users u ON u.id = a.user_id
        WHERE a.action IN ('ret_credential_fallback', 'ret_missing_credentials')
        ORDER BY a.timestamp DESC
        LIMIT ?
    ''', (limit,)).fetchall()
    conn.close()
    return jsonify({
        'success': True,
        'items': [dict(row) for row in rows],
    })


_EXPORT_TABLES_OWNER = frozenset({'sync_status', 'sync_history', 'ret_credential_alerts'})
_EXPORT_TABLES_USER_ADMIN = frozenset({'users', 'ret_credential_alerts'})


@admin_panel_bp.route('/api/admin/export/excel', methods=['POST'])
@admin_required
def admin_export_excel():
    """Download an Admin Panel table view as Excel."""
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    table_key = str(data.get('table') or '').strip().lower()
    columns = [str(c) for c in (data.get('columns') or []) if str(c).strip()]
    rows = data.get('rows')
    if table_key not in _EXPORT_TABLES_OWNER | _EXPORT_TABLES_USER_ADMIN:
        return jsonify({'error': 'Unknown export table'}), 400
    if table_key in _EXPORT_TABLES_OWNER and not _is_owner(user):
        return jsonify({'error': 'Owner access required'}), 403
    if table_key == 'users' and not _can_access_user_admin(user):
        return jsonify({'error': 'Owner or NOC SYS access required'}), 403
    if not isinstance(rows, list) or not rows:
        return jsonify({'error': 'No rows to export'}), 400

    report_title = str(data.get('report_title') or table_key.replace('_', ' ').title())
    sheet_title = str(data.get('sheet_title') or report_title)[:31]
    filename_stem = str(data.get('filename_stem') or f'Admin_{table_key}')
    meta = data.get('meta') if isinstance(data.get('meta'), dict) else {}
    column_labels = data.get('column_labels') if isinstance(data.get('column_labels'), dict) else {}

    try:
        workbook, filename = build_table_workbook(
            filename_stem=filename_stem,
            report_title=report_title,
            sheet_title=sheet_title,
            columns=columns,
            rows=rows,
            meta={
                **meta,
                'Exported By': (user.get('username') if isinstance(user, dict) else user[1]),
                'Row Count': len(rows),
            },
        )
        log_activity(
            (user.get('id') if isinstance(user, dict) else user[0]),
            'admin_table_export',
            f'Exported {table_key} ({len(rows)} rows)',
        )
        return send_file(
            workbook,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500
