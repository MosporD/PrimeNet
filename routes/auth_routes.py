"""
Authentication Routes
Handles login, logout, registration, portal selection, and dashboard access
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
from core.module_access import allowed_hrefs_for_role, navigation_sections_for_role
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
    {
        'key': '2G', 'title': '2G', 'subtitle': 'GSM / EDGE', 'count': 0,
        'vendor_counts': {'Huawei': 0, 'Nokia': 0},
        'children': [{'label': 'Huawei', 'count': 0}, {'label': 'Nokia', 'count': 0}],
    },
    {
        'key': '3G', 'title': '3G', 'subtitle': 'WCDMA / UMTS', 'count': 0,
        'vendor_counts': {'Huawei': 0, 'Nokia': 0},
        'children': [{'label': 'Huawei', 'count': 0}, {'label': 'Nokia', 'count': 0}],
    },
    {
        'key': '4G-FDD', 'title': '4G - FDD', 'subtitle': 'LTE FDD', 'count': 0,
        'vendor_counts': {'Huawei': 0, 'Nokia': 0},
        'children': [{'label': 'Huawei', 'count': 0}, {'label': 'Nokia', 'count': 0}],
    },
    {
        'key': '4G-TDD', 'title': '4G - TDD', 'subtitle': 'LTE TDD', 'count': 0,
        'vendor_counts': {'Huawei': 0, 'Nokia': 0},
        'children': [{'label': 'Huawei', 'count': 0}, {'label': 'Nokia', 'count': 0}],
    },
    {
        'key': '5G', 'title': '5G', 'subtitle': 'NR', 'count': 0,
        'vendor_counts': {'Huawei': 0, 'Nokia': 0},
        'children': [{'label': 'Huawei', 'count': 0}, {'label': 'Nokia', 'count': 0}],
    },
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
    """Redirect to portal picker or login"""
    user = get_current_user()
    if user:
        return redirect(url_for('auth.portal_select'))
    return redirect(url_for('auth.login_page'))

@auth_bp.route('/login')
def login_page():
    """Render login page"""
    return render_template('login.html')

@auth_bp.route('/register')
def register_page():
    """Registration is disabled for internal-only deployment."""
    return redirect(url_for('auth.login_page'))

_PORTAL_COMING_SOON = {
    'marketing': {
        'id': 'marketing',
        'name': 'Marketing Portal',
        'blurb': 'Campaigns, outreach, and brand operations.',
    },
    'sales': {
        'id': 'sales',
        'name': 'Sales Portal',
        'blurb': 'Pipeline, accounts, and commercial workflows.',
    },
    'support': {
        'id': 'support',
        'name': 'Customer Support Portal',
        'blurb': 'Tickets, customer care, and service tools.',
    },
}

@auth_bp.route('/portals')
def portal_select():
    """Post-login portal picker."""
    user = get_current_user()
    if not user:
        return redirect(url_for('auth.login_page'))
    return render_template(
        'portal_select.html',
        user=format_user_data(user),
    )

@auth_bp.route('/portals/<portal_id>')
def portal_enter(portal_id):
    """Enter a portal, or show Coming soon for future portals."""
    user = get_current_user()
    if not user:
        return redirect(url_for('auth.login_page'))

    key = (portal_id or '').strip().lower()
    if key == 'engineering':
        return redirect(url_for('auth.dashboard'))

    portal = _PORTAL_COMING_SOON.get(key)
    if not portal:
        return redirect(url_for('auth.portal_select'))

    return render_template(
        'portal_coming_soon.html',
        user=format_user_data(user),
        portal=portal,
    )

@auth_bp.route('/dashboard')
def dashboard():
    """Render main dashboard.

    Site counts load asynchronously via ``/api/dashboard/operational-sites``
    so this page can paint immediately after portal entry.
    """
    user = get_current_user()
    if not user:
        return redirect(url_for('auth.login_page'))

    user_data = format_user_data(user)
    return render_template(
        'dashboard.html',
        user=user_data,
        allowed_hrefs=allowed_hrefs_for_role(user_data),
        tech_site_columns=[dict(c) for c in _DEFAULT_SITE_COLUMNS],
        total_sites=0,
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

            user_role = (user.get('role') if isinstance(user, dict) else user[6])
            response = make_response(jsonify({
                'success': True,
                'message': 'Login successful',
                'must_change_password': must_change_password,
                'user': {
                    'username': (user.get('username') if isinstance(user, dict) else user[1]),
                    'email': (user.get('email') if isinstance(user, dict) else user[2]),
                    'role': user_role,
                },
                'navigation_sections': navigation_sections_for_role(user_role),
                'allowed_hrefs': allowed_hrefs_for_role(user_role),
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

@auth_bp.route('/api/navigation/allowed', methods=['GET'])
def navigation_allowed():
    """Return feature-navigation sections permitted for the current user."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    role = user.get('role') if isinstance(user, dict) else user[6]
    return jsonify({
        'success': True,
        'role': role,
        'sections': navigation_sections_for_role(role),
        'allowed_hrefs': allowed_hrefs_for_role(role),
    })


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


