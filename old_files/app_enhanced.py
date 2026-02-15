"""
Nokia Configuration Manager - Enhanced Web Version
Flask Backend with REST API + Authentication + Parameter Selection + Tasks
"""

from flask import Flask, request, jsonify, send_file, render_template, redirect, url_for, make_response
from werkzeug.utils import secure_filename
import os
import tempfile
import traceback
from datetime import datetime
import uuid
from functools import wraps
import json

# Import core processing logic
import sys
sys.path.append(os.path.dirname(__file__))

from ncm_core import (
    XMLToExcelConverter,
    ExcelToXMLConverter,
    XMLComparator
)

# Import enhanced authentication + task management
from database_enhanced import (
    init_db, create_user, authenticate_user, create_session,
    get_user_by_session, delete_session, log_activity, get_all_users,
    # Filter profiles
    save_filter_profile, get_filter_profiles, delete_filter_profile,
    # Task management
    create_task, get_tasks, update_task_status, add_task_comment,
    get_task_updates, get_task_by_id, assign_task
)

# Import MO descriptions
try:
    from mo_descriptions import (
        MO_DESCRIPTIONS, MO_CATEGORIES, PARAM_DESCRIPTIONS,
        EMBEDDED_CATEGORIZATION, get_mo_params, get_param_description,
        get_mo_description, get_mo_category
    )
    MO_DESCRIPTIONS_AVAILABLE = True
except Exception as e:
    print(f"Warning: Could not load mo_descriptions: {e}")
    MO_DESCRIPTIONS = {}
    MO_CATEGORIES = {}
    PARAM_DESCRIPTIONS = {}
    EMBEDDED_CATEGORIZATION = {'param_to_mos': {}, 'mo_to_params': {}}
    MO_DESCRIPTIONS_AVAILABLE = False
    def get_mo_params(mo): return []
    def get_param_description(param): return "No description available"
    def get_mo_description(mo): return "No description available"
    def get_mo_category(mo): return "Other"

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB
app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()
app.config['SECRET_KEY'] = 'your-secret-key-change-this-in-production'

TEMP_FILES = {}

# ============================================================================
# AUTHENTICATION MIDDLEWARE
# ============================================================================

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        session_token = request.cookies.get('session_token')
        
        if not session_token:
            return redirect(url_for('login_page'))
        
        user = get_user_by_session(session_token)
        if not user:
            return redirect(url_for('login_page'))
        
        request.current_user = user
        return f(*args, **kwargs)
    
    return decorated_function

def get_current_user():
    """Get current logged-in user"""
    session_token = request.cookies.get('session_token')
    if session_token:
        return get_user_by_session(session_token)
    return None

def cleanup_temp_files(session_id):
    """Clean up temporary files for a session"""
    if session_id in TEMP_FILES:
        for file_path in TEMP_FILES[session_id]:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                print(f"Error cleaning up {file_path}: {e}")
        del TEMP_FILES[session_id]

def save_temp_file(file, session_id):
    """Save uploaded file temporarily and track it"""
    if not file:
        return None
    
    filename = secure_filename(file.filename)
    temp_path = os.path.join(tempfile.gettempdir(), f"{session_id}_{filename}")
    file.save(temp_path)
    
    if session_id not in TEMP_FILES:
        TEMP_FILES[session_id] = []
    TEMP_FILES[session_id].append(temp_path)
    
    return temp_path

# ============================================================================
# AUTHENTICATION ROUTES
# ============================================================================

@app.route('/login', methods=['GET'])
def login_page():
    """Login page"""
    if get_current_user():
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/register', methods=['GET'])
def register_page():
    """Registration page"""
    if get_current_user():
        return redirect(url_for('index'))
    return render_template('register.html')

@app.route('/api/login', methods=['POST'])
def api_login():
    """Login API endpoint"""
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    
    success, user = authenticate_user(username, password)
    
    if success:
        session_token = create_session(user['id'])
        log_activity(user['id'], 'login', ip_address=request.remote_addr)
        
        response = make_response(jsonify({
            'success': True,
            'user': {
                'username': user['username'],
                'email': user['email'],
                'full_name': user['full_name'],
                'role': user['role']
            }
        }))
        response.set_cookie('session_token', session_token, max_age=24*60*60, httponly=True)
        
        return response
    else:
        return jsonify({'error': 'Invalid username or password'}), 401

