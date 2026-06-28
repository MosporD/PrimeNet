from __future__ import annotations

from flask import Blueprint, jsonify, render_template

from core.radio.insights import capacity_hotspots
from core.radio.scoring import filter_rows, summarize
from core.radio.web import admin_required, format_user, get_current_user, json_error, query_filters

capacity_hotspots_bp = Blueprint("capacity_hotspots", __name__)


@capacity_hotspots_bp.route("/capacity-hotspots")
@admin_required
def capacity_hotspots_page():
    return render_template(
        "radio_module.html",
        user=format_user(get_current_user()),
        module_title="Capacity Hotspots",
        module_subtitle="Ranks congested cells using PRB/utilization KPI recipes and daily baseline deltas.",
        module_kind="capacity-hotspots",
        api_url="/api/capacity-hotspots/issues",
        default_technology="all",
    )


@capacity_hotspots_bp.route("/api/capacity-hotspots/issues")
@admin_required
def capacity_hotspots_issues():
    f = query_filters()
    try:
        payload = capacity_hotspots(vendor=f["vendor"], technology=f["technology"], area=f["area"], limit=f["limit"])
        rows = filter_rows(payload.get("issues") or [], severity=f["severity"], search=f["search"])
        return jsonify({"success": True, **payload, "summary": summarize(rows), "issues": rows})
    except Exception as exc:
        return json_error(exc)

