"""Minimal Flask factory shared by NexusCore, PrimeNet, and NexPulse."""

from __future__ import annotations

import os
import re
import secrets
import sys
from urllib.parse import urlparse

from flask import Flask, Response, g, jsonify, request
from werkzeug.serving import WSGIRequestHandler

_THEME_BOOT_SCRIPT = (
    '<script data-primenet-theme-boot="1">'
    "(function(){try{"
    'var t=localStorage.getItem("primenet-theme");'
    'if(t!=="dark"&&t!=="light"){'
    'var L=localStorage.getItem("darkMode");'
    'if(L==="true")t="dark";else if(L==="false")t="light";'
    'else t=(window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches)?"dark":"light";'
    "}"
    'document.documentElement.setAttribute("data-theme",t);'
    'if(document.body)document.body.classList.toggle("dark-mode",t==="dark");'
    "}catch(e){}})();"
    "</script>"
)


def env_true(key: str, default: bool = False) -> bool:
    raw = (os.getenv(key) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def create_base_app(
    service_name: str,
    *,
    session_cookie_name: str,
    secret_key_env: str | None = None,
) -> Flask:
    """Create a Flask app with shared security headers, health, and sanitizers."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if root not in sys.path:
        sys.path.insert(0, root)

    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(root, ".env"), override=True)
    except ImportError:
        pass

    app = Flask(
        service_name,
        template_folder=os.path.join(root, "templates"),
        static_folder=os.path.join(root, "static"),
    )
    app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024
    app.config["SERVICE_NAME"] = service_name
    app.config["SESSION_COOKIE_NAME"] = session_cookie_name

    secret_envs = [secret_key_env] if secret_key_env else []
    secret_envs.extend(["FLASK_SECRET_KEY", "SECRET_KEY"])
    configured_secret = ""
    for key in secret_envs:
        if not key:
            continue
        configured_secret = (os.getenv(key) or "").strip()
        if configured_secret:
            break
    app.config["SECRET_KEY"] = configured_secret or secrets.token_hex(32)
    app.config["SECRET_KEY_EPHEMERAL"] = not bool(configured_secret)
    if not configured_secret:
        print(
            f"[WARNING] No secret key for {service_name} — using a random per-process secret. "
            "Set FLASK_SECRET_KEY (or the platform-specific key) in .env for a stable deployment."
        )

    @app.context_processor
    def inject_module_versions():
        try:
            from core.module_versions import MODULE_VERSIONS

            return {"module_versions": MODULE_VERSIONS}
        except Exception:
            return {"module_versions": {}}

    def _wants_json_error() -> bool:
        path = request.path or ""
        if path.startswith("/api/"):
            return True
        accept = (request.headers.get("Accept") or "").lower()
        if "application/json" in accept and "text/html" not in accept:
            return True
        return request.headers.get("X-Requested-With") == "XMLHttpRequest"

    @app.errorhandler(404)
    def not_found(error):
        if _wants_json_error():
            return jsonify({"error": "Not found"}), 404
        try:
            from flask import render_template

            return render_template("404.html", user=None, requested_path=(request.path or "")[:180]), 404
        except Exception:
            return jsonify({"error": "Not found"}), 404

    @app.errorhandler(413)
    def request_entity_too_large(error):
        return jsonify({"error": "File too large. Maximum size is 100MB"}), 413

    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({"error": "Internal server error"}), 500

    @app.route("/health/live")
    @app.route("/api/health/live")
    def health_live():
        return jsonify({"status": "ok", "service": service_name}), 200

    @app.route("/health")
    @app.route("/api/health")
    def health_check():
        return jsonify({"status": "ok", "service": service_name}), 200

    @app.route("/robots.txt")
    def robots_txt():
        body = (
            "User-agent: *\n"
            "Disallow: /\n"
            "\n"
            f"# {service_name} is an internal operator platform.\n"
        )
        resp = Response(body, mimetype="text/plain; charset=utf-8")
        resp.headers["X-Robots-Tag"] = "noindex, nofollow"
        return resp

    @app.before_request
    def validate_and_sanitize_request_input():
        from utils.input_safety import sanitize_json, sanitize_mapping_values

        max_query_len = 4096
        path = (request.path or "").lower()
        is_cm_extractor_api = path.startswith("/api/cm-extractor/")
        max_json_bytes = 8_000_000 if is_cm_extractor_api else 1_000_000
        max_json_items = 100_000 if is_cm_extractor_api else 5_000
        max_form_bytes = 1_000_000
        if len(request.query_string or b"") > max_query_len:
            return jsonify({"error": "Query string too large"}), 413

        try:
            g.sanitized_args = sanitize_mapping_values(
                list(request.args.items(multi=True)),
                max_items=300,
                max_key_len=128,
                max_val_len=1024,
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

        if request.content_type and request.content_type.startswith("application/x-www-form-urlencoded"):
            if (request.content_length or 0) > max_form_bytes:
                return jsonify({"error": "Form payload too large"}), 413
            try:
                g.sanitized_form = sanitize_mapping_values(
                    list(request.form.items(multi=True)),
                    max_items=500,
                    max_key_len=128,
                    max_val_len=4096,
                )
            except ValueError as e:
                return jsonify({"error": str(e)}), 400
        else:
            g.sanitized_form = {}

        if request.is_json:
            if (request.content_length or 0) > max_json_bytes:
                return jsonify({"error": "JSON payload too large"}), 413
            raw = request.get_data(cache=True)
            if raw:
                parsed = request.get_json(silent=True)
                if parsed is None:
                    return jsonify({"error": "Malformed JSON payload"}), 400
                try:
                    g.sanitized_json = sanitize_json(
                        parsed,
                        max_depth=10,
                        max_items=max_json_items,
                        max_key_len=128,
                        max_str_len=4096,
                    )
                except ValueError as e:
                    return jsonify({"error": str(e)}), 400
            else:
                g.sanitized_json = {}
        else:
            g.sanitized_json = {}
        return None

    @app.before_request
    def enforce_csrf_origin_for_cookie_auth():
        from core.platform.session import get_session_token

        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return None
        if not get_session_token():
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

    @app.after_request
    def set_security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        resp.headers.setdefault("X-Robots-Tag", "noindex, nofollow, noarchive")
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
        if env_true("NCM_ENABLE_HSTS", False):
            resp.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        try:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if resp.status_code in (200, 404) and "text/html" in ctype and not resp.direct_passthrough:
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

    return app


class ConciseRequestHandler(WSGIRequestHandler):
    """Hide query strings in access logs (e.g., massive KPI lists)."""

    def log_request(self, code="-", size="-"):
        req = self.requestline or ""
        try:
            parts = req.split(" ", 2)
            if len(parts) == 3:
                method, target, version = parts
                safe_target = target.split("?", 1)[0]
                req = f"{method} {safe_target} {version}"
        except Exception:
            pass
        self.log("info", '"%s" %s %s', req, code, size)


def run_dev_server(app: Flask, *, title: str, default_port: int, open_path: str = "/"):
    import threading

    print("=" * 60)
    print(title)
    print("=" * 60)
    print("Starting server...")
    debug = env_true("FLASK_DEBUG", False)
    port = int(os.getenv("FLASK_PORT", str(default_port)))
    print(f"URL: http://localhost:{port}{open_path}")
    print("=" * 60)

    def _open_browser():
        if os.name != "nt":
            return
        if env_true("NCM_CONTAINER") or env_true("NCM_DISABLE_AUTO_BROWSER"):
            return
        url = f"http://localhost:{port}{open_path}"
        try:
            import subprocess

            subprocess.run(["powershell", "-Command", f"Start-Process {url}"], check=False)
        except Exception as e:
            print(f"[WARNING] Could not open browser: {e}")

    if not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        threading.Timer(1.5, _open_browser).start()
    app.run(
        debug=debug,
        host=os.getenv("FLASK_HOST", "0.0.0.0"),
        port=port,
        request_handler=ConciseRequestHandler,
    )
