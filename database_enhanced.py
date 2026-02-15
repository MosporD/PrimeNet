"""
Database Models and Authentication - COMPLETE VERSION
SQLite database for user management with all features
"""

import sqlite3
import hashlib
import secrets
from datetime import datetime
import os
import json

DATABASE = 'ncm_users.db'

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database with all tables"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT,
            department TEXT,
            role TEXT DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP,
            is_active BOOLEAN DEFAULT 1
        )
    ''')
    
    # Sessions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            session_token TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Activity log table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            ip_address TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Tasks table (with XML file support)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            task_type TEXT NOT NULL,
            priority TEXT DEFAULT 'medium',
            status TEXT DEFAULT 'pending',
            created_by INTEGER NOT NULL,
            assigned_to INTEGER,
            xml_file_path TEXT,
            xml_file_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users (id),
            FOREIGN KEY (assigned_to) REFERENCES users (id)
        )
    ''')
    
    # Task updates table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS task_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            update_type TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES tasks (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Filter profiles table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS filter_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            profile_name TEXT NOT NULL,
            description TEXT,
            filter_data TEXT NOT NULL,
            is_shared BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            UNIQUE(user_id, profile_name)
        )
    ''')
    
    conn.commit()
    conn.close()

# ============================================================================
# PASSWORD FUNCTIONS
# ============================================================================

def hash_password(password):
    """Hash password with SHA-256"""
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.sha256((password + salt).encode()).hexdigest()
    return f"{salt}${pwd_hash}"

def verify_password(password, password_hash):
    """Verify password against hash"""
    try:
        salt, pwd_hash = password_hash.split('$')
        test_hash = hashlib.sha256((password + salt).encode()).hexdigest()
        return test_hash == pwd_hash
    except:
        return False

# ============================================================================
# USER FUNCTIONS
# ============================================================================

def create_user(username, email, password, full_name=None, department=None, role='user'):
    """Create new user"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        password_hash = hash_password(password)
        
        cursor.execute('''
            INSERT INTO users (username, email, password_hash, full_name, department, role)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (username, email, password_hash, full_name, department, role))
        
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
        
        return True, user_id
    except sqlite3.IntegrityError as e:
        if 'username' in str(e):
            return False, "Username already exists"
        elif 'email' in str(e):
            return False, "Email already exists"
        return False, "User creation failed"
    except Exception as e:
        return False, str(e)

def authenticate_user(username, password):
    """Authenticate user and return user data"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM users WHERE username = ? AND is_active = 1', (username,))
    user = cursor.fetchone()
    
    if user and verify_password(password, user['password_hash']):
        cursor.execute('UPDATE users SET last_login = ? WHERE id = ?', 
                      (datetime.now(), user['id']))
        conn.commit()
        conn.close()
        
        return True, dict(user)
    
    conn.close()
    return False, None

def get_all_users():
    """Get all users (for admin)"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, username, email, full_name, department, role, 
               created_at, last_login, is_active 
        FROM users 
        ORDER BY created_at DESC
    ''')
    users = cursor.fetchall()
    conn.close()
    return [dict(user) for user in users]

def update_user_role(user_id, new_role):
    """Update user's role"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('UPDATE users SET role = ? WHERE id = ?', (new_role, user_id))
    affected = cursor.rowcount
    
    conn.commit()
    conn.close()
    
    return affected > 0

def update_user_status(user_id, is_active):
    """Activate or deactivate user"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('UPDATE users SET is_active = ? WHERE id = ?', (is_active, user_id))
    affected = cursor.rowcount
    
    conn.commit()
    conn.close()
    
    return affected > 0

# ============================================================================
# SESSION FUNCTIONS
# ============================================================================

def create_session(user_id):
    """Create session token for user"""
    conn = get_db()
    cursor = conn.cursor()
    
    session_token = secrets.token_urlsafe(32)
    expires_at = datetime.now().timestamp() + (24 * 60 * 60)  # 24 hours
    
    cursor.execute('''
        INSERT INTO sessions (user_id, session_token, expires_at)
        VALUES (?, ?, ?)
    ''', (user_id, session_token, expires_at))
    
    conn.commit()
    conn.close()
    
    return session_token

def get_user_by_session(session_token):
    """Get user data by session token"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT u.* FROM users u
        JOIN sessions s ON u.id = s.user_id
        WHERE s.session_token = ? AND s.expires_at > ? AND u.is_active = 1
    ''', (session_token, datetime.now().timestamp()))
    
    user = cursor.fetchone()
    conn.close()
    
    return dict(user) if user else None

