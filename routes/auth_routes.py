"""
Authentication Routes
Handles login, logout, registration, and dashboard access
"""

from flask import Blueprint, request, jsonify, render_template, redirect, url_for, make_response
from database_enhanced import (
    create_user, authenticate_user, create_session,
    get_user_by_session, delete_session, log_activity
)

auth_bp = Blueprint('auth', __name__)

def get_current_user():
    """Get current logged-in user"""
    session_token = request.cookies.get('session_token')
    if session_token:
        return get_user_by_session(session_token)
    return None

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

    return render_template('dashboard.html', user=format_user_data(user))

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
                log_activity((user.get('id') if isinstance(user, dict) else user[0]), 'logout', f'User {(user.get('username') if isinstance(user, dict) else user[1])} logged out')
            delete_session(session_token)

        response = make_response(jsonify({'success': True}))
        response.set_cookie('session_token', '', expires=0)
        return response

    except Exception as e:
        return jsonify({'error': str(e)}), 500
