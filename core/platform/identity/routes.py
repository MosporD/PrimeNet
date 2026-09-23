"""Login / logout blueprint — local users DB or central PrimeNet users DB."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlparse

from flask import (
    Blueprint,
    g,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)

from core.platform.identity import store
from core.platform.paths import nexuscore_public_url
from core.platform.session import clear_session_cookie, get_session_token, set_session_cookie

logger = logging.getLogger(__name__)

_LOGIN_RATE_LIMIT_ATTEMPTS = 5
_LOGIN_RATE_LIMIT_WINDOW_SEC = 2 * 60
_login_rate_lock = threading.Lock()
_login_attempts_by_ip = defaultdict(deque)
_login_attempts_by_ip_user = defaultdict(deque)


def _login_client_ip() -> str:
    forwarded = (request.headers.get("X-Forwarded-For") or "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    return (request.remote_addr or "unknown").strip() or "unknown"


def _prune_login_attempts(buf: deque, now_ts: float) -> None:
    cutoff = now_ts - _LOGIN_RATE_LIMIT_WINDOW_SEC
    while buf and buf[0] < cutoff:
        buf.popleft()


def _login_rate_limit_remaining(ip: str, username: str) -> tuple[bool, int]:
    now_ts = time.time()
    key_user = f"{ip}:{(username or '').lower()}"
    with _login_rate_lock:
        ip_buf = _login_attempts_by_ip[ip]
        user_buf = _login_attempts_by_ip_user[key_user]
        _prune_login_attempts(ip_buf, now_ts)
        _prune_login_attempts(user_buf, now_ts)
        ip_limited = len(ip_buf) >= _LOGIN_RATE_LIMIT_ATTEMPTS
        user_limited = len(user_buf) >= _LOGIN_RATE_LIMIT_ATTEMPTS
        if not ip_limited and not user_limited:
            return False, 0
        next_retry_ip = int(max(1, _LOGIN_RATE_LIMIT_WINDOW_SEC - (now_ts - ip_buf[0]))) if ip_buf else 1
        next_retry_user = int(max(1, _LOGIN_RATE_LIMIT_WINDOW_SEC - (now_ts - user_buf[0]))) if user_buf else 1
        return True, max(next_retry_ip, next_retry_user)


def _record_login_failure(ip: str, username: str) -> None:
    now_ts = time.time()
    key_user = f"{ip}:{(username or '').lower()}"
    with _login_rate_lock:
        _login_attempts_by_ip[ip].append(now_ts)
        _login_attempts_by_ip_user[key_user].append(now_ts)


def _clear_login_failures(ip: str, username: str) -> None:
    key_user = f"{ip}:{(username or '').lower()}"
    with _login_rate_lock:
        _login_attempts_by_ip_user.pop(key_user, None)


def _safe_next_url(raw: str | None, *, fallback: str) -> str:
    """Allow same-site relative paths or absolute URLs under known public hosts."""
    value = (raw or "").strip()
    if not value:
        return fallback
    if value.startswith("/") and not value.startswith("//"):
        return value
    try:
        parsed = urlparse(value)
    except Exception:
        return fallback
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return fallback
    from core.platform.paths import (
        nexpulse_public_url,
        nexuscore_public_url as nxc_url,
        primenet_public_url,
    )

    allowed_hosts = {
        urlparse(nxc_url()).netloc.lower(),
        urlparse(primenet_public_url()).netloc.lower(),
        urlparse(nexpulse_public_url()).netloc.lower(),
    }
    try:
        from flask import has_request_context, request

        if has_request_context() and request.host:
            allowed_hosts.add(request.host.split(":")[0].lower())
            allowed_hosts.add(request.host.lower())
    except Exception:
        pass
    if parsed.netloc.lower() not in allowed_hosts:
        return fallback
    return value


def create_identity_blueprint(
    *,
    db_path: str | None = None,
    platform_id: str,
    post_login_endpoint: str,
    brand_title: str | None = None,
    central: bool = False,
    require_portal: str | None = None,
    sso_redirect_login: bool = False,
) -> Blueprint:
    """Build an ``auth`` blueprint.

    ``central=True`` authenticates against PrimeNet ``ncm_users.db``
    (``database_enhanced``). Otherwise ``db_path`` is a platform-local SQLite file.
    ``sso_redirect_login=True`` sends ``/login`` to NexusCore (shared cookie).
    """
    bp = Blueprint("auth", __name__)

    def _authenticate(username: str, password: str) -> dict | None:
        if central:
            from database_enhanced import authenticate_user, init_db

            init_db()
            ok, user = authenticate_user(username, password)
            return user if ok and user else None
        assert db_path, "db_path required when central=False"
        return store.authenticate(db_path, username, password)

    def _create_session(user_id: int) -> str:
        if central:
            from database_enhanced import create_session

            return create_session(user_id)
        assert db_path
        return store.create_session(db_path, user_id)

    def _delete_session(token: str | None) -> None:
        if not token:
            return
        if central:
            from database_enhanced import delete_session

            delete_session(token)
            return
        assert db_path
        store.delete_session(db_path, token)

    def current_user() -> dict | None:
        token = get_session_token()
        if not token:
            return None
        if central:
            from database_enhanced import get_user_by_session, init_db

            init_db()
            user = get_user_by_session(token)
        else:
            assert db_path
            user = store.get_user_by_session(db_path, token)
        if not user:
            return None
        if require_portal:
            from core.platform.portal_access import user_can_access_portal

            if not user_can_access_portal(user, require_portal):
                return None
        return user

    @bp.route("/")
    def index():
        user = current_user()
        if user:
            return redirect(url_for(post_login_endpoint))
        return redirect(url_for("auth.login_page"))

    @bp.route("/login")
    def login_page():
        next_url = request.args.get("next") or ""
        allow_local = (os.getenv("NCM_ALLOW_LOCAL_LOGIN") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        if sso_redirect_login and not allow_local:
            target = next_url or request.url_root.rstrip("/") + "/"
            return redirect(nexuscore_login_url(next_url=target))
        return render_template(
            "login.html",
            platform_brand=brand_title or platform_id,
            next_url=next_url,
        )

    @bp.route("/api/login", methods=["POST"])
    def login():
        try:
            data = getattr(g, "sanitized_json", None) or request.get_json() or {}
            username = (data.get("username") or "").strip()
            password = data.get("password")
            client_ip = _login_client_ip()

            limited, retry_after = _login_rate_limit_remaining(client_ip, username)
            if limited:
                response = jsonify(
                    {
                        "error": "Too many login attempts. Try again later.",
                        "retry_after_seconds": retry_after,
                    }
                )
                response.status_code = 429
                response.headers["Retry-After"] = str(retry_after)
                return response

            if not username or password is None or password == "":
                return jsonify({"error": "Username and password required"}), 400

            user = _authenticate(username, password)
            if not user:
                _record_login_failure(client_ip, username)
                return jsonify({"error": "Invalid credentials"}), 401

            if require_portal:
                from core.platform.portal_access import user_can_access_portal

                if not user_can_access_portal(user, require_portal):
                    return jsonify({"error": "No access to this portal"}), 403

            _clear_login_failures(client_ip, username)
            token = _create_session(int(user["id"]))
            fallback = url_for(post_login_endpoint)
            redirect_to = _safe_next_url(
                data.get("next") or request.args.get("next"),
                fallback=fallback,
            )
            response = make_response(
                jsonify(
                    {
                        "success": True,
                        "message": "Login successful",
                        "redirect": redirect_to,
                        "user": {
                            "username": user.get("username"),
                            "email": user.get("email"),
                            "role": user.get("role"),
                        },
                    }
                )
            )
            set_session_cookie(response, token)
            return response
        except Exception:
            logger.exception("Login error (%s)", platform_id)
            return jsonify({"error": "Internal server error"}), 500

    @bp.route("/api/logout", methods=["POST"])
    def logout():
        try:
            token = get_session_token()
            _delete_session(token)
            response = make_response(jsonify({"success": True}))
            clear_session_cookie(response)
            return response
        except Exception:
            logger.exception("Logout error (%s)", platform_id)
            return jsonify({"error": "Internal server error"}), 500

    bp.current_user = current_user  # type: ignore[attr-defined]
    return bp


def nexuscore_login_url(*, next_url: str | None = None) -> str:
    base = f"{nexuscore_public_url().rstrip('/')}/login"
    if next_url:
        from urllib.parse import quote

        return f"{base}?next={quote(next_url, safe='')}"
    return base
