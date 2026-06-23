"""
Sector Health — interactive view of sector tech-layer coverage (same data as the Sector Health report).
"""

from flask import Blueprint, jsonify, render_template, redirect, request, url_for
from functools import wraps

from database_enhanced import get_user_by_session
from modules.reports.sector_coverage_data import build_sector_health_api_response

sector_health_bp = Blueprint(
    'sector_health',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/sector-health/static',
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


def format_user(user):
    if not user:
        return None
    return {'id': user.get('id'), 'username': user.get('username'), 'role': user.get('role')}


def get_current_user():
    token = request.cookies.get('session_token')
    return get_user_by_session(token) if token else None


@sector_health_bp.route('/sector-health')
@login_required
def sector_health_page():
    user = get_current_user()
    return render_template('sector_health.html', user=format_user(user))


@sector_health_bp.route('/api/sector-health/data')
@login_required
def sector_health_data():
    try:
        payload = build_sector_health_api_response(
            area=str(request.args.get('area', '') or '').strip(),
            rat=str(request.args.get('rat', '') or '').strip(),
            search=str(request.args.get('q', '') or '').strip(),
        )
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

    return jsonify({'success': True, **payload})
