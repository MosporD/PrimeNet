from __future__ import annotations

from flask import Blueprint, jsonify, render_template

from core.radio.insights import change_impact
from core.radio.scoring import filter_rows, summarize
from core.radio.web import format_user, get_current_user, json_error, login_required, query_filters

change_impact_bp = Blueprint("change_impact", __name__)


@change_impact_bp.route("/change-impact")
@login_required
def change_impact_page():
    return render_template(
        "radio_module.html",
        user=format_user(get_current_user()),
        module_title="Change Impact Tracker",
        module_subtitle="Candidate PM impact correlations for CM parameter changes between snapshots.",
        module_kind="change-impact",
        api_url="/api/change-impact/issues",
        default_technology="all",
    )


@change_impact_bp.route("/api/change-impact/issues")
@login_required
def change_impact_issues():
    f = query_filters(default_limit=200)
    try:
        payload = change_impact(vendor=f["vendor"], technology=f["technology"], limit=f["limit"])
        rows = filter_rows(payload.get("issues") or [], area=f["area"], severity=f["severity"], search=f["search"])
        note = None
        if not payload.get("store", {}).get("rows"):
            note = "No CM snapshots are stored yet. Change impact appears after at least two snapshots exist."
        return jsonify({"success": True, **payload, "summary": summarize(rows), "issues": rows, "note": note})
    except Exception as exc:
        return json_error(exc)

