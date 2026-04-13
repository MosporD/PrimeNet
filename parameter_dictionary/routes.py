"""
Parameter Dictionary Routes
Handles MO parameter browsing functionality
"""

from flask import Blueprint, request, jsonify, render_template, redirect, url_for
from functools import wraps

from database_enhanced import get_user_by_session, log_activity

try:
    from mo_descriptions import (
        MO_DESCRIPTIONS, MO_CATEGORIES, PARAM_DESCRIPTIONS,
        get_mo_params, get_param_description,
        get_mo_description, get_mo_category
    )
    MO_DESCRIPTIONS_AVAILABLE = True
except ImportError:
    MO_DESCRIPTIONS = {}
    MO_CATEGORIES = {}
    PARAM_DESCRIPTIONS = {}
    MO_DESCRIPTIONS_AVAILABLE = False
    def get_mo_params(mo): return []
    def get_param_description(param): return "No description available"
    def get_mo_description(mo): return "No description available"
    def get_mo_category(mo): return "Other"

parameter_dictionary_bp = Blueprint(
    'parameter_dictionary', __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/parameter_dictionary/static',
)

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


@parameter_dictionary_bp.route('/parameter-dictionary')
@login_required
def parameter_dictionary_page():
    """Render Parameter Dictionary page"""
    user = get_current_user()
    return render_template('parameter_dictionary.html', user=format_user_data(user))

@parameter_dictionary_bp.route('/api/parameter-dictionary/list', methods=['GET'])
def list_mos():
    """Get list of all MOs with their parameters"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        mos_data = {}

        if MO_DESCRIPTIONS_AVAILABLE:
            for mo_name in MO_DESCRIPTIONS.keys():
                params = get_mo_params(mo_name)
                param_list = []

                for param in params:
                    param_list.append({
                        'name': param,
                        'description': get_param_description(param)
                    })

                mos_data[mo_name] = {
                    'description': get_mo_description(mo_name),
                    'category': get_mo_category(mo_name),
                    'parameters': param_list
                }
        else:
            mos_data = {
                'Example_MO': {
                    'description': 'MO descriptions not available',
                    'category': 'System',
                    'parameters': []
                }
            }

        log_activity((user.get('id') if isinstance(user, dict) else user[0]), 'mo_browse', 'Browsed parameter dictionary')

        return jsonify({
            'success': True,
            'mos': mos_data
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@parameter_dictionary_bp.route('/api/parameter-dictionary/search', methods=['POST'])
def search_parameters():
    """Search for specific parameters or MOs"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        data = request.get_json()
        search_term = data.get('search', '').lower()

        results = []

        if MO_DESCRIPTIONS_AVAILABLE:
            for mo_name, mo_desc in MO_DESCRIPTIONS.items():
                if search_term in mo_name.lower() or search_term in mo_desc.lower():
                    results.append({
                        'mo': mo_name,
                        'description': mo_desc,
                        'category': get_mo_category(mo_name)
                    })

        log_activity((user.get('id') if isinstance(user, dict) else user[0]), 'mo_search', f'Searched: {search_term}')

        return jsonify({
            'success': True,
            'results': results
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
