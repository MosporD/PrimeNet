"""
Excel Generator Routes
Handles Excel to XML conversion functionality
"""

from flask import Blueprint, request, jsonify, send_file, render_template, redirect, url_for
from werkzeug.utils import secure_filename
import os
import tempfile
import uuid
from functools import wraps

from ncm_core import ExcelToXMLConverter
from database_enhanced import get_user_by_session, log_activity
from core.cm_plan_validate import validate_raml_plan

excel_generator_bp = Blueprint(
    'excel_generator', __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/excel_generator/static',
)

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

@excel_generator_bp.route('/excel-generator')
@login_required
def excel_generator_page():
    """Render Excel Generator page"""
    user = get_current_user()
    return render_template('excel_generator.html', user=format_user_data(user))

@excel_generator_bp.route('/api/excel-generator/upload', methods=['POST'])
def upload_excel():
    """Upload Excel file and discover MO classes"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
        return jsonify({'error': 'Only Excel files are allowed'}), 400

    try:
        file_id = str(uuid.uuid4())
        filename = secure_filename(file.filename)
        temp_path = os.path.join(tempfile.gettempdir(), f"{file_id}_{filename}")
        file.save(temp_path)

        # Discover MO classes
        converter = ExcelToXMLConverter(temp_path, '')
        mo_classes = converter.discover_sheets()

        # Store file info for later conversion
        TEMP_FILES[file_id] = {
            'path': temp_path,
            'filename': filename,
            'mo_classes': mo_classes,
            'user_id': (user.get('id') if isinstance(user, dict) else user[0])
        }

        log_activity((user.get('id') if isinstance(user, dict) else user[0]), 'excel_upload', f'Uploaded {filename}')

        return jsonify({
            'success': True,
            'file_id': file_id,
            'mo_classes': mo_classes
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@excel_generator_bp.route('/api/excel-generator/convert', methods=['POST'])
def convert_excel():
    """Convert Excel to XML with selected operations"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        data = request.get_json()
        file_id = data.get('file_id')
        operations = data.get('operations', {})

        if not file_id or file_id not in TEMP_FILES:
            return jsonify({'error': 'File not found'}), 404

        file_info = TEMP_FILES[file_id]

        # Check user owns this file
        if file_info['user_id'] != (user.get('id') if isinstance(user, dict) else user[0]):
            return jsonify({'error': 'Unauthorized'}), 403

        input_path = file_info['path']
        filename = file_info['filename']

        output_filename = filename.replace('.xlsx', '_output.xml').replace('.xls', '_output.xml')
        output_path = os.path.join(tempfile.gettempdir(), f"output_{file_id}_{output_filename}")

        converter = ExcelToXMLConverter(input_path, output_path)
        converter.set_operations(operations)

        success, message = converter.convert()

        if not success:
            return jsonify({'error': message}), 500

        validation = {"summary": {"errors": 0, "warnings": 0, "diffs": 0}, "findings": []}
        try:
            validation = validate_raml_plan(output_path)
        except Exception as exc:
            validation = {"success": False, "error": str(exc), "summary": {"errors": 0, "warnings": 0, "diffs": 0}, "findings": []}

        TEMP_FILES[f"output_{file_id}"] = {
            'path': output_path,
            'filename': output_filename,
            'user_id': (user.get('id') if isinstance(user, dict) else user[0]),
            'validation': validation,
        }

        log_activity((user.get('id') if isinstance(user, dict) else user[0]), 'excel_convert', f'Converted {filename} to XML')

        return jsonify({
            'success': True,
            'output_file': output_filename,
            'file_id': f"output_{file_id}",
            'validation': validation,
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@excel_generator_bp.route('/api/excel-generator/download/<filename>')
def download_file(filename):
    """Download generated XML file"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
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
