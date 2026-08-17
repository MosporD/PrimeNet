from __future__ import annotations

from flask import Blueprint, jsonify, render_template

from core.radio.insights import overshooting_candidates
from core.radio.scoring import filter_rows, summarize
from core.radio.web import admin_required, attach_feature_guard, format_user, get_current_user, json_error, query_filters

overshooting_detector_bp = Blueprint("overshooting_detector", __name__)
attach_feature_guard(overshooting_detector_bp, "/overshooting-detector")


@overshooting_detector_bp.route("/overshooting-detector")
@admin_required
def overshooting_detector_page():
    return render_template(
        "radio_module.html",
        user=format_user(get_current_user()),
        module_title="Overshooting Detector",
        module_subtitle="Heuristic long-neighbor, distance, and handover evidence for possible overshooting cells.",
        module_kind="overshooting-detector",
        api_url="/api/overshooting-detector/issues",
        default_technology="4G-4G",
    )


@overshooting_detector_bp.route("/api/overshooting-detector/issues")
@admin_required
def overshooting_detector_issues():
    f = query_filters()
    try:
        payload = overshooting_candidates(vendor=f["vendor"], technology=f["technology"], area=f["area"], limit=f["limit"])
        rows = filter_rows(payload.get("issues") or [], severity=f["severity"], search=f["search"])
        return jsonify({"success": True, **payload, "summary": summarize(rows), "issues": rows})
    except Exception as exc:
        return json_error(exc)

