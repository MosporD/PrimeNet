"""
XML Parser Routes
Handles XML to Excel conversion functionality
"""

from flask import Blueprint, request, jsonify, send_file, render_template, redirect, url_for
from werkzeug.utils import secure_filename
import os
import tempfile
import uuid
from functools import wraps

# Import core processing logic
from ncm_core import XMLToExcelConverter
from database_enhanced import get_user_by_session, log_activity

xml_parser_bp = Blueprint('xml_parser', __name__)

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
        import xml.etree.ElementTree as ET
        tree = ET.parse(temp_path)
        root = tree.getroot()

        # Extract all unique parameter names
        parameters = set()
        for elem in root.iter():
            # Look for parameter elements (p tags) - handle namespace
            if elem.tag.endswith('p') or elem.tag == 'p':
                param_name = elem.get('name', '')
                if param_name:
                    parameters.add(param_name)

        parameters = sorted(list(parameters))

        # Store file info
        TEMP_FILES[file_id] = {
            'path': temp_path,
            'filename': filename,
            'parameters': parameters,
            'user_id': (user.get('id') if isinstance(user, dict) else user[0])
        }

        log_activity((user.get('id') if isinstance(user, dict) else user[0]), 'xml_upload', f'Uploaded {filename}')

        return jsonify({
            'success': True,
            'file_id': file_id,
            'filename': filename,
            'parameters': parameters
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
        data = request.get_json()
        file_id = data.get('file_id')
        selected_parameters = data.get('selected_parameters', [])

        if not file_id or file_id not in TEMP_FILES:
            return jsonify({'error': 'Invalid or expired file'}), 400

        file_info = TEMP_FILES[file_id]
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
            import xml.etree.ElementTree as ET
            tree = ET.parse(input_path)
            root = tree.getroot()

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

    except Exception as e:
        return jsonify({'error': str(e)}), 500

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

    except Exception as e:
        return jsonify({'error': str(e)}), 500
