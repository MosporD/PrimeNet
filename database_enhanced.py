"""
Database Models and Authentication - COMPLETE VERSION
SQLite database for user management with all features
"""

import sqlite3
import hashlib
import secrets
from datetime import datetime, timedelta
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sync_config import NCMUSERS_DB as DATABASE
from db.runtime import adapt_placeholders, connect_app, is_postgresql


def _unique_constraint_error(exc):
    if isinstance(exc, sqlite3.IntegrityError):
        return True
    try:
        import psycopg2.errors

        return isinstance(exc, psycopg2.errors.UniqueViolation)
    except Exception:
        return False


def _exec(cur, sql: str, params=()):
    return cur.execute(adapt_placeholders(sql), tuple(params) if params is not None else ())


def _insert_return_id(conn, sql: str, params):
    sql = adapt_placeholders(sql)
    params = tuple(params)
    if is_postgresql():
        s = sql.rstrip().rstrip(';')
        if 'RETURNING' not in s.upper():
            s = f'{s} RETURNING id'
        cur = conn.cursor()
        cur.execute(s, params)
        row = cur.fetchone()
        return row['id'] if row else None
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur.lastrowid


def get_db():
    """SQLite ``ncm_users.db`` or PostgreSQL ``app`` schema (via ``DATABASE_URL``)."""
    return connect_app()


def init_db():
    """Initialize database with all tables"""
    if is_postgresql():
        # App + metadata + PM schemas are created by ``sync.db_migration.run_migrations``.
        return

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
            password_changed_at TIMESTAMP,
            force_password_change BOOLEAN DEFAULT 1,
            last_login TIMESTAMP,
            is_active BOOLEAN DEFAULT 1
        )
    ''')
    # Backward-compatible upgrades for existing SQLite user tables.
    try:
        cursor.execute('ALTER TABLE users ADD COLUMN password_changed_at TIMESTAMP')
    except Exception:
        pass
    try:
        cursor.execute('ALTER TABLE users ADD COLUMN force_password_change BOOLEAN DEFAULT 1')
    except Exception:
        pass
    
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

    # ── New feature tables ────────────────────────────────────────────────────

    # Config version history
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS config_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ne_name TEXT NOT NULL,
            file_name TEXT NOT NULL,
            version_num INTEGER NOT NULL,
            xml_content TEXT NOT NULL,
            comment TEXT,
            uploaded_by INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (uploaded_by) REFERENCES users (id)
        )
    ''')

    # Report archive (generated report files)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS report_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_name TEXT NOT NULL,
            report_type TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_size INTEGER DEFAULT 0,
            generated_by INTEGER NOT NULL,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (generated_by) REFERENCES users (id)
        )
    ''')

    # User preferences (dashboard personalisation)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_preferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            preferences TEXT NOT NULL DEFAULT '{}',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')

    # Configuration task scheduler tables
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS config_scheduler_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_name TEXT NOT NULL,
            vendor TEXT NOT NULL DEFAULT 'mixed',
            schedule_mode TEXT NOT NULL DEFAULT 'run_now',
            scheduled_at TIMESTAMP,
            run_mode TEXT NOT NULL DEFAULT 'serial',
            execution_order TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            completion_notes TEXT,
            created_by INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS config_scheduler_task_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            original_file_name TEXT NOT NULL,
            stored_file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_order INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES config_scheduler_tasks(id) ON DELETE CASCADE
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS config_scheduler_result_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            original_file_name TEXT NOT NULL,
            stored_file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            uploaded_by INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES config_scheduler_tasks(id) ON DELETE CASCADE,
            FOREIGN KEY (uploaded_by) REFERENCES users(id)
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
    except (ValueError, AttributeError):
        return False

# ============================================================================
# USER FUNCTIONS
# ============================================================================

def create_user(username, email, password, full_name=None, department=None, role='user'):
    """Create new user"""
    try:
        conn = get_db()
        password_hash = hash_password(password)
        user_id = _insert_return_id(
            conn,
            '''
            INSERT INTO users (
                username, email, password_hash, full_name, department, role, password_changed_at, force_password_change
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (username, email, password_hash, full_name, department, role, datetime.now(), 1),
        )
        conn.commit()
        conn.close()
        return True, user_id
    except Exception as e:
        if _unique_constraint_error(e):
            msg = str(e).lower()
            if 'username' in msg or 'users_username_key' in msg:
                return False, 'Username already exists'
            if 'email' in msg or 'users_email_key' in msg:
                return False, 'Email already exists'
            return False, 'User creation failed'
        return False, str(e)