def delete_session(session_token):
    """Delete session (logout)"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM sessions WHERE session_token = ?', (session_token,))
    conn.commit()
    conn.close()

# ============================================================================
# ACTIVITY LOG
# ============================================================================

def log_activity(user_id, action, details=None, ip_address=None):
    """Log user activity"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO activity_log (user_id, action, details, ip_address)
        VALUES (?, ?, ?, ?)
    ''', (user_id, action, details, ip_address))
    
    conn.commit()
    conn.close()

# ============================================================================
# TASK FUNCTIONS
# ============================================================================

def create_task_db(title, description, task_type, priority, created_by, 
                   assigned_to=None, xml_file_path=None, xml_file_name=None):
    """Create a new task with optional XML file attachment"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO tasks (
            title, description, task_type, priority, status,
            created_by, assigned_to, xml_file_path, xml_file_name
        ) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)
    ''', (
        title, description, task_type, priority,
        created_by, assigned_to, xml_file_path, xml_file_name
    ))
    
    task_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return task_id

def get_tasks(user_id=None, assigned_to=None, created_by=None, status=None):
    """Get tasks based on filters"""
    conn = get_db()
    cursor = conn.cursor()

    query = '''
        SELECT
            t.*,
            creator.username as creator_name,
            creator.full_name as creator_full_name,
            assignee.username as assignee_name,
            assignee.full_name as assignee_full_name
        FROM tasks t
        LEFT JOIN users creator ON t.created_by = creator.id
        LEFT JOIN users assignee ON t.assigned_to = assignee.id
        WHERE 1=1
    '''
    params = []

    if assigned_to is not None:
        query += ' AND t.assigned_to = ?'
        params.append(assigned_to)

    if created_by is not None:
        query += ' AND t.created_by = ?'
        params.append(created_by)

    if user_id is not None and assigned_to is None and created_by is None:
        # Show tasks where user is either creator or assignee
        query += ' AND (t.assigned_to = ? OR t.created_by = ?)'
        params.append(user_id)
        params.append(user_id)

    if status:
        statuses = status.split(',')
        placeholders = ','.join(['?' for _ in statuses])
        query += f' AND t.status IN ({placeholders})'
        params.extend(statuses)

    query += ' ORDER BY t.created_at DESC'

    cursor.execute(query, params)
    tasks = cursor.fetchall()
    conn.close()

    return [dict(task) for task in tasks]

def get_task_by_id(task_id):
    """Get task details including XML file info"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            t.*,
            creator.username as creator_name,
            creator.full_name as creator_full_name,
            assignee.username as assignee_name,
            assignee.full_name as assignee_full_name
        FROM tasks t
        LEFT JOIN users creator ON t.created_by = creator.id
        LEFT JOIN users assignee ON t.assigned_to = assignee.id
        WHERE t.id = ?
    ''', (task_id,))
    
    task = cursor.fetchone()
    conn.close()
    
    return dict(task) if task else None

def update_task_status(task_id, user_id, new_status, comment=None, error_details=None):
    """Update task status and log the change"""
    conn = get_db()
    cursor = conn.cursor()

    # Get old status
    cursor.execute('SELECT status FROM tasks WHERE id = ?', (task_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False, "Task not found"

    old_status = row['status']

    # Update task
    cursor.execute('''
        UPDATE tasks
        SET status = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    ''', (new_status, task_id))

    # Log the update
    cursor.execute('''
        INSERT INTO task_updates (task_id, user_id, update_type, old_value, new_value, comment)
        VALUES (?, ?, 'status_change', ?, ?, ?)
    ''', (task_id, user_id, old_status, new_status, comment))

    conn.commit()
    conn.close()

    return True, "Status updated successfully"

def get_task_updates(task_id):
    """Get all updates for a task"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT
            tu.*,
            u.username,
            u.full_name
        FROM task_updates tu
        LEFT JOIN users u ON tu.user_id = u.id
        WHERE tu.task_id = ?
        ORDER BY tu.created_at DESC
    ''', (task_id,))

    updates = cursor.fetchall()
    conn.close()

    return [dict(update) for update in updates]

# Alias for compatibility with app_enhanced.py
def create_task(title, description, task_type, created_by, assigned_to=None, priority='medium',
                xml_file_path=None, xml_file_name=None):
    """Create a new task (wrapper for create_task_db)"""
    try:
        task_id = create_task_db(title, description, task_type, priority, created_by,
                                  assigned_to, xml_file_path, xml_file_name)
        return True, task_id
    except Exception as e:
        return False, str(e)

def assign_task(task_id, user_id, assigned_to, comment=None):
    """Assign or reassign a task to a user"""
    conn = get_db()
    cursor = conn.cursor()

    try:
        # Get current assignee
        cursor.execute('SELECT assigned_to FROM tasks WHERE id = ?', (task_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return False, "Task not found"

        old_assignee = row['assigned_to']

        # Update task assignment
        cursor.execute('''
            UPDATE tasks
            SET assigned_to = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (assigned_to if assigned_to else None, task_id))

        # Log the assignment change
        cursor.execute('''
            INSERT INTO task_updates (task_id, user_id, update_type, old_value, new_value, comment)
            VALUES (?, ?, 'assignment', ?, ?, ?)
        ''', (task_id, user_id, str(old_assignee) if old_assignee else 'Unassigned',
              str(assigned_to) if assigned_to else 'Unassigned', comment))

        conn.commit()
        conn.close()

        return True, "Task assigned successfully"
    except Exception as e:
        conn.close()
        return False, str(e)

