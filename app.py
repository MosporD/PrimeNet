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
from routes.auth_routes import auth_bp
from routes.xml_parser_routes import xml_parser_bp
from routes.excel_generator_routes import excel_generator_bp
from routes.ne_comparison_routes import ne_comparison_bp
from routes.parameter_dictionary_routes import parameter_dictionary_bp
from routes.network_map_routes import network_map_bp
from routes.admin_panel_routes import admin_panel_bp

app.register_blueprint(auth_bp)
app.register_blueprint(xml_parser_bp)
app.register_blueprint(excel_generator_bp)
app.register_blueprint(ne_comparison_bp)
app.register_blueprint(parameter_dictionary_bp)
app.register_blueprint(network_map_bp)
app.register_blueprint(admin_panel_bp)

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

try:
    init_db()
    create_admin_user()
    print("[OK] Database initialized successfully")
except Exception as e:
    print(f"[WARNING] Database initialization: {e}")

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