@auth_bp.route('/api/dashboard/neighbor-health', methods=['GET'])
def dashboard_neighbor_health():
    """Neighbor database health (Owner / admin only)."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    if not _is_owner(user):
        return jsonify({'error': 'Owner access required'}), 403

    force = (request.args.get('refresh') or '').strip().lower() in ('1', 'true', 'yes')
    try:
        from core.neighbor_health import get_neighbor_health_cached

        payload = get_neighbor_health_cached(force_refresh=force)
        return jsonify({'success': True, **payload})
    except Exception:
        logger.exception('Neighbor health check failed')
        return jsonify({'success': False, 'error': 'Neighbor health check failed'}), 500


@auth_bp.route('/api/dashboard/network-activity', methods=['GET'])
def dashboard_network_activity():
    """Relative network traffic level (0..1) for dashboard visuals."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        from core.network_activity import get_network_activity

        force = (request.args.get('refresh') or '').strip().lower() in ('1', 'true', 'yes')
        payload = get_network_activity(force_refresh=force)
        resp = jsonify({'success': True, **payload})
        resp.headers['Cache-Control'] = 'no-store, private'
        return resp
    except Exception:
        logger.exception('Network activity check failed')
        return jsonify({'success': True, 'level': None, 'vendors': {}})


_SITE_MAP_MAX_POINTS = 550
_SITE_MAP_CACHE_SECONDS = 600
_site_map_cache = {'expires': 0.0, 'payload': None}

# Rough bounding box for Jordan — drops obviously bad coordinates.
_JO_LAT_MIN, _JO_LAT_MAX = 28.9, 33.6
_JO_LON_MIN, _JO_LON_MAX = 34.7, 39.5


def _thin_site_points(sites: list[dict], max_points: int) -> list[dict]:
    """Grid-thin sites so the map stays a representative, uncluttered sample."""
    if len(sites) <= max_points:
        return sites
    cell_deg = 0.02
    while cell_deg <= 0.25:
        buckets: dict[tuple[int, int], dict] = {}
        for site in sites:
            key = (int(site['lat'] / cell_deg), int(site['lon'] / cell_deg))
            buckets.setdefault(key, site)
        if len(buckets) <= max_points:
            return list(buckets.values())
        cell_deg *= 1.6
    return list(buckets.values())[:max_points]