def authenticate_user(username, password):
    """Authenticate user and return user data"""
    conn = get_db()
    cursor = conn.cursor()
    _exec(
        cursor,
        'SELECT * FROM users WHERE username = ? AND is_active',
        (username,),
    )
    user = cursor.fetchone()

    if user and verify_password(password, user['password_hash']):
        must_change = is_password_change_required(dict(user))
        _exec(
            cursor,
            'UPDATE users SET last_login = ? WHERE id = ?',
            (datetime.now(), user['id']),
        )
        conn.commit()
        conn.close()
        out = dict(user)
        out['must_change_password'] = must_change
        return True, out

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
    
    _exec(cursor, 'UPDATE users SET role = ? WHERE id = ?', (new_role, user_id))
    affected = cursor.rowcount
    
    conn.commit()
    conn.close()
    
    return affected > 0

def update_user_status(user_id, is_active):
    """Activate or deactivate user"""
    conn = get_db()
    cursor = conn.cursor()
    
    _exec(cursor, 'UPDATE users SET is_active = ? WHERE id = ?', (is_active, user_id))
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
    expires_at = datetime.now() + timedelta(hours=24)

    _exec(
        cursor,
        '''
        INSERT INTO sessions (user_id, session_token, expires_at)
        VALUES (?, ?, ?)
        ''',
        (user_id, session_token, expires_at),
    )

    conn.commit()
    conn.close()
    return session_token

def get_user_by_session(session_token):
    """Get user data by session token"""
    conn = get_db()
    cursor = conn.cursor()
    
    _exec(
        cursor,
        '''
        SELECT u.* FROM users u
        JOIN sessions s ON u.id = s.user_id
        WHERE s.session_token = ? AND s.expires_at > ? AND u.is_active
        ''',
        (session_token, datetime.now()),
    )
    
    user = cursor.fetchone()
    conn.close()
    
    return dict(user) if user else None

def delete_session(session_token):
    """Delete session (logout)"""
    conn = get_db()
    cursor = conn.cursor()
    _exec(cursor, 'DELETE FROM sessions WHERE session_token = ?', (session_token,))
    conn.commit()
    conn.close()

# ============================================================================
# ACTIVITY LOG
# ============================================================================

def log_activity(user_id, action, details=None, ip_address=None):
    """Log user activity"""
    conn = get_db()
    cursor = conn.cursor()
    
    _exec(
        cursor,
        '''
        INSERT INTO activity_log (user_id, action, details, ip_address)
        VALUES (?, ?, ?, ?)
        ''',
        (user_id, action, details, ip_address),
    )
    
    conn.commit()
    conn.close()

# ============================================================================
# TASK FUNCTIONS
# ============================================================================

def create_task_db(title, description, task_type, priority, created_by, 
                   assigned_to=None, xml_file_path=None, xml_file_name=None):
    """Create a new task with optional XML file attachment"""
    conn = get_db()

    task_id = _insert_return_id(
        conn,
        '''
        INSERT INTO tasks (
            title, description, task_type, priority, status,
            created_by, assigned_to, xml_file_path, xml_file_name
        ) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)
        ''',
        (
            title,
            description,
            task_type,
            priority,
            created_by,
            assigned_to,
            xml_file_path,
            xml_file_name,
        ),
    )
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

    cursor.execute(adapt_placeholders(query), params)
    tasks = cursor.fetchall()
    conn.close()

    return [dict(task) for task in tasks]

def get_task_by_id(task_id):
    """Get task details including XML file info"""
    conn = get_db()
    cursor = conn.cursor()
    
    _exec(
        cursor,
        '''
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
        ''',
        (task_id,),
    )
    
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
    _exec(
        cursor,
        '''
        UPDATE tasks
        SET status = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        ''',
        (new_status, task_id),
    )

    # Log the update
    _exec(
        cursor,
        '''
        INSERT INTO task_updates (task_id, user_id, update_type, old_value, new_value, comment)
        VALUES (?, ?, 'status_change', ?, ?, ?)
        ''',
        (task_id, user_id, old_status, new_status, comment),
    )

    conn.commit()
    conn.close()

    return True, "Status updated successfully"

