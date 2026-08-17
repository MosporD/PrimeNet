"""Small Flask helpers shared by radio modules."""

from __future__ import annotations

from functools import wraps

from flask import jsonify, redirect, request, url_for

from database_enhanced import get_user_by_session


def _role(user) -> str:
    if not user:
        return ""
    if isinstance(user, dict):
        return str(user.get("role") or "").strip().lower()
    return str(user[6] or "").strip().lower()


def _deny():
    """403 for API/JSON requests, redirect to dashboard for page requests."""
    if (request.path or "").startswith("/api/") or request.is_json:
        return jsonify({"success": False, "error": "Access denied."}), 403
    return redirect(url_for("auth.dashboard"))


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get("session_token")
        if not token:
            return redirect(url_for("auth.login_page"))
        user = get_user_by_session(token)
        if not user:
            return redirect(url_for("auth.login_page"))
        request.current_user = user
        # Honor configurable feature access: only block when a feature owns this
        # path AND the role is not permitted. Unmatched paths stay allowed.
        from core.module_access import path_access

        allowed, matched = path_access(request.path or "", user)
        if matched and not allowed:
            return _deny()
        return f(*args, **kwargs)

    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get("session_token")
        if not token:
            return redirect(url_for("auth.login_page"))
        user = get_user_by_session(token)
        if not user:
            return redirect(url_for("auth.login_page"))
        request.current_user = user
        if _role(user) == "admin":
            return f(*args, **kwargs)
        # Non-admins are allowed only when an admin has granted their role access
        # to the feature that owns this path (defaults keep admin-only modules
        # admin-only).
        from core.module_access import path_access

        allowed, matched = path_access(request.path or "", user)
        if matched and allowed:
            return f(*args, **kwargs)
        return _deny()

    return decorated


def get_current_user():
    token = request.cookies.get("session_token")
    return get_user_by_session(token) if token else None


def format_user(user):
    if not user:
        return None
    if isinstance(user, dict):
        return {"id": user.get("id"), "username": user.get("username"), "role": user.get("role")}
    return {"id": user[0], "username": user[1], "role": user[6]}


def query_filters(default_limit: int = 200) -> dict:
    return {
        "area": str(request.args.get("area") or "all").strip(),
        "vendor": str(request.args.get("vendor") or "all").strip().lower(),
        "technology": str(request.args.get("technology") or request.args.get("rat") or "all").strip(),
        "severity": str(request.args.get("severity") or "all").strip(),
        "search": str(request.args.get("q") or request.args.get("search") or "").strip(),
        "limit": min(1000, max(1, int(request.args.get("limit") or default_limit))),
    }


def json_error(exc: Exception, status: int = 500):
    return jsonify({"success": False, "error": str(exc)}), status


def attach_feature_guard(bp, href: str) -> None:
    """Honor Admin Panel feature-access grants on a blueprint (login + href ACL)."""

    @bp.before_request
    def _feature_guard():
        from core.module_access import module_access_before_request
        return module_access_before_request(href)

    _feature_guard.__name__ = f"_guard_{href.strip('/').replace('-', '_')}"

