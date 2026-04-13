"""
Nokia Configuration Manager - Modular Application
Main application file with Blueprint architecture
"""

from flask import Flask
import os
import sys

# Add current directory to Python path
sys.path.append(os.path.dirname(__file__))

# Initialize Flask app
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB
app.config['SECRET_KEY'] = 'your-secret-key-change-this-in-production'

# ============================================================================
# REGISTER BLUEPRINTS
# ============================================================================

# Import and register blueprints
from routes.auth_routes import auth_bp                          # auth (shared infra)
from network_map.routes import network_map_bp                   # module: network_map/
from performance.routes import performance_bp                   # module: performance/
from ne_comparison.routes import ne_comparison_bp               # module: ne_comparison/
from excel_generator.routes import excel_generator_bp           # module: excel_generator/
from xml_parser.routes import xml_parser_bp                     # module: xml_parser/
from parameter_dictionary.routes import parameter_dictionary_bp # module: parameter_dictionary/
from admin_panel.routes import admin_panel_bp                   # module: admin_panel/
from sync.routes import sync_bp                                 # sync infra: sync/
from config_history.routes import config_history_bp             # module: config_history/
from network_management.routes import network_management_bp     # module: network_management/
from reports.routes import reports_bp                           # module: reports/
from user_profile.routes import user_profile_bp                 # module: user_profile/

app.register_blueprint(auth_bp)
app.register_blueprint(xml_parser_bp)
app.register_blueprint(excel_generator_bp)
app.register_blueprint(ne_comparison_bp)
app.register_blueprint(parameter_dictionary_bp)
app.register_blueprint(network_map_bp)
app.register_blueprint(admin_panel_bp)
app.register_blueprint(sync_bp)
app.register_blueprint(performance_bp)
app.register_blueprint(config_history_bp)
app.register_blueprint(network_management_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(user_profile_bp)

# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(413)
def request_entity_too_large(error):
    from flask import jsonify
    return jsonify({'error': 'File too large. Maximum size is 100MB'}), 413

@app.errorhandler(500)
def internal_error(error):
    from flask import jsonify
    return jsonify({'error': 'Internal server error'}), 500

# ============================================================================
# DATABASE INITIALIZATION
# ============================================================================

from database_enhanced import init_db, create_admin_user

# ============================================================================
# DATA DB MIGRATIONS (SQLite files or PostgreSQL bootstrap)
# ============================================================================
from sync_config import probe_postgresql_at_startup

probe_postgresql_at_startup()

try:
    from sync.db_migration import run_migrations

    run_migrations()
    print('[OK] Data databases migrated successfully')
except Exception as e:
    print(f'[WARNING] Data DB migrations: {e}')

try:
    init_db()
    create_admin_user()
    print('[OK] App user database initialized successfully')
except Exception as e:
    print(f'[WARNING] App database initialization: {e}')

# Start SFTP sync scheduler
# - In debug mode, Werkzeug starts a reloader parent process + a child server process.
#   We only start the scheduler once (in the reloader parent) using the same guard
#   we already had, but we also allow disabling it entirely for local debugging.
import os
if os.environ.get('NCM_DISABLE_SCHEDULER') == '1':
    print("[INFO] Sync scheduler disabled (NCM_DISABLE_SCHEDULER=1)")
elif os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
    from sync.scheduler import start_scheduler
    try:
        start_scheduler()
        print("[OK] Sync scheduler started")
    except Exception as e:
        print(f"[WARNING] Sync scheduler could not start: {e}")

# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    print("=" * 60)
    print("Nokia Configuration Manager - Modular Version")
    print("=" * 60)
    print("Starting server...")
    print("Dashboard: http://localhost:5000/dashboard")
    print("=" * 60)
    app.run(debug=True, host='0.0.0.0', port=5000)
