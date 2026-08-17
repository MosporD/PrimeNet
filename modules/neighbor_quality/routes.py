from __future__ import annotations

from flask import Blueprint, jsonify, render_template

from core.radio.insights import neighbor_quality
from core.radio.scoring import filter_rows, summarize
from core.radio.web import admin_required, attach_feature_guard, format_user, get_current_user, json_error, query_filters

neighbor_quality_bp = Blueprint("neighbor_quality", __name__)
attach_feature_guard(neighbor_quality_bp, "/neighbor-quality")


@neighbor_quality_bp.route("/neighbor-quality")
@admin_required
def neighbor_quality_page():
    return render_template(
        "radio_module.html",
        user=format_user(get_current_user()),
        module_title="Neighbor Quality Analyzer",
        module_subtitle="Scores low handover SR, failed HOs, distant neighbors, and missing reciprocal relations.",
        module_kind="neighbor-quality",
        api_url="/api/neighbor-quality/issues",
        default_technology="4G-4G",
    )


@neighbor_quality_bp.route("/api/neighbor-quality/issues")
@admin_required
def neighbor_quality_issues():
    f = query_filters()
    try:
        payload = neighbor_quality(vendor=f["vendor"], technology=f["technology"], area=f["area"], limit=f["limit"])
        rows = filter_rows(payload.get("issues") or [], severity=f["severity"], search=f["search"])
        return jsonify({"success": True, **payload, "summary": summarize(rows), "issues": rows})
    except Exception as exc:
        return json_error(exc)

