from __future__ import annotations

from flask import Blueprint, jsonify, render_template

from core.radio.insights import layer_coverage_gaps
from core.radio.scoring import filter_rows, summarize
from core.radio.web import admin_required, format_user, get_current_user, json_error, query_filters

layer_coverage_bp = Blueprint("layer_coverage", __name__)


@layer_coverage_bp.route("/layer-coverage")
@admin_required
def layer_coverage_page():
    return render_template(
        "radio_module.html",
        user=format_user(get_current_user()),
        module_title="Layer Coverage Gaps",
        module_subtitle="Inventory-based missing RAT, LTE layer, and sector build consistency checks.",
        module_kind="layer-coverage",
        api_url="/api/layer-coverage/issues",
        default_technology="all",
    )


@layer_coverage_bp.route("/api/layer-coverage/issues")
@admin_required
def layer_coverage_issues():
    f = query_filters(default_limit=500)
    try:
        payload = layer_coverage_gaps(area=f["area"], search=f["search"], limit=f["limit"])
        rows = filter_rows(payload.get("issues") or [], severity=f["severity"], vendor=f["vendor"], technology=f["technology"])
        return jsonify({"success": True, **payload, "summary": summarize(rows), "issues": rows})
    except Exception as exc:
        return json_error(exc)

