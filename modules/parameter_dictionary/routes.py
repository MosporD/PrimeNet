"""
Parameter Dictionary Routes
Handles MO parameter browsing functionality
"""

import os

from flask import Blueprint, request, jsonify, render_template, redirect, url_for, send_from_directory, abort, g
from functools import wraps

from database_enhanced import get_user_by_session, log_activity
from .knowledge import parse_huawei_toc
from .ai_service import answer_question
from .nokia_loader import get_nokia_index_payload, get_nokia_mo_parameters, load_nokia_data, search_nokia_parameters

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


HUAWEI_PARAMS_DIR = os.path.join(os.path.dirname(__file__), "huawei_params")


@parameter_dictionary_bp.route('/parameter-dictionary')
@login_required
def parameter_dictionary_page():
    """Render Parameter Dictionary page"""
    user = get_current_user()
    return render_template('parameter_dictionary.html', user=format_user_data(user))


@parameter_dictionary_bp.route('/parameter-dictionary/huawei/')
@parameter_dictionary_bp.route('/parameter-dictionary/huawei/<path:filepath>')
@login_required
def huawei_params_viewer(filepath='sran-para-homepage.html'):
    """Serve extracted Huawei CHM content."""
    safe = os.path.normpath(filepath)
    if safe.startswith('..') or os.path.isabs(safe):
        abort(404)
    full = os.path.join(HUAWEI_PARAMS_DIR, safe)
    if not os.path.isfile(full):
        abort(404)
    directory = os.path.dirname(full)
    filename = os.path.basename(full)
    return send_from_directory(directory, filename)


@parameter_dictionary_bp.route('/api/parameter-dictionary/huawei-toc')
def huawei_toc():
    """Return the full Huawei TOC for client-side search."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    toc = parse_huawei_toc()
    return jsonify({"success": True, "entries": toc, "total": len(toc)})


@parameter_dictionary_bp.route('/api/parameter-dictionary/list', methods=['GET'])
def list_mos():
    """Get list of all MOs with their parameters"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        payload = get_nokia_index_payload()
        meta = payload.get("meta") or {}

        log_activity((user.get('id') if isinstance(user, dict) else user[0]), 'mo_browse', 'Browsed parameter dictionary')

        return jsonify({
            'success': True,
            'columns': payload.get('columns') or [],
            'mo_index': payload.get('mo_index') or [],
            'meta': {
                'source': meta.get('source'),
                'mo_count': meta.get('mo_count'),
                'param_count': meta.get('param_count'),
                'row_count': meta.get('row_count'),
                'technologies': meta.get('technologies') or [],
                'categories': meta.get('categories') or [],
            },
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@parameter_dictionary_bp.route('/api/parameter-dictionary/nokia/mo', methods=['GET'])
def nokia_mo_parameters():
    """Return Excel-row parameters for a single MO class."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    mo_name = (request.args.get('mo') or '').strip()
    if not mo_name:
        return jsonify({'error': 'Missing mo query parameter'}), 400

    try:
        payload = get_nokia_mo_parameters(mo_name)
        return jsonify({'success': True, **payload})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@parameter_dictionary_bp.route('/api/parameter-dictionary/nokia/search', methods=['GET'])
def nokia_parameter_search():
    """Search Nokia parameters across all MO classes."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    query = (request.args.get('q') or '').strip()
    limit = min(500, max(1, int(request.args.get('limit', 500))))

    try:
        result = search_nokia_parameters(query, limit=limit)
        return jsonify({'success': True, 'query': query, **result})
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
        search_term = (data.get('search') or '').lower()
        results = []

        payload = get_nokia_index_payload()
        mos_data = load_nokia_data().get('mos') or {}
        for mo_name, mo_info in mos_data.items():
            leaf = (mo_info.get('leaf') or mo_name.split('/')[-1]).lower()
            if search_term in mo_name.lower() or search_term in leaf:
                results.append({
                    'mo': mo_name,
                    'description': mo_info.get('leaf') or mo_name,
                    'category': mo_info.get('category'),
                    'technology': mo_info.get('technology'),
                })
                continue
            for param in mo_info.get('parameters') or []:
                blob = ' '.join(str(param.get(col) or '') for col in (payload.get('columns') or [])).lower()
                if search_term in blob:
                    results.append({
                        'mo': mo_name,
                        'parameter': param.get('Abbreviated Name'),
                        'description': param.get('Description'),
                        'category': param.get('Parameter Category'),
                        'technology': param.get('Technology'),
                    })
                    break

        log_activity((user.get('id') if isinstance(user, dict) else user[0]), 'mo_search', f'Searched: {search_term}')

        return jsonify({
            'success': True,
            'results': results
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@parameter_dictionary_bp.route('/api/parameter-dictionary/ai/ask', methods=['POST'])
@login_required
def ai_ask():
    """Answer natural-language questions about Nokia/Huawei parameters."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    body = getattr(g, 'sanitized_json', None) or {}
    question = (body.get('question') or '').strip()
    vendor = (body.get('vendor') or 'all').strip().lower()

    if len(question) < 3:
        return jsonify({'error': 'Please enter a question with at least 3 characters.'}), 400
    if len(question) > 500:
        return jsonify({'error': 'Question is too long (max 500 characters).'}), 400
    if vendor not in ('all', 'nokia', 'huawei'):
        vendor = 'all'

    try:
        result = answer_question(question, vendor=vendor)
        log_activity(
            (user.get('id') if isinstance(user, dict) else user[0]),
            'param_dict_ai',
            f'AI ask ({vendor}): {question[:120]}',
        )
        return jsonify({
            'success': True,
            'question': question,
            'answer': result.get('answer'),
            'sources': result.get('sources') or [],
            'mode': result.get('mode'),
            'vendor': vendor,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