def add_task_comment(task_id, user_id, comment):
    """Add a comment to a task"""
    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            INSERT INTO task_updates (task_id, user_id, update_type, comment)
            VALUES (?, ?, 'comment', ?)
        ''', (task_id, user_id, comment))

        conn.commit()
        conn.close()

        return True, "Comment added successfully"
    except Exception as e:
        conn.close()
        return False, str(e)

# ============================================================================
# PROFILE FUNCTIONS
# ============================================================================

def save_profile(user_id, profile_name, description, filter_data, is_shared=False):
    """Save a filter profile"""
    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            INSERT INTO filter_profiles (user_id, profile_name, description, filter_data, is_shared)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, profile_name, description, json.dumps(filter_data), is_shared))

        profile_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return True, profile_id
    except sqlite3.IntegrityError:
        conn.close()
        return False, "Profile name already exists"
    except Exception as e:
        conn.close()
        return False, str(e)

# Alias for compatibility with app_enhanced.py
def save_filter_profile(user_id, profile_name, filter_data, description='', is_shared=False):
    """Save a filter profile (alias for save_profile)"""
    return save_profile(user_id, profile_name, description, filter_data, is_shared)

def get_filter_profiles(user_id):
    """Get user's filter profiles (alias for get_profiles)"""
    return get_profiles(user_id)

def delete_filter_profile(profile_id, user_id):
    """Delete a filter profile"""
    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            DELETE FROM filter_profiles
            WHERE id = ? AND user_id = ?
        ''', (profile_id, user_id))

        affected = cursor.rowcount
        conn.commit()
        conn.close()

        return affected > 0
    except Exception as e:
        conn.close()
        return False

def get_profiles(user_id):
    """Get user's profiles (own + shared)"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM filter_profiles
        WHERE user_id = ? OR is_shared = 1
        ORDER BY created_at DESC
    ''', (user_id,))
    
    profiles = cursor.fetchall()
    conn.close()
    
    return [dict(profile) for profile in profiles]

def get_profile_by_id(profile_id, user_id):
    """Get specific profile (check ownership)"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM filter_profiles
        WHERE id = ? AND (user_id = ? OR is_shared = 1)
    ''', (profile_id, user_id))
    
    profile = cursor.fetchone()
    conn.close()
    
    return dict(profile) if profile else None

# ============================================================================
# PERMISSION CHECKING
# ============================================================================

def check_task_permission(user, task, action='view'):
    """
    Check if user has permission to perform action on task
    
    Permissions:
    - admin: Can do anything
    - config_team: Can create, edit, delete, assign any task
    - user: Can only view/update tasks assigned to them
    """
    role = user.get('role', 'user')
    
    if role == 'admin':
        return True
    
    if role == 'config_team':
        return True
    
    # Regular users
    if action == 'view':
        return (task['assigned_to'] == user['id'] or 
                task['created_by'] == user['id'])
    
    if action == 'update':
        return task['assigned_to'] == user['id']
    
    if action in ['create', 'delete', 'assign']:
        return False
    
    return False

# ============================================================================
# INITIALIZATION
# ============================================================================

def create_admin_user():
    """Create default admin user if no users exist"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) as count FROM users')
    count = cursor.fetchone()['count']
    conn.close()
    
    if count == 0:
        success, user_id = create_user(
            username='admin',
            email='admin@company.com',
            password='admin123',
            full_name='System Administrator',
            department='IT',
            role='admin'
        )
        return success
    return False

# Initialize database on import
try:
    if not os.path.exists(DATABASE):
        print(f"Creating database at: {os.path.abspath(DATABASE)}")
        init_db()
        create_admin_user()
        print("✓ Database initialized successfully")
except Exception as e:
    print(f"⚠️  Warning: Could not auto-initialize database: {e}")