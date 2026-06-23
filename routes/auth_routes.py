"""
Authentication Routes
Handles login, logout, registration, and dashboard access
"""

import logging
import threading
import time
from collections import defaultdict, deque
from flask import Blueprint, request, jsonify, render_template, redirect, url_for, make_response, g
from database_enhanced import (
    create_user, authenticate_user, create_session,
    get_user_by_session, delete_session, log_activity, is_password_change_required
)
from db.runtime import connect_metadata, execute_query
from modules.sync.metadata_active_sql import perf_per_tech_union_sql_with_activity

logger = logging.getLogger(__name__)
auth_bp = Blueprint('auth', __name__)

_LOGIN_RATE_LIMIT_ATTEMPTS = 5
_LOGIN_RATE_LIMIT_WINDOW_SEC = 2 * 60
_login_rate_lock = threading.Lock()
_login_attempts_by_ip = defaultdict(deque)
_login_attempts_by_ip_user = defaultdict(deque)


def _login_client_ip() -> str:
    forwarded = (request.headers.get('X-Forwarded-For') or '').strip()
    if forwarded:
        return forwarded.split(',')[0].strip() or 'unknown'
    return (request.remote_addr or 'unknown').strip() or 'unknown'


def _prune_login_attempts(buf: deque, now_ts: float) -> None:
    cutoff = now_ts - _LOGIN_RATE_LIMIT_WINDOW_SEC
    while buf and buf[0] < cutoff:
        buf.popleft()


def _login_rate_limit_remaining(ip: str, username: str) -> tuple[bool, int]:
    now_ts = time.time()
    key_user = f'{ip}:{(username or "").lower()}'
    with _login_rate_lock:
        ip_buf = _login_attempts_by_ip[ip]
        user_buf = _login_attempts_by_ip_user[key_user]
        _prune_login_attempts(ip_buf, now_ts)
        _prune_login_attempts(user_buf, now_ts)
        ip_limited = len(ip_buf) >= _LOGIN_RATE_LIMIT_ATTEMPTS
        user_limited = len(user_buf) >= _LOGIN_RATE_LIMIT_ATTEMPTS
        if not ip_limited and not user_limited:
            return False, 0
        next_retry_ip = int(max(1, _LOGIN_RATE_LIMIT_WINDOW_SEC - (now_ts - ip_buf[0]))) if ip_buf else 1
        next_retry_user = int(max(1, _LOGIN_RATE_LIMIT_WINDOW_SEC - (now_ts - user_buf[0]))) if user_buf else 1
        return True, max(next_retry_ip, next_retry_user)


def _record_login_failure(ip: str, username: str) -> None:
    now_ts = time.time()
    key_user = f'{ip}:{(username or "").lower()}'
    with _login_rate_lock:
        ip_buf = _login_attempts_by_ip[ip]
        user_buf = _login_attempts_by_ip_user[key_user]
        _prune_login_attempts(ip_buf, now_ts)
        _prune_login_attempts(user_buf, now_ts)
        ip_buf.append(now_ts)
        user_buf.append(now_ts)


def _clear_login_failures(ip: str, username: str) -> None:
    key_user = f'{ip}:{(username or "").lower()}'
    with _login_rate_lock:
        _login_attempts_by_ip_user.pop(key_user, None)


def reset_login_rate_limits() -> None:
    """Clear in-memory login lockouts (e.g. after policy change or admin reset)."""
    with _login_rate_lock:
        _login_attempts_by_ip.clear()
        _login_attempts_by_ip_user.clear()


reset_login_rate_limits()

_DEFAULT_SITE_COLUMNS = [
    {'key': '2G', 'title': '2G', 'subtitle': 'GSM / EDGE', 'count': 0},
    {'key': '3G', 'title': '3G', 'subtitle': 'WCDMA / UMTS', 'count': 0},
    {'key': '4G-FDD', 'title': '4G - FDD', 'subtitle': 'LTE FDD', 'count': 0},
    {'key': '4G-TDD', 'title': '4G - TDD', 'subtitle': 'LTE TDD', 'count': 0},
    {'key': '5G', 'title': '5G', 'subtitle': 'NR', 'count': 0},
]

def get_current_user():
    """Get current logged-in user"""
    session_token = request.cookies.get('session_token')
    if session_token:
        return get_user_by_session(session_token)
    return None

