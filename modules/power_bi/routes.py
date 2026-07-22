"""Power BI link-out gallery — opens reports in Power BI Service."""

from __future__ import annotations

from functools import wraps

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from database_enhanced import get_user_by_session
from .logic import reports_for_role

power_bi_bp = Blueprint(
    "power_bi",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/power-bi/static",
)


@power_bi_bp.before_request
def _guard_power_bi_access():
    from core.module_access import module_access_before_request

    return module_access_before_request("/power-bi")


def _current_user():
    token = request.cookies.get("session_token")
    return get_user_by_session(token) if token else None


def _format_user(user):
    if not user:
        return None
    return {
        "id": user.get("id"),
        "username": user.get("username"),
        "role": user.get("role"),
    }


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = _current_user()
        if not user:
            return redirect(url_for("auth.login_page"))
        request.current_user = user
        return f(*args, **kwargs)

    return decorated


@power_bi_bp.route("/power-bi")
@login_required
def power_bi_gallery():
    user = _current_user()
    reports = reports_for_role(user)
    return render_template(
        "gallery.html",
        user=_format_user(user),
        reports=reports,
        report_count=len(reports),
    )


@power_bi_bp.route("/api/power-bi/reports")
@login_required
def power_bi_reports_api():
    user = _current_user()
    reports = reports_for_role(user)
    return jsonify({"success": True, "reports": reports, "count": len(reports)})
