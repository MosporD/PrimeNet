from flask import Flask, jsonify, redirect, request, url_for
import os
import sys
import subprocess
import secrets
import threading
import re
from flask import g
from urllib.parse import urlparse
from werkzeug.serving import WSGIRequestHandler

# Add current directory to Python path
sys.path.append(os.path.dirname(__file__))

# Load .env before activation_gate reads NCM_SKIP_ACTIVATION / license settings.
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)
except ImportError:
    pass

from core.activation_gate import install_sqlite_gate

install_sqlite_gate()

# Initialize Flask app
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB
app.config['SECRET_KEY'] = (os.getenv('FLASK_SECRET_KEY') or os.getenv('SECRET_KEY') or secrets.token_hex(32))


@app.context_processor
def inject_module_versions():
    from core.module_versions import MODULE_VERSIONS
    return {'module_versions': MODULE_VERSIONS}

# ============================================================================
# REGISTER BLUEPRINTS
# ============================================================================

# Import and register blueprints
from routes.auth_routes import auth_bp                          # auth (shared infra)
from routes.activation_routes import activation_bp
from utils.input_safety import sanitize_json, sanitize_mapping_values
from modules.network_map.routes import network_map_bp
from modules.performance.routes import performance_bp
from modules.ne_comparison.routes import ne_comparison_bp
from modules.excel_generator.routes import excel_generator_bp
from modules.xml_parser.routes import xml_parser_bp
from modules.cm_extractor import cm_extractor_bp
from modules.parameter_dictionary.routes import parameter_dictionary_bp
from modules.performance_dictionary.routes import performance_dictionary_bp
from modules.admin_panel.routes import admin_panel_bp
from modules.sync.routes import sync_bp
from modules.config_history.routes import config_history_bp
from modules.network_management.routes import network_management_bp
from modules.reports.routes import reports_bp
from modules.conflict_map.routes import conflict_map_bp
from modules.user_profile.routes import user_profile_bp
from modules.femto_pm.routes import femto_pm_bp
from modules.task_scheduler.routes import task_scheduler_bp
from modules.drive_test_viewer.routes import drive_test_viewer_bp
from modules.cell_heatmap.routes import cell_heatmap_bp
from modules.ran_features.routes import ran_features_bp
from modules.son_analytics.routes import son_analytics_bp
from modules.network_health.routes import network_health_bp
from modules.sector_health.routes import sector_health_bp
from modules.performance_analytics import performance_analytics_bp
from modules.radio_api import radio_api_bp
from modules.neighbor_quality import neighbor_quality_bp
from modules.capacity_hotspots import capacity_hotspots_bp
from modules.layer_coverage import layer_coverage_bp
from modules.overshooting_detector import overshooting_detector_bp
from modules.rf_optimization import rf_optimization_bp
from modules.cm_parameter_audit import cm_parameter_audit_bp
from modules.change_impact import change_impact_bp
from modules.radio_morning_report import radio_morning_report_bp
from modules.fault_management import fault_management_bp
from modules.elevation import elevation_bp
from modules.sleeping_cells import sleeping_cells_bp
from modules.ret_management import ret_management_bp
from modules.power_bi.routes import power_bi_bp
from modules.documentation import documentation_bp
from modules.nokia_load_balancing import nokia_load_balancing_bp
from modules.huawei_load_balancing import huawei_load_balancing_bp

