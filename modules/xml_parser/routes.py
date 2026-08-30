"""
XML Parser Routes
Handles XML to Excel conversion functionality
"""

from flask import Blueprint, request, jsonify, send_file, render_template, redirect, url_for
from werkzeug.utils import secure_filename
import os
import json
import sqlite3
import tempfile
import uuid
from functools import wraps

# Import core processing logic
from ncm_core import XMLToExcelConverter
from database_enhanced import get_user_by_session, log_activity, get_db
from db.runtime import execute_query
from utils.xml_safety import parse_xml_file
from core.cm_plan_validate import validate_raml_plan

xml_parser_bp = Blueprint(
    'xml_parser', __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/xml_parser/static',
)

# Temporary storage for uploaded files
TEMP_FILES = {}

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

# ============================================================================
# PAGE ROUTES
# ============================================================================

@xml_parser_bp.route('/xml-parser')
@login_required
def xml_parser_page():
    """Render XML Parser page"""
    user = get_current_user()
    return render_template('xml_parser.html', user=format_user_data(user))

# ============================================================================
# API ROUTES
# ============================================================================

@xml_parser_bp.route('/api/xml-parser/upload', methods=['POST'])
def upload_xml():
    """Upload and analyze XML file"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not file.filename.endswith('.xml'):
        return jsonify({'error': 'Only XML files are allowed'}), 400

    try:
        # Generate unique file ID
        file_id = str(uuid.uuid4())

        # Save file temporarily
        filename = secure_filename(file.filename)
        temp_path = os.path.join(tempfile.gettempdir(), f"{file_id}_{filename}")
        file.save(temp_path)

        # Analyze XML to get available parameters
        root = parse_xml_file(temp_path)

        # Extract all unique parameter names
        parameters = set()
        for elem in root.iter():
            # Look for parameter elements (p tags) - handle namespace
            if elem.tag.endswith('p') or elem.tag == 'p':
                param_name = elem.get('name', '')
                if param_name:
                    parameters.add(param_name)

        parameters = sorted(list(parameters))

        validation = {"summary": {"errors": 0, "warnings": 0, "diffs": 0}, "findings": [], "mo_count": 0}
        try:
            validation = validate_raml_plan(temp_path)
        except Exception as exc:
            validation = {
                "success": False,
                "error": str(exc),
                "summary": {"errors": 0, "warnings": 0, "diffs": 0},
                "findings": [],
            }

        # Store file info
        TEMP_FILES[file_id] = {
            'path': temp_path,
            'filename': filename,
            'parameters': parameters,
            'user_id': (user.get('id') if isinstance(user, dict) else user[0]),
            'validation': validation,
        }

        log_activity((user.get('id') if isinstance(user, dict) else user[0]), 'xml_upload', f'Uploaded {filename}')

        return jsonify({
            'success': True,
            'file_id': file_id,
            'filename': filename,
            'parameters': parameters,
            'validation': validation,
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@xml_parser_bp.route('/api/xml-parser/convert', methods=['POST'])
def convert_xml():
    """Convert XML to Excel with optional parameter filtering"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        from flask import g
        data = getattr(g, 'sanitized_json', None) or request.get_json(silent=True) or {}
        file_id = data.get('file_id')
        selected_parameters = data.get('selected_parameters', [])

        if not file_id or file_id not in TEMP_FILES:
            return jsonify({'error': 'Invalid or expired file'}), 400

        file_info = TEMP_FILES[file_id]
        if file_info.get('user_id') != (user.get('id') if isinstance(user, dict) else user[0]):
            return jsonify({'error': 'Unauthorized file access'}), 403
        input_path = file_info['path']

        # Generate output path
        output_filename = file_info['filename'].replace('.xml', '.xlsx')
        output_path = os.path.join(tempfile.gettempdir(), f"output_{file_id}_{output_filename}")

        # Convert XML to Excel
        converter = XMLToExcelConverter(input_path, output_path)

        if selected_parameters:
            # Build parameter filter dictionary
            param_dict = {}
            # Get all MOs from XML
            root = parse_xml_file(input_path)

            # Find all MO elements and map selected parameters to their MOs
            for mo in root.iter('managedObject'):
                mo_class = mo.get('class', '')
                if mo_class:
                    mo_params = []
                    for param in mo.findall('.//p'):
                        param_name = param.get('name', '')
                        if param_name in selected_parameters:
                            mo_params.append(param_name)
                    if mo_params:
                        param_dict[mo_class] = mo_params

            converter.set_parameters(param_dict)

        # Convert
        success, message = converter.convert()

        if not success:
            return jsonify({'error': message}), 500

        # Store output file info
        TEMP_FILES[f"output_{file_id}"] = {
            'path': output_path,
            'filename': output_filename,
            'user_id': (user.get('id') if isinstance(user, dict) else user[0])
        }

        log_activity((user.get('id') if isinstance(user, dict) else user[0]), 'xml_convert', f'Converted {file_info["filename"]} to Excel')

        return jsonify({
            'success': True,
            'output_file': output_filename,
            'file_id': f"output_{file_id}"
        })

    except Exception:
        return jsonify({'error': 'Conversion failed'}), 500

