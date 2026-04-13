"""
Authentication Routes
Handles login, logout, registration, and dashboard access
"""

import logging
import sqlite3
from flask import Blueprint, request, jsonify, render_template, redirect, url_for, make_response
from database_enhanced import (
    create_user, authenticate_user, create_session,
    get_user_by_session, delete_session, log_activity
)
from sync_config import METADATA_DB
from sync.metadata_active_sql import perf_per_tech_union_sql_with_activity

logger = logging.getLogger(__name__)
auth_bp = Blueprint('auth', __name__)

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
        SELECT technology, site_id
        FROM ({union}) v
        WHERE activity_status = 'Active'
          AND site_id IS NOT NULL
          AND TRIM(COALESCE(CAST(site_id AS TEXT), '')) != ''
    '''
    try:
        conn = sqlite3.connect(METADATA_DB, timeout=15)
        rows = conn.execute(sql).fetchall()
        conn.close()
    except Exception as e:
        logger.exception('Dashboard operational site stats failed: %s', e)
        cols = [dict(c) for c in _DEFAULT_SITE_COLUMNS]
        return cols, 0

    buckets = {
        '2G': set(),
        '3G': set(),
        '4G-FDD': set(),
        '4G-TDD': set(),
        '5G': set(),
    }
    for tech, site_id in rows:
        if tech in buckets:
            buckets[tech].add(site_id)

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
        s = buckets.get(key, set())
        all_sites |= s
        columns.append({
            'key': key,
            'title': title,
            'subtitle': subtitle,
            'count': len(s),
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
    """Render registration page"""
    return render_template('register.html')

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
    """Register a new user"""
    try:
        data = request.get_json()
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')

        if not all([username, email, password]):
            return jsonify({'error': 'All fields are required'}), 400

        user_id = create_user(username, email, password)

        if user_id:
            log_activity(user_id, 'register', f'User {username} registered')
            return jsonify({
                'success': True,
                'message': 'Registration successful'
            })
        else:
            return jsonify({'error': 'Username or email already exists'}), 400

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@auth_bp.route('/api/login', methods=['POST'])
def login():
    """Authenticate user and create session"""
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')

        if not all([username, password]):
            return jsonify({'error': 'Username and password required'}), 400

        success, user = authenticate_user(username, password)

        if success and user:
            session_token = create_session((user.get('id') if isinstance(user, dict) else user[0]))
            log_activity((user.get('id') if isinstance(user, dict) else user[0]), 'login', f'User {username} logged in')

            response = make_response(jsonify({
                'success': True,
                'message': 'Login successful',
                'user': {
                    'username': (user.get('username') if isinstance(user, dict) else user[1]),
                    'email': (user.get('email') if isinstance(user, dict) else user[2]),
                    'role': (user.get('role') if isinstance(user, dict) else user[6])
                }
            }))

            response.set_cookie('session_token', session_token, httponly=True)
            return response
        else:
            return jsonify({'error': 'Invalid credentials'}), 401

    except Exception as e:
        return jsonify({'error': str(e)}), 500

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
        response.set_cookie('session_token', '', expires=0)
        return response

    except Exception as e:
        return jsonify({'error': str(e)}), 500


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
