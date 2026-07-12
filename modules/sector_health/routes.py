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


def _parse_all_cells_arg(raw: str) -> bool:
    return str(raw or '').strip().lower() in ('1', 'true', 'yes', 'on')


def _sector_health_page_context(*, all_cells: bool) -> dict:
    if all_cells:
        return {
            'all_cells': True,
            'page_title': 'Sector Health — All Cells',
            'page_heading': '📡 Sector Health — All Cells',
            'page_subtitle': (
                'Configured tech/band layers from CM metadata — includes inactive and off-air cells. '
                'LTE pies exclude L35.'
            ),
            'scope_note': 'Includes all configured cells regardless of activity status (admin_state / active_state).',
            'alt_view_href': '/sector-health',
            'alt_view_label': 'Active cells only',
            'report_href': '/reports',
            'report_label': 'All-cells Excel report',
        }
    return {
        'all_cells': False,
        'page_title': 'Sector Health',
        'page_heading': '📡 Sector Health',
        'page_subtitle': '2G / 3G / 5G sector counts; LTE pies (% of LTE sectors in view, excluding L35). Active cells only.',
        'scope_note': 'Only on-air cells per vendor activity rules (admin_state / active_state).',
        'alt_view_href': '/sector-health-all',
        'alt_view_label': 'All configured cells',
        'report_href': '/reports',
        'report_label': 'Sector Health report',
    }


@sector_health_bp.route('/sector-health')
@login_required
def sector_health_page():
    user = get_current_user()
    ctx = _sector_health_page_context(all_cells=False)
    return render_template('sector_health.html', user=format_user(user), **ctx)


@sector_health_bp.route('/sector-health-all')
@login_required
def sector_health_all_page():
    user = get_current_user()
    ctx = _sector_health_page_context(all_cells=True)
    return render_template('sector_health.html', user=format_user(user), **ctx)


@sector_health_bp.route('/api/sector-health/data')
@login_required
def sector_health_data():
    try:
        all_cells = _parse_all_cells_arg(request.args.get('all_cells', ''))
        payload = build_sector_health_api_response(
            area=str(request.args.get('area', '') or '').strip(),
            rat=str(request.args.get('rat', '') or '').strip(),
            search=str(request.args.get('q', '') or '').strip(),
            active_only=not all_cells,
        )
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

    return jsonify({'success': True, **payload})
