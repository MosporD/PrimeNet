"""SON Analytics routes (development stage)."""

from __future__ import annotations

from functools import wraps

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from database_enhanced import get_user_by_session

from .area_helpers import list_areas
from .logic import build_all_recommendations, filter_recommendations, filtered_summary, get_recommendation_by_id

son_analytics_bp = Blueprint(
    "son_analytics",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/son-analytics/static",
)


@son_analytics_bp.before_request
def _guard_son_analytics_access():
    from core.module_access import module_access_before_request
    return module_access_before_request("/son-analytics")


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
    return {"id": user.get("id"), "username": user.get("username"), "role": user.get("role")}


@son_analytics_bp.route("/son-analytics")
@login_required
def son_analytics_page():
    user = get_current_user()
    return render_template(
        "son_analytics.html",
        user=format_user(user),
        stage_label="Development Stage",
    )


@son_analytics_bp.route("/api/son/areas")
@login_required
def son_areas():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"success": True, "areas": list_areas()})


@son_analytics_bp.route("/api/son/summary")
@login_required
def son_summary():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        payload = build_all_recommendations(force_refresh=False)
        summary = filtered_summary(
            payload,
            category=request.args.get("category"),
            severity=request.args.get("severity"),
            vendor=request.args.get("vendor"),
            technology=request.args.get("technology"),
            area=request.args.get("area"),
        )
        return jsonify({
            "success": True,
            "stage": "development",
            "pm_data_scope": payload.get("pm_data_scope"),
            "generated_at": payload.get("generated_at"),
            "summary": summary,
            "area": request.args.get("area") or "all",
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@son_analytics_bp.route("/api/son/recommendations")
@login_required
def son_recommendations():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        payload = build_all_recommendations(force_refresh=False)
        limit = min(200, max(1, int(request.args.get("limit", 50))))
        offset = max(0, int(request.args.get("offset", 0)))
        rows, total = filter_recommendations(
            payload,
            category=request.args.get("category"),
            severity=request.args.get("severity"),
            vendor=request.args.get("vendor"),
            technology=request.args.get("technology"),
            area=request.args.get("area"),
            limit=limit,
            offset=offset,
        )
        return jsonify({
            "success": True,
            "stage": "development",
            "pm_data_scope": payload.get("pm_data_scope"),
            "generated_at": payload.get("generated_at"),
            "total": total,
            "limit": limit,
            "offset": offset,
            "recommendations": rows,
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@son_analytics_bp.route("/api/son/recommendations/<rec_id>")
@login_required
def son_recommendation_detail(rec_id):
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        payload = build_all_recommendations(force_refresh=False)
        rec = get_recommendation_by_id(payload, rec_id)
        if not rec:
            return jsonify({"success": False, "error": "Not found"}), 404
        return jsonify({
            "success": True,
            "stage": "development",
            "generated_at": payload.get("generated_at"),
            "recommendation": rec,
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@son_analytics_bp.route("/api/son/refresh", methods=["POST"])
@login_required
def son_refresh():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    role = str(user.get("role") or "").lower()
    if role not in ("admin", "noc_sys"):
        return jsonify({"error": "Forbidden"}), 403
    try:
        payload = build_all_recommendations(force_refresh=True)
        return jsonify({
            "success": True,
            "stage": "development",
            "pm_data_scope": payload.get("pm_data_scope"),
            "generated_at": payload.get("generated_at"),
            "summary": payload.get("summary"),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500