app.register_blueprint(auth_bp)
app.register_blueprint(activation_bp)
app.register_blueprint(xml_parser_bp)
app.register_blueprint(cm_extractor_bp)
app.register_blueprint(excel_generator_bp)
app.register_blueprint(ne_comparison_bp)
app.register_blueprint(parameter_dictionary_bp)
app.register_blueprint(performance_dictionary_bp)
app.register_blueprint(network_map_bp)
app.register_blueprint(admin_panel_bp)
app.register_blueprint(sync_bp)
app.register_blueprint(performance_bp)
app.register_blueprint(config_history_bp)
app.register_blueprint(network_management_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(conflict_map_bp)
app.register_blueprint(user_profile_bp)
app.register_blueprint(femto_pm_bp)
app.register_blueprint(task_scheduler_bp)
app.register_blueprint(drive_test_viewer_bp)
app.register_blueprint(cell_heatmap_bp)
app.register_blueprint(ran_features_bp)
app.register_blueprint(son_analytics_bp)
app.register_blueprint(network_health_bp)
app.register_blueprint(sector_health_bp)
app.register_blueprint(performance_analytics_bp)
app.register_blueprint(radio_api_bp)
app.register_blueprint(neighbor_quality_bp)
app.register_blueprint(capacity_hotspots_bp)
app.register_blueprint(layer_coverage_bp)
app.register_blueprint(overshooting_detector_bp)
app.register_blueprint(rf_optimization_bp)
app.register_blueprint(cm_parameter_audit_bp)
app.register_blueprint(change_impact_bp)
app.register_blueprint(radio_morning_report_bp)
app.register_blueprint(fault_management_bp)
app.register_blueprint(elevation_bp)
app.register_blueprint(sleeping_cells_bp)
app.register_blueprint(ret_management_bp)
app.register_blueprint(power_bi_bp)
app.register_blueprint(documentation_bp)
app.register_blueprint(nokia_load_balancing_bp)
app.register_blueprint(huawei_load_balancing_bp)


@app.route("/amle-optimizer")
@app.route("/amle-optimizer/<path:rest>")
def legacy_amle_optimizer_redirect(rest=""):
    target = "/nokia-load-balancing"
    if rest:
        target = f"{target}/{rest}"
    return redirect(target, 301)


def _env_true(key: str, default: bool = False) -> bool:
    raw = (os.getenv(key) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")

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
# DATABASE INITIALIZATION (local dev / single-process only)
# ============================================================================

from database_enhanced import get_user_by_session, is_password_change_required
from core.activation_gate import activation_status, is_activated
from deploy.bootstrap import run_app_bootstrap_if_enabled

_post_activation_bootstrap_done = False


def _ensure_post_activation_bootstrap() -> None:
    global _post_activation_bootstrap_done
    if _post_activation_bootstrap_done or not is_activated():
        return
    _post_activation_bootstrap_done = True
    run_app_bootstrap_if_enabled()


if is_activated():
    _ensure_post_activation_bootstrap()
else:
    print("[INFO] Sync bootstrap deferred until operator activation")


def _start_live_logger_terminal():
    """
    Open a separate terminal window that tails sync_log entries (Windows dev only).
    Disabled in containers and when NCM_DISABLE_LIVE_LOGGER_TERMINAL=1.
    """
    if _env_true('NCM_CONTAINER') or _env_true('NCM_DISABLE_LIVE_LOGGER_TERMINAL'):
        return
    if os.environ.get('NCM_DISABLE_LIVE_LOGGER_TERMINAL', '').strip().lower() in ('1', 'true', 'yes'):
        return
    # Start once from the reloader parent to avoid duplicate windows.
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        return
    script = os.path.join(os.path.dirname(__file__), 'scripts', 'live_sync_logger.py')
    if not os.path.isfile(script):
        print(f"[WARNING] Live logger script not found: {script}")
        return
    cmd = f"cd '{os.path.dirname(__file__)}'; python scripts/live_sync_logger.py"
    try:
        subprocess.Popen(
            ['powershell', '-NoExit', '-Command', cmd],
            creationflags=getattr(subprocess, 'CREATE_NEW_CONSOLE', 0),
        )
        print('[OK] Live sync logger terminal opened')
    except Exception as e:
        print(f"[WARNING] Could not open live logger terminal: {e}")


_start_live_logger_terminal()


def _open_dashboard_browser():
    """Open the dashboard in the default browser (Windows dev only)."""
    if _env_true('NCM_CONTAINER') or _env_true('NCM_DISABLE_AUTO_BROWSER'):
        return
    port = int(os.getenv('FLASK_PORT', '5000'))
    url = f'http://localhost:{port}/dashboard'
    try:
        subprocess.run(
            ['powershell', '-Command', f'Start-Process {url}'],
            check=False,
        )
    except Exception as e:
        print(f'[WARNING] Could not open dashboard in browser: {e}')

# ============================================================================
# HEALTH (container orchestration / load balancers)
# ============================================================================

@app.route('/health')
@app.route('/api/health')
def health_check():
    act = activation_status()
    if not act.get('activated'):
        return jsonify({
            'status': 'locked',
            'service': 'primenet',
            'activation': act,
        }), 503

    from db.runtime import connect_app, execute_query

    payload = {'status': 'ok', 'service': 'primenet', 'activation': act}
    try:
        conn = connect_app()
        try:
            execute_query(conn, 'SELECT 1')
        finally:
            conn.close()
        payload['database'] = 'ok'
    except Exception as exc:
        payload['status'] = 'degraded'
        payload['database'] = str(exc)
        return jsonify(payload), 503
    return jsonify(payload), 200

# ============================================================================
# REQUEST HOOKS
# ============================================================================

@app.before_request
def enforce_monthly_operator_activation():
    path = request.path or '/'
    if path.startswith('/static/') or path.startswith('/favicon'):
        return None
    allowed = {
        '/activation',
        '/api/activation/status',
        '/api/activation/unlock',
        '/health',
        '/api/health',
    }
    if path in allowed:
        return None
    if is_activated():
        _ensure_post_activation_bootstrap()
        return None
    status = activation_status()
    if path.startswith('/api/'):
        return jsonify({
            'error': status.get('message') or 'Operator activation required',
            'activation_required': True,
            'activation': status,
        }), 403
    from flask import redirect
    return redirect('/activation')


@app.before_request
def validate_and_sanitize_request_input():
    """
    Global request guard:
    - Reject malformed JSON bodies.
    - Reject oversized query/form/json input.
    - Provide sanitized payloads via flask.g for route handlers.
    """
    max_query_len = 4096
    path = (request.path or '').lower()
    is_cm_extractor_api = path.startswith('/api/cm-extractor/')
    max_json_bytes = 8_000_000 if is_cm_extractor_api else 1_000_000
    max_json_items = 100_000 if is_cm_extractor_api else 5_000
    max_form_bytes = 1_000_000
    if len(request.query_string or b"") > max_query_len:
        return jsonify({'error': 'Query string too large'}), 413

    try:
        g.sanitized_args = sanitize_mapping_values(
            list(request.args.items(multi=True)),
            max_items=300,
            max_key_len=128,
            max_val_len=1024,
        )
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    if request.content_type and request.content_type.startswith('application/x-www-form-urlencoded'):
        if (request.content_length or 0) > max_form_bytes:
            return jsonify({'error': 'Form payload too large'}), 413
        try:
            g.sanitized_form = sanitize_mapping_values(
                list(request.form.items(multi=True)),
                max_items=500,
                max_key_len=128,
                max_val_len=4096,
            )
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
    else:
        g.sanitized_form = {}

    if request.is_json:
        if (request.content_length or 0) > max_json_bytes:
            return jsonify({'error': 'JSON payload too large'}), 413
        raw = request.get_data(cache=True)
        if raw:
            parsed = request.get_json(silent=True)
            if parsed is None:
                return jsonify({'error': 'Malformed JSON payload'}), 400
            try:
                g.sanitized_json = sanitize_json(
                    parsed,
                    max_depth=10,
                    max_items=max_json_items,
                    max_key_len=128,
                    max_str_len=4096,
                )
            except ValueError as e:
                return jsonify({'error': str(e)}), 400
        else:
            g.sanitized_json = {}
    else:
        g.sanitized_json = {}

    return None


@app.before_request
def enforce_csrf_origin_for_cookie_auth():
    """
    Basic CSRF protection for cookie-authenticated state-changing requests.
    """
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    token = request.cookies.get("session_token")
    if not token:
        return None
    origin = (request.headers.get("Origin") or "").strip()
    referer = (request.headers.get("Referer") or "").strip()
    host = (request.host_url or "").rstrip("/")

    def _same_origin(url_val: str) -> bool:
        if not url_val:
            return False
        try:
            parsed = urlparse(url_val)
            req = urlparse(host)
            return (parsed.scheme, parsed.netloc) == (req.scheme, req.netloc)
        except Exception:
            return False

    if origin and not _same_origin(origin):
        return jsonify({"error": "CSRF origin check failed"}), 403
    if not origin and referer and not _same_origin(referer):
        return jsonify({"error": "CSRF referer check failed"}), 403
    if not origin and not referer:
        return jsonify({"error": "Missing CSRF origin context"}), 403
    return None


@app.before_request
def enforce_password_rotation():
    path = request.path or '/'
    if path.startswith('/static/') or path.startswith('/favicon'):
        return None
    allowed_exact = {
        '/login',
        '/api/login',
        '/api/logout',
        '/profile',
        '/api/profile/change-password',
    }
    if path in allowed_exact or path.startswith('/user_profile/static/'):
        return None

    session_token = request.cookies.get('session_token')
    if not session_token:
        return None
    user = get_user_by_session(session_token)
    if not user:
        return None
    if not is_password_change_required(user):
        return None

    if path.startswith('/api/'):
        return jsonify({
            'error': 'Password change required. Please update your password.',
            'password_change_required': True,
        }), 403
    return redirect(url_for('user_profile.profile_page', force_password_change=1))


# Inline boot: apply saved theme before first paint (avoids light-mode FOUC on nav).
_THEME_BOOT_SCRIPT = (
    '<script data-primenet-theme-boot="1">'
    '(function(){try{'
    'var t=localStorage.getItem("primenet-theme");'
    'if(t!=="dark"&&t!=="light"){'
    'var L=localStorage.getItem("darkMode");'
    'if(L==="true")t="dark";else if(L==="false")t="light";'
    'else t=(window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches)?"dark":"light";'
    '}'
    'document.documentElement.setAttribute("data-theme",t);'
    'if(document.body)document.body.classList.toggle("dark-mode",t==="dark");'
    '}catch(e){}})();'
    '</script>'
)


@app.after_request
def set_security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://unpkg.com; "
        "img-src 'self' data: blob: https://*.tile.openstreetmap.org https://*.tile.openstreetmap.fr https://server.arcgisonline.com; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'self'; "
        "base-uri 'self';"
    )
    resp.headers.setdefault("Content-Security-Policy", csp)
    if _env_true("NCM_ENABLE_HSTS", False):
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

    # Run as first thing inside <body> so body.dark-mode exists before content paints.
    try:
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if resp.status_code == 200 and "text/html" in ctype and not resp.direct_passthrough:
            data = resp.get_data(as_text=True)
            if data and "data-primenet-theme-boot" not in data:
                data2, n = re.subn(
                    r"(<body\b[^>]*>)",
                    r"\1" + _THEME_BOOT_SCRIPT,
                    data,
                    count=1,
                    flags=re.IGNORECASE,
                )
                if n:
                    resp.set_data(data2)
    except Exception:
        pass
    return resp

if __name__ == '__main__':
    class ConciseRequestHandler(WSGIRequestHandler):
        """Hide query strings in access logs (e.g., massive KPI lists)."""
        def log_request(self, code='-', size='-'):
            req = self.requestline or ''
            try:
                parts = req.split(' ', 2)
                if len(parts) == 3:
                    method, target, version = parts
                    safe_target = target.split('?', 1)[0]
                    req = f'{method} {safe_target} {version}'
            except Exception:
                pass
            self.log('info', '"%s" %s %s', req, code, size)

    print("=" * 60)
    print("PrimeNet - Network Performance & Configuration Platform")
    print("=" * 60)
    print("Starting server...")
    debug = _env_true("FLASK_DEBUG", False)
    port = int(os.getenv("FLASK_PORT", "5000"))
    print(f"Dashboard: http://localhost:{port}/dashboard")
    print("=" * 60)
    # Open browser once the server is listening (skip reloader parent).
    if not debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        threading.Timer(1.5, _open_dashboard_browser).start()
    app.run(
        debug=debug,
        host=os.getenv("FLASK_HOST", "0.0.0.0"),
        port=port,
        request_handler=ConciseRequestHandler,
    )