@auth_bp.route('/api/dashboard/site-map', methods=['GET'])
def dashboard_site_map():
    """Unique on-air sites with coordinates for the dashboard Jordan map."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    import time as _time

    now = _time.time()
    if _site_map_cache['payload'] is not None and _site_map_cache['expires'] > now:
        return jsonify(_site_map_cache['payload'])

    try:
        from core.radio.metadata import list_cells

        by_site: dict[str, dict] = {}
        for row in list_cells():
            sid = str(row.get('site_id') or '').strip()
            lat = row.get('latitude')
            lon = row.get('longitude')
            if not sid or sid in by_site or lat is None or lon is None:
                continue
            if not (_JO_LAT_MIN <= lat <= _JO_LAT_MAX and _JO_LON_MIN <= lon <= _JO_LON_MAX):
                continue
            by_site[sid] = {
                'id': sid,
                'name': str(row.get('site_name') or '').strip(),
                'area': str(row.get('area') or '').strip(),
                'lat': round(float(lat), 5),
                'lon': round(float(lon), 5),
            }
        all_sites = list(by_site.values())
        shown = _thin_site_points(all_sites, _SITE_MAP_MAX_POINTS)
        payload = {
            'success': True,
            'sites': shown,
            'total_unique': len(all_sites),
            'shown': len(shown),
        }
    except Exception:
        logger.exception('Site map lookup failed')
        payload = {'success': True, 'sites': [], 'total_unique': 0, 'shown': 0}

    _site_map_cache['payload'] = payload
    _site_map_cache['expires'] = now + _SITE_MAP_CACHE_SECONDS
    resp = jsonify(payload)
    resp.headers['Cache-Control'] = 'no-store, private'
    return resp


_GLOBAL_SEARCH_MAX_RESULTS = 10


def _global_search_metadata(q: str) -> dict:
    """Sites / cells / PCI matches from the metadata cell union."""
    out = {'sites': [], 'cells': [], 'pci': []}
    like = f'%{q}%'
    union = perf_per_tech_union_sql_with_activity()
    conn = connect_metadata()
    try:
        site_rows = execute_query(conn, f'''
            SELECT CAST(site_id AS TEXT) AS site_id,
                   MAX(COALESCE(site_name, '')) AS site_name,
                   COUNT(*) AS cell_count,
                   GROUP_CONCAT(DISTINCT technology) AS technologies,
                   SUM(CASE WHEN activity_status = 'Active' THEN 1 ELSE 0 END) AS active_cells
            FROM ({union}) v
            WHERE site_id IS NOT NULL
              AND (CAST(site_id AS TEXT) LIKE ? OR site_name LIKE ?)
            GROUP BY CAST(site_id AS TEXT)
            ORDER BY LENGTH(CAST(site_id AS TEXT)), CAST(site_id AS TEXT)
            LIMIT ?
        ''', (like, like, _GLOBAL_SEARCH_MAX_RESULTS)).fetchall()
        out['sites'] = [dict(r) for r in site_rows]

        cell_rows = execute_query(conn, f'''
            SELECT cell_name, CAST(site_id AS TEXT) AS site_id, technology, vendor,
                   activity_status, CAST(pci AS TEXT) AS pci
            FROM ({union}) v
            WHERE cell_name LIKE ?
            ORDER BY LENGTH(cell_name), cell_name
            LIMIT ?
        ''', (like, _GLOBAL_SEARCH_MAX_RESULTS)).fetchall()
        out['cells'] = [dict(r) for r in cell_rows]

        if q.isdigit():
            pci_rows = execute_query(conn, f'''
                SELECT cell_name, CAST(site_id AS TEXT) AS site_id, technology, vendor,
                       activity_status, CAST(pci AS TEXT) AS pci
                FROM ({union}) v
                WHERE pci = ?
                ORDER BY technology, cell_name
                LIMIT ?
            ''', (int(q), _GLOBAL_SEARCH_MAX_RESULTS)).fetchall()
            out['pci'] = [dict(r) for r in pci_rows]
    finally:
        conn.close()
    return out


def _truncate_global_search_text(text: str, limit: int = 120) -> str:
    cleaned = ' '.join(str(text or '').split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + '…'


def _global_search_parameters(q: str) -> list:
    """Parameter dictionary matches (Nokia MO index + Huawei TOC), best-effort."""
    results = []
    try:
        from modules.parameter_dictionary.nokia_loader import search_nokia_entries

        for entry in search_nokia_entries(q, limit=4):
            entry_type = entry.get('type') or 'mo'
            if entry_type == 'parameter':
                param_name = entry.get('parameter') or ''
                mo_list = entry.get('mo_list') or []
                results.append({
                    'vendor': 'Nokia',
                    'name': param_name,
                    'detail': entry.get('description') or '',
                    'technology': '',
                    'sub': _truncate_global_search_text(entry.get('description') or ''),
                    'mo': mo_list[0] if mo_list else '',
                    'param': param_name,
                })
                continue

            mo_name = entry.get('mo') or ''
            params = entry.get('parameters') or []
            first_param = params[0] if params else {}
            results.append({
                'vendor': 'Nokia',
                'name': entry.get('description') or mo_name.split('/')[-1] or mo_name,
                'detail': entry.get('description') or '',
                'technology': entry.get('technology') or '',
                'sub': mo_name or (first_param.get('full_name') or first_param.get('name') or ''),
                'mo': mo_name,
                'param': first_param.get('name') or '',
            })
    except Exception:
        logger.debug('Nokia parameter search unavailable', exc_info=True)
    try:
        from modules.parameter_dictionary.knowledge import parse_huawei_toc

        ql = q.lower()
        hits = 0
        for entry in parse_huawei_toc():
            name = str(entry.get('name') or '')
            if ql in name.lower():
                results.append({
                    'vendor': 'Huawei',
                    'name': name,
                    'detail': '',
                    'technology': '',
                    'sub': '',
                    'huawei_url': entry.get('url') or '',
                })
                hits += 1
                if hits >= 4:
                    break
    except Exception:
        logger.debug('Huawei parameter search unavailable', exc_info=True)
    return results


@auth_bp.route('/api/global-search', methods=['GET'])
def global_search():
    """One search box: site IDs, cell names, PCIs, and parameter names."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    args = getattr(g, 'sanitized_args', None) or request.args
    q = str(args.get('q') or '').strip()
    if len(q) < 2:
        return jsonify({'success': True, 'query': q,
                        'sites': [], 'cells': [], 'pci': [], 'parameters': []})

    payload = {'success': True, 'query': q}
    try:
        payload.update(_global_search_metadata(q))
    except Exception:
        logger.exception('Global search metadata lookup failed')
        payload.update({'sites': [], 'cells': [], 'pci': []})
    payload['parameters'] = _global_search_parameters(q)
    resp = jsonify(payload)
    resp.headers['Cache-Control'] = 'no-store, private'
    return resp


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
