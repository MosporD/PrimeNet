"""
Manual Database Initialization Script
Run this to create the database and admin user
"""

import os
import sys

print("=" * 50)
print("Nokia Configuration Manager")
print("Database Initialization")
print("=" * 50)
print()

# Project root (parent of scripts/)
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
os.chdir(project_root)
sys.path.insert(0, project_root)
print(f"Working directory: {os.getcwd()}")
print()

# Import database module
try:
    from database_enhanced import init_db, create_admin_user, DATABASE
    from modules.sync.db_migration import run_migrations

    print("✓ Database module loaded")
    print(f"✓ SQLite app DB path: {DATABASE}")
    print()
except Exception as e:
    print("✗ ERROR: Failed to import database module")
    print(f"  {e}")
    input("Press Enter to exit...")
    sys.exit(1)

# Initialize database
try:
    print("Running migrations (SQLite files under databases/)...")
    run_migrations()
    print("Creating app tables (ncm_users.db)...")
    init_db()
    print("✓ Database tables created")
except Exception as e:
    print("✗ ERROR: Failed to create database")
    print(f"  {e}")
    import traceback
    traceback.print_exc()
    input("Press Enter to exit...")
    sys.exit(1)

# Create admin user
try:
    print("Creating default admin user...")
    result = create_admin_user()
    if result:
        print("✓ Admin user created")
    else:
        print("✓ Admin user already exists")
except Exception as e:
    print("✗ ERROR: Failed to create admin user")
    print(f"  {e}")
    import traceback
    traceback.print_exc()
    input("Press Enter to exit...")
    sys.exit(1)

# Verify database was created
if os.path.exists(DATABASE):
    print()
    print("=" * 50)
    print("SUCCESS! Database initialized")
    print("=" * 50)
    print()
    print(f"Database file: {DATABASE}")
    print(f"File size: {os.path.getsize(DATABASE)} bytes")
    print()
    
    bootstrap_user = (os.getenv('NCM_BOOTSTRAP_ADMIN_USERNAME') or 'admin').strip()
    has_bootstrap_pw = bool((os.getenv('NCM_BOOTSTRAP_ADMIN_PASSWORD') or '').strip())
    print("Bootstrap Admin Login:")
    print(f"  Username: {bootstrap_user}")
    print(f"  Password source: {'NCM_BOOTSTRAP_ADMIN_PASSWORD (set)' if has_bootstrap_pw else 'NOT SET'}")
    print()
    print("⚠️  IMPORTANT: Set NCM_BOOTSTRAP_ADMIN_PASSWORD in your .env before first login.")
    print()
    
    # Test admin login
    try:
        from database_enhanced import authenticate_user
        if has_bootstrap_pw:
            print("Testing bootstrap admin login...")
            success, user = authenticate_user(bootstrap_user, os.getenv('NCM_BOOTSTRAP_ADMIN_PASSWORD'))
            if success:
                print("✓ Admin login works!")
                print(f"  User ID: {user['id']}")
                print(f"  Username: {user['username']}")
                print(f"  Email: {user['email']}")
            else:
                print("✗ Admin login failed - check NCM_BOOTSTRAP_ADMIN_* values")
        else:
            print("ℹ️  Skipped admin login test (bootstrap password not set)")
    except Exception as e:
        print(f"✗ Error testing login: {e}")
    
    print()
    print("You can now run the server: python app.py")
else:
    print()
    print("=" * 50)
    print("ERROR: Database file was not created")
    print("=" * 50)
    print()
    print("This might be a permissions issue.")
    print(f"Check if you can create files in: {os.getcwd()}")

print()
input("Press Enter to exit...")
