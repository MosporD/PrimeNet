from __future__ import annotations

from flask import Blueprint, jsonify, render_template

from core.radio.insights import cm_parameter_audit
from core.radio.scoring import filter_rows, summarize
from core.radio.web import admin_required, format_user, get_current_user, json_error, query_filters

cm_parameter_audit_bp = Blueprint("cm_parameter_audit", __name__)


@cm_parameter_audit_bp.route("/cm-parameter-audit")
@admin_required
def cm_parameter_audit_page():
    return render_template(
        "radio_module.html",
        user=format_user(get_current_user()),
        module_title="CM Parameter Audit",
        module_subtitle="Golden-rule exceptions from normalized CM snapshots and parameter audit recipes.",
        module_kind="cm-parameter-audit",
        api_url="/api/cm-parameter-audit/issues",
        default_technology="all",
    )


@cm_parameter_audit_bp.route("/api/cm-parameter-audit/issues")
@admin_required
def cm_parameter_audit_issues():
    f = query_filters(default_limit=500)
    try:
        payload = cm_parameter_audit(vendor=f["vendor"], technology=f["technology"], limit=f["limit"])
        rows = filter_rows(payload.get("issues") or [], area=f["area"], severity=f["severity"], search=f["search"])
        note = None
        if not payload.get("store", {}).get("rows"):
            note = "No CM snapshots are stored yet. Run or import normalized CM snapshots to enable audit results."
        return jsonify({"success": True, **payload, "summary": summarize(rows), "issues": rows, "note": note})
    except Exception as exc:
        return json_error(exc)

