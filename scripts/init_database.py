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

# Make sure we're in the right directory
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
print(f"Working directory: {os.getcwd()}")
print()

# Import database module
try:
    from database_enhanced import init_db, create_admin_user, get_db, DATABASE
    print(f"✓ Database module loaded")
    print(f"✓ Database location: {DATABASE}")
    print()
except Exception as e:
    print(f"✗ ERROR: Failed to import database module")
    print(f"  {e}")
    input("Press Enter to exit...")
    sys.exit(1)

# Initialize database
try:
    print("Creating database tables...")
    init_db()
    print("✓ Database tables created")
except Exception as e:
    print(f"✗ ERROR: Failed to create database")
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
    print(f"✗ ERROR: Failed to create admin user")
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
    
    # Show admin credentials
    print("Default Admin Login:")
    print("  Username: admin")
    print("  Password: admin123")
    print()
    print("⚠️  IMPORTANT: Change the admin password after first login!")
    print()
    
    # Test admin login
    try:
        from database_enhanced import authenticate_user
        print("Testing admin login...")
        success, user = authenticate_user('admin', 'admin123')
        if success:
            print("✓ Admin login works!")
            print(f"  User ID: {user['id']}")
            print(f"  Username: {user['username']}")
            print(f"  Email: {user['email']}")
        else:
            print("✗ Admin login failed - something is wrong")
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
