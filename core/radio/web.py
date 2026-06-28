"""Small Flask helpers shared by radio modules."""

from __future__ import annotations

from functools import wraps

from flask import jsonify, redirect, request, url_for

from database_enhanced import get_user_by_session


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
        return f(*args, **kwargs)

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