def get_task_updates(task_id):
    """Get all updates for a task"""
    conn = get_db()
    cursor = conn.cursor()

    _exec(
        cursor,
        '''
        SELECT
            tu.*,
            u.username,
            u.full_name
        FROM task_updates tu
        LEFT JOIN users u ON tu.user_id = u.id
        WHERE tu.task_id = ?
        ORDER BY tu.created_at DESC
        ''',
        (task_id,),
    )

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
        _exec(cursor, 'SELECT assigned_to FROM tasks WHERE id = ?', (task_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return False, "Task not found"

        old_assignee = row['assigned_to']

        # Update task assignment
        _exec(
            cursor,
            '''
            UPDATE tasks
            SET assigned_to = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            ''',
            (assigned_to if assigned_to else None, task_id),
        )

        # Log the assignment change
        _exec(
            cursor,
            '''
            INSERT INTO task_updates (task_id, user_id, update_type, old_value, new_value, comment)
            VALUES (?, ?, 'assignment', ?, ?, ?)
            ''',
            (
                task_id,
                user_id,
                str(old_assignee) if old_assignee else 'Unassigned',
                str(assigned_to) if assigned_to else 'Unassigned',
                comment,
            ),
        )

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
        _exec(
            cursor,
            '''
            INSERT INTO task_updates (task_id, user_id, update_type, comment)
            VALUES (?, ?, 'comment', ?)
            ''',
            (task_id, user_id, comment),
        )

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

    try:
        profile_id = _insert_return_id(
            conn,
            '''
            INSERT INTO filter_profiles (user_id, profile_name, description, filter_data, is_shared)
            VALUES (?, ?, ?, ?, ?)
            ''',
            (user_id, profile_name, description, json.dumps(filter_data), is_shared),
        )
        conn.commit()
        conn.close()
        return True, profile_id
    except Exception as e:
        conn.close()
        if _unique_constraint_error(e):
            return False, 'Profile name already exists'
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
        _exec(
            cursor,
            '''
            DELETE FROM filter_profiles
            WHERE id = ? AND user_id = ?
            ''',
            (profile_id, user_id),
        )

        affected = cursor.rowcount
        conn.commit()
        conn.close()

        return affected > 0
    except Exception:
        conn.close()
        return False

def get_profiles(user_id):
    """Get user's profiles (own + shared)"""
    conn = get_db()
    cursor = conn.cursor()
    
    _exec(
        cursor,
        '''
        SELECT * FROM filter_profiles
        WHERE user_id = ? OR is_shared
        ORDER BY created_at DESC
        ''',
        (user_id,),
    )
    
    profiles = cursor.fetchall()
    conn.close()
    
    return [dict(profile) for profile in profiles]

def get_profile_by_id(profile_id, user_id):
    """Get specific profile (check ownership)"""
    conn = get_db()
    cursor = conn.cursor()
    
    _exec(
        cursor,
        '''
        SELECT * FROM filter_profiles
        WHERE id = ? AND (user_id = ? OR is_shared)
        ''',
        (profile_id, user_id),
    )
    
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
            password='PrimeNet@1234',
            full_name='System Administrator',
            department='IT',
            role='admin'
        )
        return success
    return False

# Initialize database on import
try:
    if is_postgresql():
        pass
    elif not os.path.exists(DATABASE):
        print(f"Creating database at: {os.path.abspath(DATABASE)}")
        init_db()
        create_admin_user()
        print('✓ Database initialized successfully')
except Exception as e:
    print(f"⚠️  Warning: Could not auto-initialize database: {e}")


def _parse_timestamp(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    text = text.replace('T', ' ')
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f'):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
    return None


def is_password_change_required(user, max_days=60):
    if not user:
        return True
    if user.get('force_password_change'):
        return True
    changed_at = _parse_timestamp(user.get('password_changed_at'))
    if not changed_at:
        return True
    return datetime.now() - changed_at >= timedelta(days=max_days)