"""Performance Explorer Plus — Nokia raw-counter warehouse UI."""

from __future__ import annotations

from functools import wraps

from flask import (
    Blueprint,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from core.pm_plus import ledger
from core.pm_plus.kpi_compiler import validate_formula
from core.pm_plus.query import (
    delete_kpi,
    export_series_csv,
    list_counters,
    list_kpis,
    list_objects,
    list_saved_views,
    query_series,
    save_kpi,
    save_view,
    warehouse_stats,
)
from core.pm_plus.rollup import apply_retention, rollup_all
from core.pm_plus.schema import init_schema
from database_enhanced import get_user_by_session, log_activity
from core.platform.session import get_session_token
performance_explorer_plus_bp = Blueprint(
    "performance_explorer_plus",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/performance-explorer-plus/static",
)


@performance_explorer_plus_bp.before_request
def _guard_access():
    from core.module_access import module_access_before_request

    return module_access_before_request("/performance-explorer-plus")


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = get_session_token()
        if not token:
            return redirect(url_for("auth.login_page"))
        user = get_user_by_session(token)
        if not user:
            return redirect(url_for("auth.login_page"))
        request.current_user = user
        return f(*args, **kwargs)

    return decorated


def get_current_user():
    token = get_session_token()
    return get_user_by_session(token) if token else None


def format_user(user):
    if not user:
        return None
    return {
        "id": user.get("id"),
        "username": user.get("username"),
        "role": user.get("role"),
    }


@performance_explorer_plus_bp.route("/performance-explorer-plus")
@login_required
def page():
    user = get_current_user()
    try:
        init_schema()
    except Exception:
        pass
    return render_template(
        "performance_explorer_plus.html",
        user=format_user(user),
    )


@performance_explorer_plus_bp.route("/api/performance-explorer-plus/health")
@login_required
def api_health():
    try:
        init_schema()
        snap = ledger.health_snapshot()
        stats = warehouse_stats()
        return jsonify({"success": True, "lag": snap, "warehouse": stats})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"success": False, "error": str(exc)}), 500


@performance_explorer_plus_bp.route("/api/performance-explorer-plus/counters")
@login_required
def api_counters():
    q = (request.args.get("q") or "").strip()
    limit = min(1000, max(1, int(request.args.get("limit", 200))))
    try:
        return jsonify({"success": True, "counters": list_counters(q=q, limit=limit)})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"success": False, "error": str(exc)}), 500


@performance_explorer_plus_bp.route("/api/performance-explorer-plus/objects")
@login_required
def api_objects():
    q = (request.args.get("q") or "").strip()
    limit = min(1000, max(1, int(request.args.get("limit", 200))))
    try:
        return jsonify({"success": True, "objects": list_objects(q=q, limit=limit)})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"success": False, "error": str(exc)}), 500


@performance_explorer_plus_bp.route("/api/performance-explorer-plus/query", methods=["POST"])
@login_required
def api_query():
    body = request.get_json(silent=True) or {}
    try:
        result = query_series(
            counter_ids=body.get("counter_ids") or None,
            formula=body.get("formula") or None,
            object_dns=body.get("object_dns") or None,
            site_key=body.get("site_key") or None,
            resolution=body.get("resolution") or "hour",
            ts_from=body.get("ts_from") or None,
            ts_to=body.get("ts_to") or None,
            limit=min(20000, max(1, int(body.get("limit") or 5000))),
        )
        return jsonify({"success": True, **result})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"success": False, "error": str(exc)}), 500


@performance_explorer_plus_bp.route("/api/performance-explorer-plus/export", methods=["POST"])
@login_required
def api_export():
    body = request.get_json(silent=True) or {}
    try:
        result = query_series(
            counter_ids=body.get("counter_ids") or None,
            formula=body.get("formula") or None,
            object_dns=body.get("object_dns") or None,
            site_key=body.get("site_key") or None,
            resolution=body.get("resolution") or "hour",
            ts_from=body.get("ts_from") or None,
            ts_to=body.get("ts_to") or None,
            limit=min(50000, max(1, int(body.get("limit") or 20000))),
        )
        csv_text = export_series_csv(result)
        return Response(
            csv_text,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=pm_plus_export.csv"},
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"success": False, "error": str(exc)}), 500


@performance_explorer_plus_bp.route("/api/performance-explorer-plus/kpis", methods=["GET"])
@login_required
def api_kpis_list():
    try:
        return jsonify({"success": True, "kpis": list_kpis()})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"success": False, "error": str(exc)}), 500


@performance_explorer_plus_bp.route("/api/performance-explorer-plus/kpis", methods=["POST"])
@login_required
def api_kpis_save():
    user = get_current_user()
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    formula = (body.get("formula") or "").strip()
    if not name or not formula:
        return jsonify({"success": False, "error": "name and formula required"}), 400
    result = save_kpi(
        name=name,
        formula=formula,
        description=(body.get("description") or "").strip(),
        created_by=(user or {}).get("username") or "",
        scope_default=(body.get("scope_default") or "cell"),
    )
    if not result.get("ok"):
        return jsonify({"success": False, **result}), 400
    log_activity(
        (user or {}).get("id"),
        "pm_plus_kpi_save",
        f"Saved KPI {name}",
        ip_address=request.remote_addr,
    )
    return jsonify({"success": True, **result})


@performance_explorer_plus_bp.route("/api/performance-explorer-plus/kpis/<int:kpi_id>", methods=["DELETE"])
@login_required
def api_kpis_delete(kpi_id: int):
    delete_kpi(kpi_id)
    return jsonify({"success": True})


@performance_explorer_plus_bp.route("/api/performance-explorer-plus/kpis/validate", methods=["POST"])
@login_required
def api_kpis_validate():
    body = request.get_json(silent=True) or {}
    known = [c["counter_id"] for c in list_counters(limit=5000)]
    return jsonify({"success": True, **validate_formula(body.get("formula") or "", known)})


@performance_explorer_plus_bp.route("/api/performance-explorer-plus/views", methods=["GET"])
@login_required
def api_views_list():
    return jsonify({"success": True, "views": list_saved_views()})


@performance_explorer_plus_bp.route("/api/performance-explorer-plus/views", methods=["POST"])
@login_required
def api_views_save():
    user = get_current_user()
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    payload = body.get("payload") or {}
    if not name:
        return jsonify({"success": False, "error": "name required"}), 400
    result = save_view(
        name=name,
        payload=payload,
        created_by=(user or {}).get("username") or "",
    )
    return jsonify({"success": True, **result})


@performance_explorer_plus_bp.route("/api/performance-explorer-plus/rollup", methods=["POST"])
@login_required
def api_rollup():
    user = get_current_user()
    if not user or str(user.get("role") or "").lower() != "admin":
        return jsonify({"success": False, "error": "Admin only"}), 403
    body = request.get_json(silent=True) or {}
    out = {
        "rollup": rollup_all(
            ts_from=body.get("ts_from") or body.get("day_from"),
            ts_to=body.get("ts_to") or body.get("day_to"),
        )
    }
    if body.get("retention"):
        out["retention"] = apply_retention()
    return jsonify({"success": True, **out})


@performance_explorer_plus_bp.route("/api/performance-explorer-plus/nl-filters", methods=["POST"])
@login_required
def api_nl_filters():
    """Compile NL text to editable filter chips — never executes SQL."""
    body = request.get_json(silent=True) or {}
    text = body.get("text") or body.get("query") or ""
    try:
        from core.pm_plus.nl_filters import compile_nl_to_filters

        return jsonify({"success": True, **compile_nl_to_filters(text)})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"success": False, "error": str(exc)}), 500
