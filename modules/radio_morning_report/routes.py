from __future__ import annotations

from flask import Blueprint, jsonify, render_template

from core.radio.insights import radio_morning_report
from core.radio.scoring import filter_rows, summarize
from core.radio.web import admin_required, attach_feature_guard, format_user, get_current_user, json_error, query_filters

radio_morning_report_bp = Blueprint("radio_morning_report", __name__)
attach_feature_guard(radio_morning_report_bp, "/radio-morning-report")


@radio_morning_report_bp.route("/radio-morning-report")
@admin_required
def radio_morning_report_page():
    return render_template(
        "radio_module.html",
        user=format_user(get_current_user()),
        module_title="Radio Morning Report",
        module_subtitle="Daily RF/NOC summary across capacity, mobility, sleeping cells, group health, alarms, IRAT borders, CM audit, and change impact.",
        module_kind="radio-morning-report",
        api_url="/api/radio-morning-report/issues",
        default_technology="all",
    )


@radio_morning_report_bp.route("/api/radio-morning-report/issues")
@admin_required
def radio_morning_report_issues():
    f = query_filters(default_limit=100)
    try:
        payload = radio_morning_report(area=f["area"], vendor=f["vendor"], technology=f["technology"], limit=f["limit"])
        rows = filter_rows(payload.get("issues") or [], severity=f["severity"], search=f["search"])
        return jsonify({"success": True, **payload, "summary": summarize(rows), "issues": rows})
    except Exception as exc:
        return json_error(exc)

