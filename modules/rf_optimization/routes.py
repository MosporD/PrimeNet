from __future__ import annotations

from flask import Blueprint, jsonify, render_template

from core.radio.insights import rf_optimization
from core.radio.scoring import filter_rows, summarize
from core.radio.web import format_user, get_current_user, json_error, login_required, query_filters

rf_optimization_bp = Blueprint("rf_optimization", __name__)


@rf_optimization_bp.route("/rf-optimization")
@login_required
def rf_optimization_page():
    return render_template(
        "radio_module.html",
        user=format_user(get_current_user()),
        module_title="RF Optimization Workbench",
        module_subtitle="Prioritized RF action queue across mobility, capacity, layer, coverage, and configuration signals.",
        module_kind="rf-optimization",
        api_url="/api/rf-optimization/issues",
        default_technology="all",
    )


@rf_optimization_bp.route("/api/rf-optimization/issues")
@login_required
def rf_optimization_issues():
    f = query_filters(default_limit=250)
    try:
        payload = rf_optimization(area=f["area"], vendor=f["vendor"], technology=f["technology"], limit=f["limit"])
        rows = filter_rows(payload.get("issues") or [], severity=f["severity"], search=f["search"])
        return jsonify({"success": True, **payload, "summary": summarize(rows), "issues": rows})
    except Exception as exc:
        return json_error(exc)