@app.route('/api/register', methods=['POST'])
def api_register():
    """Registration API endpoint"""
    data = request.get_json()
    
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    full_name = data.get('full_name')
    department = data.get('department')
    
    if not username or not email or not password:
        return jsonify({'error': 'Username, email, and password required'}), 400
    
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400
    
    success, result = create_user(username, email, password, full_name, department)
    
    if success:
        return jsonify({'success': True, 'message': 'Registration successful'}), 201
    else:
        return jsonify({'error': result}), 400

@app.route('/api/logout', methods=['POST'])
def api_logout():
    """Logout API endpoint"""
    session_token = request.cookies.get('session_token')
    
    if session_token:
        user = get_user_by_session(session_token)
        if user:
            log_activity(user['id'], 'logout', ip_address=request.remote_addr)
        delete_session(session_token)
    
    response = make_response(jsonify({'success': True}))
    response.set_cookie('session_token', '', expires=0)
    
    return response

@app.route('/api/current-user', methods=['GET'])
def api_current_user():
    """Get current user info"""
    user = get_current_user()
    if user:
        return jsonify({
            'username': user['username'],
            'email': user['email'],
            'full_name': user['full_name'],
            'department': user['department'],
            'role': user['role']
        })
    return jsonify({'error': 'Not logged in'}), 401

# ============================================================================
# MAIN APPLICATION ROUTES
# ============================================================================

@app.route('/')
@login_required
def index():
    """Main page"""
    try:
        user = request.current_user
        user_data = {
            'username': user.get('username', 'User'),
            'email': user.get('email', ''),
            'full_name': user.get('full_name', user.get('username', 'User')),
            'department': user.get('department', ''),
            'role': user.get('role', 'user')
        }
        return render_template('index.html', user=user_data)
    except Exception as e:
        print(f"Error loading index page: {e}")
        traceback.print_exc()
        return f"Error loading page: {str(e)}", 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'version': '2.0'})

# ============================================================================
# PARAMETER SELECTION API
# ============================================================================