def get_operational_site_stats():
    """
    Distinct site counts per RAT from metadata, counting only cells whose
    vendor-specific rules mark them as on-air (activity_status = 'Active').
    4G-FDD and 4G-TDD are reported as separate columns.
    """
    union = perf_per_tech_union_sql_with_activity()
    sql = f'''
        SELECT technology, vendor, site_id
        FROM ({union}) v
        WHERE activity_status = 'Active'
          AND site_id IS NOT NULL
          AND TRIM(COALESCE(CAST(site_id AS TEXT), '')) != ''
    '''
    try:
        conn = connect_metadata()
        rows = [dict(r) for r in execute_query(conn, sql).fetchall()]
        conn.close()
    except Exception as e:
        logger.exception('Dashboard operational site stats failed: %s', e)
        cols = [dict(c) for c in _DEFAULT_SITE_COLUMNS]
        return cols, 0

    buckets = {
        '2G': {'all': set(), 'vendors': {'Huawei': set(), 'Nokia': set()}},
        '3G': {'all': set(), 'vendors': {'Huawei': set(), 'Nokia': set()}},
        '4G-FDD': {'all': set(), 'vendors': {'Huawei': set(), 'Nokia': set()}},
        '4G-TDD': {'all': set(), 'vendors': {'Huawei': set(), 'Nokia': set()}},
        '5G': {'all': set(), 'vendors': {'Huawei': set(), 'Nokia': set()}},
    }
    for row in rows:
        tech = row.get('technology')
        site_id = row.get('site_id')
        vendor = str(row.get('vendor') or '').strip().title()
        if tech in buckets and site_id is not None:
            buckets[tech]['all'].add(site_id)
            if vendor in ('Huawei', 'Nokia'):
                buckets[tech]['vendors'][vendor].add(site_id)

    order = [
        ('2G', '2G', 'GSM / EDGE'),
        ('3G', '3G', 'WCDMA / UMTS'),
        ('4G-FDD', '4G - FDD', 'LTE FDD'),
        ('4G-TDD', '4G - TDD', 'LTE TDD'),
        ('5G', '5G', 'NR'),
    ]
    columns = []
    all_sites = set()
    for key, title, subtitle in order:
        bucket = buckets.get(key, {'all': set(), 'vendors': {'Huawei': set(), 'Nokia': set()}})
        s = bucket['all']
        all_sites |= s
        huawei_count = len(bucket['vendors']['Huawei'])
        nokia_count = len(bucket['vendors']['Nokia'])
        columns.append({
            'key': key,
            'title': title,
            'subtitle': subtitle,
            'count': len(s),
            'vendor_counts': {
                'Huawei': huawei_count,
                'Nokia': nokia_count,
            },
            'children': [
                {'label': 'Huawei', 'count': huawei_count},
                {'label': 'Nokia', 'count': nokia_count},
            ],
        })
    return columns, len(all_sites)


def format_user_data(user):
    """Format user data consistently for templates"""
    if not user:
        return None
    if isinstance(user, dict):
        return {
            'id': user.get('id'),
            'username': user.get('username'),
            'email': user.get('email'),
            'role': user.get('role')
        }
    else:
        return {
            'id': (user.get('id') if isinstance(user, dict) else user[0]),
            'username': (user.get('username') if isinstance(user, dict) else user[1]),
            'email': (user.get('email') if isinstance(user, dict) else user[2]),
            'role': (user.get('role') if isinstance(user, dict) else user[6])
        }

# ============================================================================
# PAGE ROUTES
# ============================================================================

@auth_bp.route('/')
def index():
    """Redirect to dashboard or login"""
    user = get_current_user()
    if user:
        return redirect(url_for('auth.dashboard'))
    return redirect(url_for('auth.login_page'))

@auth_bp.route('/login')
def login_page():
    """Render login page"""
    return render_template('login.html')

@auth_bp.route('/register')
def register_page():
    """Registration is disabled for internal-only deployment."""
    return redirect(url_for('auth.login_page'))

@auth_bp.route('/dashboard')
def dashboard():
    """Render main dashboard"""
    user = get_current_user()
    if not user:
        return redirect(url_for('auth.login_page'))

    tech_site_columns, _ = get_operational_site_stats()
    return render_template(
        'dashboard.html',
        user=format_user_data(user),
        tech_site_columns=tech_site_columns,
    )

# ============================================================================
# API ROUTES
# ============================================================================

