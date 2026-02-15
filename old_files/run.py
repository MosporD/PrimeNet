#!/usr/bin/env python3
"""
Nokia Configuration Manager - Startup Script
Run this to start the web application
"""

import subprocess
import sys
import os

def main():
    print("=" * 50)
    print("Nokia Configuration Manager - Web Version")
    print("=" * 50)
    print()

    # Change to script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    print(f"Working directory: {os.getcwd()}")
    print()

    # Check Python version
    if sys.version_info < (3, 8):
        print("ERROR: Python 3.8 or higher is required")
        print(f"Current version: {sys.version}")
        sys.exit(1)

    print(f"Python version: {sys.version}")
    print()

    # Install requirements if needed
    print("Checking dependencies...")
    try:
        import flask
        import openpyxl
        import pandas
        print("All dependencies installed.")
    except ImportError as e:
        print(f"Missing dependency: {e}")
        print("Installing dependencies from requirements.txt...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("Dependencies installed.")
    print()

    # Initialize database
    print("Initializing database...")
    try:
        from database_enhanced import init_db, create_admin_user, DATABASE
        init_db()
        result = create_admin_user()
        if result:
            print("Admin user created.")
        else:
            print("Admin user already exists.")
        print(f"Database: {os.path.abspath(DATABASE)}")
    except Exception as e:
        print(f"Warning: Database initialization: {e}")
    print()

    # Start the server
    print("=" * 50)
    print("Starting server...")
    print("=" * 50)
    print()
    print("Open your browser and go to: http://localhost:5000")
    print()
    print("Default Admin Login:")
    print("  Username: admin")
    print("  Password: admin123")
    print()
    print("Press Ctrl+C to stop the server")
    print("=" * 50)
    print()

    # Import and run the app
    from app_enhanced import app
    app.run(host='0.0.0.0', port=5000, debug=True)

if __name__ == '__main__':
    main()
