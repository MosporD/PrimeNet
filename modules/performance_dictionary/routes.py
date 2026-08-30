"""Performance Dictionary routes — browse Nokia PM measurements, counters, and KPIs."""

from __future__ import annotations

from functools import wraps

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from database_enhanced import get_user_by_session, log_activity

from .nokia_loader import (
    get_counter,
    get_counters_for_measurement,
    get_index_payload,
    get_kpi,
    get_measurement,
    search_nokia_performance,
)

performance_dictionary_bp = Blueprint(
    "performance_dictionary",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/performance_dictionary/static",
)


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        session_token = request.cookies.get("session_token")
        if not session_token:
            return redirect(url_for("auth.login_page"))
        user = get_user_by_session(session_token)
        if not user:
            return redirect(url_for("auth.login_page"))
        request.current_user = user
        return f(*args, **kwargs)

    return decorated_function


def get_current_user():
    session_token = request.cookies.get("session_token")
    if session_token:
        return get_user_by_session(session_token)
    return None


def format_user_data(user):
    if not user:
        return None
    if isinstance(user, dict):
        return {
            "username": user.get("username"),
            "email": user.get("email"),
            "role": user.get("role"),
            "id": user.get("id"),
        }
    return {
        "username": user[1],
        "email": user[2],
        "role": user[6],
        "id": user[0],
    }


@performance_dictionary_bp.route("/performance-dictionary")
@login_required
def performance_dictionary_page():
    user = get_current_user()
    return render_template("performance_dictionary.html", user=format_user_data(user))


@performance_dictionary_bp.route("/api/performance-dictionary/list", methods=["GET"])
def list_index():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        payload = get_index_payload()
        meta = payload.get("meta") or {}
        log_activity(
            (user.get("id") if isinstance(user, dict) else user[0]),
            "perf_dict_browse",
            "Browsed performance dictionary",
        )
        return jsonify({
            "success": True,
            "columns": payload.get("columns") or {},
            "measurement_index": payload.get("measurement_index") or [],
            "kpi_index": payload.get("kpi_index") or [],
            "meta": {
                "source": meta.get("source"),
                "measurement_count": meta.get("measurement_count"),
                "counter_count": meta.get("counter_count"),
                "kpi_count": meta.get("kpi_count"),
                "technologies": meta.get("technologies") or [],
            },
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@performance_dictionary_bp.route("/api/performance-dictionary/nokia/measurement", methods=["GET"])
def nokia_measurement():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    measurement_id = (request.args.get("id") or "").strip()
    if not measurement_id:
        return jsonify({"error": "Missing id query parameter"}), 400

    try:
        payload = get_measurement(measurement_id)
        return jsonify({"success": True, **payload})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@performance_dictionary_bp.route("/api/performance-dictionary/nokia/counters", methods=["GET"])
def nokia_counters():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    measurement_id = (request.args.get("measurement_id") or "").strip()
    if not measurement_id:
        return jsonify({"error": "Missing measurement_id query parameter"}), 400

    try:
        payload = get_counters_for_measurement(measurement_id)
        return jsonify({"success": True, **payload})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@performance_dictionary_bp.route("/api/performance-dictionary/nokia/counter", methods=["GET"])
def nokia_counter():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    counter_id = (request.args.get("id") or "").strip()
    if not counter_id:
        return jsonify({"error": "Missing id query parameter"}), 400

    try:
        payload = get_counter(counter_id)
        return jsonify({"success": True, **payload})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@performance_dictionary_bp.route("/api/performance-dictionary/nokia/kpi", methods=["GET"])
def nokia_kpi():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    kpi_id = (request.args.get("id") or "").strip()
    if not kpi_id:
        return jsonify({"error": "Missing id query parameter"}), 400

    try:
        payload = get_kpi(kpi_id)
        return jsonify({"success": True, **payload})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@performance_dictionary_bp.route("/api/performance-dictionary/huawei/catalog", methods=["GET"])
def huawei_catalog():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        from core.huawei_pm.counter_catalog import list_technologies, filter_counters

        tech = (request.args.get("technology") or request.args.get("tech") or "").strip().upper()
        if not tech:
            return jsonify({
                "success": True,
                "vendor": "huawei",
                "technologies": list_technologies(),
            })
        payload = filter_counters(
            tech,
            q=(request.args.get("q") or "").strip(),
            subset_id=int(request.args["subset_id"]) if request.args.get("subset_id") else None,
            limit=min(500, max(1, int(request.args.get("limit", 300)))),
            offset=max(0, int(request.args.get("offset", 0))),
        )
        return jsonify({"success": True, "vendor": "huawei", **payload})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@performance_dictionary_bp.route("/api/performance-dictionary/nokia/search", methods=["GET"])
def nokia_search():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    query = (request.args.get("q") or "").strip()
    entity = (request.args.get("entity") or "all").strip().lower()
    limit = min(500, max(1, int(request.args.get("limit", 500))))

    try:
        result = search_nokia_performance(query, entity=entity, limit=limit)
        return jsonify({"success": True, "query": query, "entity": entity, **result})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