@app.route('/api/mo-list', methods=['GET'])
@login_required
def get_mo_list():
    """Get list of all MO classes with descriptions"""
    try:
        mo_data = []
        
        if MO_DESCRIPTIONS_AVAILABLE:
            mo_to_params = EMBEDDED_CATEGORIZATION.get('mo_to_params', {})
            
            for mo in sorted(mo_to_params.keys()):
                mo_data.append({
                    'name': mo,
                    'param_count': len(mo_to_params[mo])
                })
        
        return jsonify({
            'success': True,
            'mos': mo_data,
            'count': len(mo_data)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/mo-parameters', methods=['POST'])
@login_required
def get_mo_parameters():
    """Get parameters for selected MO classes"""
    data = request.get_json()
    mo_classes = data.get('mo_classes', [])
    
    if not mo_classes:
        return jsonify({'error': 'No MO classes specified'}), 400
    
    try:
        all_params = set()
        
        for mo in mo_classes:
            params = get_mo_params(mo)
            if params:
                all_params.update(params)
            elif MO_DESCRIPTIONS_AVAILABLE:
                mo_to_params = EMBEDDED_CATEGORIZATION.get('mo_to_params', {})
                all_params.update(mo_to_params.get(mo, []))
        
        param_list = []
        for param in sorted(all_params):
            param_list.append({
                'name': param,
                'description': get_param_description(param)
            })
        
        return jsonify({
            'success': True,
            'parameters': param_list,
            'count': len(param_list)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================================
# FILTER PROFILE API
# ============================================================================

@app.route('/api/profiles', methods=['GET'])
@login_required
def list_profiles():
    """Get all filter profiles for current user"""
    user = request.current_user
    
    try:
        profiles = get_filter_profiles(user['id'])
        return jsonify({
            'success': True,
            'profiles': profiles
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/profiles', methods=['POST'])
@login_required
def save_profile():
    """Save filter profile"""
    user = request.current_user
    data = request.get_json()
    
    profile_name = data.get('profile_name')
    filter_data = data.get('filter_data')
    description = data.get('description', '')
    is_shared = data.get('is_shared', False)
    
    if not profile_name or not filter_data:
        return jsonify({'error': 'Profile name and filter data required'}), 400
    
    try:
        success, result = save_filter_profile(
            user['id'], profile_name, filter_data, description, is_shared
        )
        
        if success:
            log_activity(user['id'], 'save_profile', details=profile_name)
            return jsonify({'success': True, 'message': 'Profile saved'})
        else:
            return jsonify({'error': result}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/profiles/<int:profile_id>', methods=['DELETE'])
@login_required
def delete_profile(profile_id):
    """Delete filter profile"""
    user = request.current_user
    
    try:
        success = delete_filter_profile(profile_id, user['id'])
        
        if success:
            log_activity(user['id'], 'delete_profile', details=f'Profile {profile_id}')
            return jsonify({'success': True, 'message': 'Profile deleted'})
        else:
            return jsonify({'error': 'Profile not found or access denied'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================================
# ENHANCED XML TO EXCEL (with parameter filtering)
# ============================================================================

@app.route('/api/xml-to-excel', methods=['POST'])
@login_required
def xml_to_excel():
    """Convert XML to Excel with optional parameter filtering"""
    session_id = str(uuid.uuid4())
    user = request.current_user
    
    try:
        if 'xml_file' not in request.files:
            return jsonify({'error': 'No XML file provided'}), 400
        
        xml_file = request.files['xml_file']
        if xml_file.filename == '':
            return jsonify({'error': 'Empty filename'}), 400
        
        # Get filter data (if provided)
        filter_data_str = request.form.get('filter_data')
        filter_data = json.loads(filter_data_str) if filter_data_str else {}
        
        # Save files
        xml_path = save_temp_file(xml_file, session_id)
        
        # Create output path
        output_filename = f"Nokia_Config_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        output_path = os.path.join(tempfile.gettempdir(), f"{session_id}_{output_filename}")
        TEMP_FILES[session_id].append(output_path)
        
        # Convert
        converter = XMLToExcelConverter(xml_path, output_path)
        
        if filter_data:
            converter.set_parameters(filter_data)
        
        success, message = converter.convert()
        
        if not success:
            cleanup_temp_files(session_id)
            return jsonify({'error': message}), 500
        
        # Log activity
        log_activity(user['id'], 'xml_to_excel', details=f'File: {xml_file.filename}')
        
        # Send file
        response = send_file(
            output_path,
            as_attachment=True,
            download_name=output_filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
        @response.call_on_close
        def cleanup():
            cleanup_temp_files(session_id)
        
        return response
        
    except Exception as e:
        cleanup_temp_files(session_id)
        error_msg = f"Error: {str(e)}\n{traceback.format_exc()}"
        print(error_msg)
        return jsonify({'error': str(e)}), 500

# ============================================================================
# EXCEL TO XML CONVERSION
# ============================================================================

@app.route('/api/discover-sheets', methods=['POST'])
@login_required
def discover_sheets():
    """Discover MO classes from Excel file"""
    session_id = str(uuid.uuid4())

    try:
        if 'excel_file' not in request.files:
            return jsonify({'error': 'No Excel file provided'}), 400

        excel_file = request.files['excel_file']
        if excel_file.filename == '':
            return jsonify({'error': 'Empty filename'}), 400

        # Save file
        excel_path = save_temp_file(excel_file, session_id)

        # Discover sheets
        converter = ExcelToXMLConverter(excel_path, None)
        mo_classes = converter.discover_sheets()

        # Clean up
        cleanup_temp_files(session_id)

        return jsonify({
            'success': True,
            'mo_classes': mo_classes
        })

    except Exception as e:
        cleanup_temp_files(session_id)
        return jsonify({'error': str(e)}), 500

@app.route('/api/excel-to-xml', methods=['POST'])
@login_required
def excel_to_xml():
    """Convert Excel to XML"""
    session_id = str(uuid.uuid4())
    user = request.current_user

    try:
        if 'excel_file' not in request.files:
            return jsonify({'error': 'No Excel file provided'}), 400

        excel_file = request.files['excel_file']
        if excel_file.filename == '':
            return jsonify({'error': 'Empty filename'}), 400

        # Get operations
        operations_str = request.form.get('operations', '{}')
        operations = json.loads(operations_str)

        # Save files
        excel_path = save_temp_file(excel_file, session_id)

        # Create output path
        output_filename = f"Nokia_Config_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xml"
        output_path = os.path.join(tempfile.gettempdir(), f"{session_id}_{output_filename}")
        TEMP_FILES[session_id].append(output_path)

        # Convert
        converter = ExcelToXMLConverter(excel_path, output_path)
        converter.set_operations(operations)
        success, message = converter.convert()

        if not success:
            cleanup_temp_files(session_id)
            return jsonify({'error': message}), 500

        # Log activity
        log_activity(user['id'], 'excel_to_xml', details=f'File: {excel_file.filename}')

        # Send file
        response = send_file(
            output_path,
            as_attachment=True,
            download_name=output_filename,
            mimetype='application/xml'
        )

        @response.call_on_close
        def cleanup():
            cleanup_temp_files(session_id)

        return response

    except Exception as e:
        cleanup_temp_files(session_id)
        error_msg = f"Error: {str(e)}\n{traceback.format_exc()}"
        print(error_msg)
        return jsonify({'error': str(e)}), 500

# ============================================================================
# XML COMPARISON
# ============================================================================

@app.route('/api/compare-xml', methods=['POST'])
@login_required
def compare_xml():
    """Compare two XML files"""
    session_id = str(uuid.uuid4())
    user = request.current_user

    try:
        if 'xml1_file' not in request.files or 'xml2_file' not in request.files:
            return jsonify({'error': 'Both XML files required'}), 400

        xml1_file = request.files['xml1_file']
        xml2_file = request.files['xml2_file']

        if xml1_file.filename == '' or xml2_file.filename == '':
            return jsonify({'error': 'Empty filename'}), 400

        # Save files
        xml1_path = save_temp_file(xml1_file, session_id)
        xml2_path = save_temp_file(xml2_file, session_id)

        # Create output path
        output_filename = f"XML_Comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        output_path = os.path.join(tempfile.gettempdir(), f"{session_id}_{output_filename}")
        TEMP_FILES[session_id].append(output_path)

        # Compare
        comparator = XMLComparator(xml1_path, xml2_path, output_path)
        success, diff_count = comparator.compare()

        if not success:
            cleanup_temp_files(session_id)
            return jsonify({'error': 'Comparison failed'}), 500

        # Log activity
        log_activity(user['id'], 'compare_xml', details=f'Files: {xml1_file.filename} vs {xml2_file.filename}')

        # Send file
        response = send_file(
            output_path,
            as_attachment=True,
            download_name=output_filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )

        @response.call_on_close
        def cleanup():
            cleanup_temp_files(session_id)

        return response

    except Exception as e:
        cleanup_temp_files(session_id)
        error_msg = f"Error: {str(e)}\n{traceback.format_exc()}"
        print(error_msg)
        return jsonify({'error': str(e)}), 500

# ============================================================================
# TASK MANAGEMENT API
# ============================================================================

@app.route('/api/tasks', methods=['GET'])
@login_required
def list_tasks():
    """Get tasks (filtered by query params)"""
    user = request.current_user
    
    status = request.args.get('status')
    assigned_to_me = request.args.get('assigned_to_me') == 'true'
    created_by_me = request.args.get('created_by_me') == 'true'
    
    try:
        if assigned_to_me:
            tasks = get_tasks(assigned_to=user['id'], status=status)
        elif created_by_me:
            tasks = get_tasks(created_by=user['id'], status=status)
        else:
            tasks = get_tasks(user_id=user['id'], status=status)
        
        return jsonify({
            'success': True,
            'tasks': tasks,
            'count': len(tasks)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tasks', methods=['POST'])
@login_required
def create_new_task():
    """Create new task"""
    user = request.current_user
    data = request.get_json()
    
    title = data.get('title')
    description = data.get('description', '')
    task_type = data.get('task_type', 'xml_to_excel')
    assigned_to = data.get('assigned_to')
    priority = data.get('priority', 'medium')
    
    if not title:
        return jsonify({'error': 'Task title required'}), 400
    
    try:
        success, task_id = create_task(
            title=title,
            description=description,
            task_type=task_type,
            created_by=user['id'],
            assigned_to=assigned_to,
            priority=priority
        )
        
        if success:
            log_activity(user['id'], 'create_task', details=f'Task: {title}')
            return jsonify({
                'success': True,
                'task_id': task_id,
                'message': 'Task created'
            })
        else:
            return jsonify({'error': task_id}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tasks/<int:task_id>', methods=['GET'])
@login_required
def get_task(task_id):
    """Get single task with updates"""
    try:
        task = get_task_by_id(task_id)
        
        if not task:
            return jsonify({'error': 'Task not found'}), 404
        
        updates = get_task_updates(task_id)
        
        return jsonify({
            'success': True,
            'task': task,
            'updates': updates
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tasks/<int:task_id>/status', methods=['PUT'])
@login_required
def update_task(task_id):
    """Update task status"""
    user = request.current_user
    data = request.get_json()
    
    new_status = data.get('status')
    notes = data.get('notes')
    error_details = data.get('error_details')
    
    if not new_status:
        return jsonify({'error': 'Status required'}), 400
    
    try:
        success, message = update_task_status(
            task_id, user['id'], new_status, notes, error_details
        )
        
        if success:
            log_activity(user['id'], 'update_task', details=f'Task {task_id}: {new_status}')
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'error': message}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tasks/<int:task_id>/comment', methods=['POST'])
@login_required
def add_comment(task_id):
    """Add comment to task"""
    user = request.current_user
    data = request.get_json()
    
    comment = data.get('comment')
    
    if not comment:
        return jsonify({'error': 'Comment required'}), 400
    
    try:
        success, message = add_task_comment(task_id, user['id'], comment)
        
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'error': message}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tasks/<int:task_id>/assign', methods=['PUT'])
@login_required
def reassign_task(task_id):
    """Assign or reassign task"""
    user = request.current_user
    data = request.get_json()
    
    assigned_to = data.get('assigned_to')
    comment = data.get('comment')
    
    if assigned_to is None:
        return jsonify({'error': 'Assignee required'}), 400
    
    try:
        success, message = assign_task(task_id, user['id'], assigned_to, comment)
        
        if success:
            log_activity(user['id'], 'assign_task', details=f'Task {task_id} to user {assigned_to}')
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'error': message}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/users', methods=['GET'])
@login_required
def list_users():
    """Get all users (for task assignment)"""
    try:
        users = get_all_users()
        
        # Return only active users with essential info
        user_list = [
            {
                'id': u['id'],
                'username': u['username'],
                'full_name': u['full_name'],
                'department': u['department']
            }
            for u in users if u['is_active']
        ]
        
        return jsonify({
            'success': True,
            'users': user_list
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================================
# MO DESCRIPTIONS API
# ============================================================================

@app.route('/api/mo/search', methods=['GET'])
@login_required
def search_mo_params():
    """Search for MO classes and parameters"""
    query = request.args.get('q', '').strip().lower()
    search_type = request.args.get('type', 'all')  # 'mo', 'param', or 'all'
    limit = int(request.args.get('limit', 50))

    if not query or len(query) < 2:
        return jsonify({'error': 'Search query must be at least 2 characters'}), 400

    results = {
        'mos': [],
        'params': []
    }

    # Search MO classes
    if search_type in ['all', 'mo']:
        mo_to_params = EMBEDDED_CATEGORIZATION.get('mo_to_params', {})
        for mo_name in mo_to_params.keys():
            if query in mo_name.lower():
                description = get_mo_description(mo_name)
                category = get_mo_category(mo_name)
                results['mos'].append({
                    'name': mo_name,
                    'description': description,
                    'category': category,
                    'param_count': len(mo_to_params.get(mo_name, []))
                })
                if len(results['mos']) >= limit:
                    break

    # Search parameters
    if search_type in ['all', 'param']:
        param_to_mos = EMBEDDED_CATEGORIZATION.get('param_to_mos', {})
        for param_name in param_to_mos.keys():
            if query in param_name.lower():
                description = get_param_description(param_name)
                mo_list = param_to_mos.get(param_name, [])
                results['params'].append({
                    'name': param_name,
                    'description': description,
                    'mo_count': len(mo_list),
                    'mos': mo_list[:10]  # First 10 MOs only
                })
                if len(results['params']) >= limit:
                    break

    return jsonify({
        'success': True,
        'query': query,
        'results': results,
        'total_mos': len(results['mos']),
        'total_params': len(results['params'])
    })

@app.route('/api/mo/<mo_name>', methods=['GET'])
@login_required
def get_mo_info(mo_name):
    """Get detailed information about an MO class"""
    mo_to_params = EMBEDDED_CATEGORIZATION.get('mo_to_params', {})

    if mo_name not in mo_to_params:
        return jsonify({'error': f'MO class {mo_name} not found'}), 404

    params = mo_to_params.get(mo_name, [])
    param_details = []

    for param in params:
        desc = get_param_description(param)
        param_details.append({
            'name': param,
            'description': desc
        })

    return jsonify({
        'success': True,
        'mo': {
            'name': mo_name,
            'description': get_mo_description(mo_name),
            'category': get_mo_category(mo_name),
            'param_count': len(params),
            'parameters': param_details
        }
    })

@app.route('/api/param/<param_name>', methods=['GET'])
@login_required
def get_param_info(param_name):
    """Get detailed information about a parameter"""
    param_to_mos = EMBEDDED_CATEGORIZATION.get('param_to_mos', {})

    if param_name not in param_to_mos:
        return jsonify({'error': f'Parameter {param_name} not found'}), 404

    mos = param_to_mos.get(param_name, [])

    return jsonify({
        'success': True,
        'param': {
            'name': param_name,
            'description': get_param_description(param_name),
            'mo_count': len(mos),
            'mos': mos
        }
    })

@app.route('/api/mo/list', methods=['GET'])
@login_required
def list_all_mos():
    """Get list of all MO classes"""
    mo_to_params = EMBEDDED_CATEGORIZATION.get('mo_to_params', {})

    mos = []
    for mo_name in sorted(mo_to_params.keys()):
        mos.append({
            'name': mo_name,
            'description': get_mo_description(mo_name),
            'category': get_mo_category(mo_name),
            'param_count': len(mo_to_params.get(mo_name, []))
        })

    return jsonify({
        'success': True,
        'total': len(mos),
        'mos': mos
    })

@app.route('/api/mo/stats', methods=['GET'])
@login_required
def get_mo_stats():
    """Get statistics about available MO descriptions"""
    mo_to_params = EMBEDDED_CATEGORIZATION.get('mo_to_params', {})
    param_to_mos = EMBEDDED_CATEGORIZATION.get('param_to_mos', {})

    # Count by category
    categories = {}
    for mo_name in mo_to_params.keys():
        cat = get_mo_category(mo_name)
        categories[cat] = categories.get(cat, 0) + 1

    return jsonify({
        'success': True,
        'available': MO_DESCRIPTIONS_AVAILABLE,
        'stats': {
            'total_mos': len(mo_to_params),
            'total_params': len(param_to_mos),
            'categories': categories
        }
    })

# ============================================================================
# ADMIN API ROUTES
# ============================================================================

def admin_required(f):
    """Decorator to require admin role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        session_token = request.cookies.get('session_token')

        if not session_token:
            return jsonify({'error': 'Not authenticated'}), 401

        user = get_user_by_session(session_token)
        if not user:
            return jsonify({'error': 'Not authenticated'}), 401

        if user.get('role') != 'admin':
            return jsonify({'error': 'Admin access required'}), 403

        request.current_user = user
        return f(*args, **kwargs)

    return decorated_function

@app.route('/api/admin/users', methods=['GET'])
@admin_required
def admin_list_users():
    """Get all users (admin only)"""
    try:
        users = get_all_users()
        return jsonify({
            'success': True,
            'users': users
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/users/<int:user_id>/role', methods=['PUT'])
@admin_required
def admin_update_user_role(user_id):
    """Update user role (admin only)"""
    from database_enhanced import update_user_role

    data = request.get_json()
    new_role = data.get('role')

    if not new_role:
        return jsonify({'error': 'Role required'}), 400

    if new_role not in ['user', 'config_team', 'admin']:
        return jsonify({'error': 'Invalid role'}), 400

    try:
        success = update_user_role(user_id, new_role)
        if success:
            log_activity(request.current_user['id'], 'update_role',
                        details=f'User {user_id} role changed to {new_role}')
            return jsonify({'success': True, 'message': 'Role updated'})
        else:
            return jsonify({'error': 'User not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/users/<int:user_id>/status', methods=['PUT'])
@admin_required
def admin_update_user_status(user_id):
    """Activate/deactivate user (admin only)"""
    from database_enhanced import update_user_status

    data = request.get_json()
    is_active = data.get('is_active')

    if is_active is None:
        return jsonify({'error': 'Status required'}), 400

    try:
        success = update_user_status(user_id, is_active)
        if success:
            action = 'activated' if is_active else 'deactivated'
            log_activity(request.current_user['id'], 'update_status',
                        details=f'User {user_id} {action}')
            return jsonify({'success': True, 'message': f'User {action}'})
        else:
            return jsonify({'error': 'User not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================================
# NETWORK MAP API ROUTES
# ============================================================================

@app.route('/api/map/sites', methods=['GET'])
def get_all_sites():
    """Get all network sites with their basic information"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        import sqlite3
        conn = sqlite3.connect('ncm_users.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT site_id, site_name, latitude, longitude, region, site_type, status
            FROM sites
            WHERE status = 'Active'
            ORDER BY site_name
        ''')

        sites = [dict(row) for row in cursor.fetchall()]
        conn.close()

        log_activity(user[0], 'map_view', 'Viewed network map sites')
        return jsonify({'success': True, 'sites': sites})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/map/site/<site_id>', methods=['GET'])
def get_site_details(site_id):
    """Get detailed information about a specific site including sectors"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        import sqlite3
        conn = sqlite3.connect('ncm_users.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get site info
        cursor.execute('''
            SELECT site_id, site_name, latitude, longitude, region, site_type, status
            FROM sites
            WHERE site_id = ?
        ''', (site_id,))

        site = cursor.fetchone()
        if not site:
            conn.close()
            return jsonify({'error': 'Site not found'}), 404

        site_data = dict(site)

        # Get sectors for this site
        cursor.execute('''
            SELECT sector_id, sector_name, azimuth, beamwidth, technology, frequency_band, status
            FROM sectors
            WHERE site_id = ? AND status = 'Active'
            ORDER BY sector_name
        ''', (site_id,))

        sectors = [dict(row) for row in cursor.fetchall()]
        site_data['sectors'] = sectors

        conn.close()

        log_activity(user[0], 'site_view', f'Viewed site {site_id}')
        return jsonify({'success': True, 'site': site_data})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/map/sector/<sector_id>/kpis', methods=['GET'])
def get_sector_kpis(sector_id):
    """Get KPI data for all cells in a sector"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        import sqlite3
        conn = sqlite3.connect('ncm_users.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get sector info
        cursor.execute('''
            SELECT s.sector_id, s.sector_name, s.site_id, s.azimuth, s.beamwidth,
                   s.technology, s.frequency_band, st.site_name
            FROM sectors s
            JOIN sites st ON s.site_id = st.site_id
            WHERE s.sector_id = ?
        ''', (sector_id,))

        sector = cursor.fetchone()
        if not sector:
            conn.close()
            return jsonify({'error': 'Sector not found'}), 404

        sector_data = dict(sector)

        # Get cells for this sector
        cursor.execute('''
            SELECT cell_id, cell_name, pci, tac, status
            FROM cells
            WHERE sector_id = ?
            ORDER BY cell_name
        ''', (sector_id,))

        cells = [dict(row) for row in cursor.fetchall()]

        # Get latest KPIs for each cell
        for cell in cells:
            cursor.execute('''
                SELECT avg_users, data_volume_gb, rsrp, rsrq, sinr, cqi,
                       throughput_dl_mbps, throughput_ul_mbps, rrc_success_rate,
                       erab_success_rate, call_drop_rate, handover_success_rate,
                       availability_percent, timestamp
                FROM cell_kpis
                WHERE cell_id = ?
                ORDER BY timestamp DESC
                LIMIT 1
            ''', (cell['cell_id'],))

            kpi = cursor.fetchone()
            cell['kpis'] = dict(kpi) if kpi else None

        sector_data['cells'] = cells
        conn.close()

        log_activity(user[0], 'sector_kpi_view', f'Viewed KPIs for sector {sector_id}')
        return jsonify({'success': True, 'sector': sector_data})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/map/site', methods=['POST'])
def add_site():
    """Add a new site (for OSS data ingestion)"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    # Only admins can add sites
    if user[6] != 'admin':
        return jsonify({'error': 'Admin access required'}), 403

    try:
        data = request.get_json()
        required = ['site_id', 'site_name', 'latitude', 'longitude']

        if not all(field in data for field in required):
            return jsonify({'error': 'Missing required fields'}), 400

        import sqlite3
        conn = sqlite3.connect('ncm_users.db')
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO sites (site_id, site_name, latitude, longitude, region, site_type, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['site_id'],
            data['site_name'],
            data['latitude'],
            data['longitude'],
            data.get('region', ''),
            data.get('site_type', ''),
            data.get('status', 'Active')
        ))

        conn.commit()
        conn.close()

        log_activity(user[0], 'site_add', f'Added site {data["site_id"]}')
        return jsonify({'success': True, 'message': 'Site added successfully'})

    except sqlite3.IntegrityError:
        return jsonify({'error': 'Site ID already exists'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/map/sector', methods=['POST'])
def add_sector():
    """Add a new sector (for OSS data ingestion)"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    if user[6] != 'admin':
        return jsonify({'error': 'Admin access required'}), 403

    try:
        data = request.get_json()
        required = ['sector_id', 'site_id', 'sector_name']

        if not all(field in data for field in required):
            return jsonify({'error': 'Missing required fields'}), 400

        import sqlite3
        conn = sqlite3.connect('ncm_users.db')
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO sectors (sector_id, site_id, sector_name, azimuth, beamwidth,
                               technology, frequency_band, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['sector_id'],
            data['site_id'],
            data['sector_name'],
            data.get('azimuth', 0),
            data.get('beamwidth', 65),
            data.get('technology', ''),
            data.get('frequency_band', ''),
            data.get('status', 'Active')
        ))

        conn.commit()
        conn.close()

        log_activity(user[0], 'sector_add', f'Added sector {data["sector_id"]}')
        return jsonify({'success': True, 'message': 'Sector added successfully'})

    except sqlite3.IntegrityError:
        return jsonify({'error': 'Sector ID already exists'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/map/stats', methods=['GET'])
def get_network_stats():
    """Get overall network statistics for the dashboard"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        import sqlite3
        conn = sqlite3.connect('ncm_users.db')
        cursor = conn.cursor()

        # Count active sites
        cursor.execute('SELECT COUNT(*) FROM sites WHERE status = "Active"')
        total_sites = cursor.fetchone()[0]

        # Count active sectors
        cursor.execute('SELECT COUNT(*) FROM sectors WHERE status = "Active"')
        total_sectors = cursor.fetchone()[0]

        # Count active cells
        cursor.execute('SELECT COUNT(*) FROM cells WHERE status = "Active"')
        total_cells = cursor.fetchone()[0]

        # Calculate average availability from latest KPIs
        cursor.execute('''
            SELECT AVG(k.availability_percent)
            FROM (
                SELECT cell_id, MAX(timestamp) as latest
                FROM cell_kpis
                GROUP BY cell_id
            ) latest_kpis
            JOIN cell_kpis k ON k.cell_id = latest_kpis.cell_id
                            AND k.timestamp = latest_kpis.latest
        ''')

        avg_availability = cursor.fetchone()[0] or 100.0

        conn.close()

        stats = {
            'total_sites': total_sites,
            'total_sectors': total_sectors,
            'total_cells': total_cells,
            'avg_availability': round(avg_availability, 2)
        }

        return jsonify({'success': True, 'stats': stats})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({'error': 'File too large. Maximum size is 100MB'}), 413

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

# ============================================================================
# DATABASE INITIALIZATION
# ============================================================================

# Initialize database when app starts
from database_enhanced import init_db, create_admin_user

try:
    init_db()
    create_admin_user()
except Exception as e:
    print(f"Database initialization warning: {e}")

# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
    