@xml_parser_bp.route('/api/xml-parser/download/<filename>')
def download_file(filename):
    """Download converted Excel file"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        # Find file in temp storage
        file_info = None
        for key, info in TEMP_FILES.items():
            if info['filename'] == filename and info['user_id'] == (user.get('id') if isinstance(user, dict) else user[0]):
                file_info = info
                break

        if not file_info:
            return jsonify({'error': 'File not found'}), 404

        log_activity((user.get('id') if isinstance(user, dict) else user[0]), 'file_download', f'Downloaded {filename}')

        return send_file(
            file_info['path'],
            as_attachment=True,
            download_name=filename
        )

    except Exception:
        return jsonify({'error': 'Download failed'}), 500


def _uid(user):
    return user.get('id') if isinstance(user, dict) else user[0]


def _ensure_saved_views(conn):
    if not isinstance(conn, sqlite3.Connection):
        return
    conn.execute('''
        CREATE TABLE IF NOT EXISTS saved_views (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            module TEXT NOT NULL,
            name TEXT NOT NULL,
            state TEXT NOT NULL,
            is_public INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')


def _list_xml_profiles(user_id) -> list[dict]:
    conn = get_db()
    if isinstance(conn, sqlite3.Connection):
        conn.row_factory = sqlite3.Row
    _ensure_saved_views(conn)
    rows = execute_query(conn, '''
        SELECT name, state FROM saved_views
        WHERE user_id = ? AND module = ?
        ORDER BY updated_at DESC
    ''', (user_id, 'xml-parser')).fetchall()
    conn.close()
    profiles = []
    for row in rows:
        try:
            state = json.loads(row['state'] or '{}')
        except Exception:
            state = {}
        profiles.append({
            'name': row['name'],
            'parameters': state.get('parameters') or state.get('selected_params') or [],
        })
    return profiles


@xml_parser_bp.route('/api/xml-parser/validate', methods=['POST'])
def validate_xml_plan():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    file_id = data.get('file_id')
    if not file_id or file_id not in TEMP_FILES:
        return jsonify({'error': 'Invalid or expired file'}), 400
    info = TEMP_FILES[file_id]
    if info.get('user_id') != _uid(user):
        return jsonify({'error': 'Unauthorized file access'}), 403
    try:
        payload = validate_raml_plan(info['path'])
        info['validation'] = payload
        return jsonify({'success': True, **payload})
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500


@xml_parser_bp.route('/api/xml-parser/profiles', methods=['GET'])
@xml_parser_bp.route('/api/profiles/list', methods=['GET'])
def list_xml_profiles():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        profiles = _list_xml_profiles(_uid(user))
        return jsonify({'success': True, 'profiles': profiles})
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@xml_parser_bp.route('/api/xml-parser/profiles', methods=['POST'])
@xml_parser_bp.route('/api/profiles/save', methods=['POST'])
def save_xml_profile():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    name = str(data.get('profile_name') or data.get('name') or '').strip()
    params = data.get('selected_params') or data.get('parameters') or []
    if not name:
        return jsonify({'error': 'profile_name is required'}), 400
    if not isinstance(params, list):
        return jsonify({'error': 'selected_params must be a list'}), 400
    try:
        state = json.dumps({'parameters': [str(p) for p in params]})
        conn = get_db()
        if isinstance(conn, sqlite3.Connection):
            conn.row_factory = sqlite3.Row
        _ensure_saved_views(conn)
        existing = execute_query(conn, '''
            SELECT id FROM saved_views WHERE user_id = ? AND module = ? AND name = ?
        ''', (_uid(user), 'xml-parser', name)).fetchone()
        if existing:
            execute_query(conn, '''
                UPDATE saved_views SET state = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?
            ''', (state, existing['id']))
        else:
            execute_query(conn, '''
                INSERT INTO saved_views (id, user_id, module, name, state, is_public)
                VALUES (?, ?, ?, ?, ?, 0)
            ''', (uuid.uuid4().hex[:10], _uid(user), 'xml-parser', name, state))
        conn.commit()
        conn.close()
        log_activity(_uid(user), 'xml_profile_save', f'Saved XML parser profile {name}')
        return jsonify({'success': True, 'profile_name': name})
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500