@auth_bp.route('/api/register', methods=['POST'])
def register():
    """Registration is disabled."""
    return jsonify({'error': 'Self-registration is disabled. Contact administrator.'}), 403

@auth_bp.route('/api/login', methods=['POST'])
def login():
    """Authenticate user and create session"""
    try:
        data = (getattr(g, 'sanitized_json', None) or request.get_json() or {})
        username = (data.get('username') or '').strip()
        password = data.get('password')
        client_ip = _login_client_ip()

        limited, retry_after = _login_rate_limit_remaining(client_ip, username)
        if limited:
            response = jsonify({
                'error': 'Too many login attempts. Try again later.',
                'retry_after_seconds': retry_after,
            })
            response.status_code = 429
            response.headers['Retry-After'] = str(retry_after)
            return response

        if not username or password is None or password == '':
            return jsonify({'error': 'Username and password required'}), 400

        success, user = authenticate_user(username, password)

        if success and user:
            _clear_login_failures(client_ip, username)
            session_token = create_session((user.get('id') if isinstance(user, dict) else user[0]))
            log_activity((user.get('id') if isinstance(user, dict) else user[0]), 'login', f'User {username} logged in')
            must_change_password = bool(user.get('must_change_password')) if isinstance(user, dict) else is_password_change_required({
                'force_password_change': user[8] if len(user) > 8 else 1,
                'password_changed_at': user[7] if len(user) > 7 else None,
            })

            response = make_response(jsonify({
                'success': True,
                'message': 'Login successful',
                'must_change_password': must_change_password,
                'user': {
                    'username': (user.get('username') if isinstance(user, dict) else user[1]),
                    'email': (user.get('email') if isinstance(user, dict) else user[2]),
                    'role': (user.get('role') if isinstance(user, dict) else user[6])
                }
            }))

            secure_cookie = (request.headers.get('X-Forwarded-Proto') == 'https') or request.is_secure
            response.set_cookie(
                'session_token',
                session_token,
                httponly=True,
                secure=secure_cookie,
                samesite='Lax',
                path='/',
            )
            return response
        else:
            _record_login_failure(client_ip, username)
            return jsonify({'error': 'Invalid credentials'}), 401

    except Exception:
        logger.exception('Login error')
        return jsonify({'error': 'Internal server error'}), 500

@auth_bp.route('/api/logout', methods=['POST'])
def logout():
    """Logout user and delete session"""
    try:
        session_token = request.cookies.get('session_token')

        if session_token:
            user = get_user_by_session(session_token)
            if user:
                username = user.get('username') if isinstance(user, dict) else user[1]
                log_activity((user.get('id') if isinstance(user, dict) else user[0]), 'logout', f'User {username} logged out')
            delete_session(session_token)

        response = make_response(jsonify({'success': True}))
        secure_cookie = (request.headers.get('X-Forwarded-Proto') == 'https') or request.is_secure
        response.set_cookie(
            'session_token',
            '',
            expires=0,
            httponly=True,
            secure=secure_cookie,
            samesite='Lax',
            path='/',
        )
        return response

    except Exception:
        logger.exception('Logout error')
        return jsonify({'error': 'Internal server error'}), 500


def _is_owner(user) -> bool:
    if not user:
        return False
    role = user.get('role') if isinstance(user, dict) else (user[6] if len(user) > 6 else '')
    return str(role or '').strip().lower() == 'admin'


@auth_bp.route('/api/dashboard/pm-health', methods=['GET'])
def dashboard_pm_health():
    """PM database health (Owner / admin only)."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    if not _is_owner(user):
        return jsonify({'error': 'Owner access required'}), 403

    force = (request.args.get('refresh') or '').strip().lower() in ('1', 'true', 'yes')
    try:
        from core.pm_health import get_pm_health_cached

        payload = get_pm_health_cached(force_refresh=force)
        return jsonify({'success': True, **payload})
    except Exception:
        logger.exception('PM health check failed')
        return jsonify({'success': False, 'error': 'PM health check failed'}), 500


@auth_bp.route('/api/dashboard/operational-sites', methods=['GET'])
def dashboard_operational_sites():
    """Return latest operational site counts per technology."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    tech_site_columns, total_sites = get_operational_site_stats()
    resp = jsonify({
        'success': True,
        'tech_site_columns': tech_site_columns,
        'total_sites': total_sites,
    })
    resp.headers['Cache-Control'] = 'no-store, private'
    resp.headers['Pragma'] = 'no-cache'
    return resp
