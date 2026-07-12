from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request, send_file

from core.cm_extractor.config import huawei_configured, nokia_configured
from core.cm_extractor.huawei_client import HuaweiCmError
from core.cm_extractor.nokia_client import NokiaCmError
from core.cm_extractor.site_catalog import list_huawei_areas, list_nokia_inventory_areas
from core.radio.cm_live import query_live_parameter_status
from core.radio.web import format_user, get_current_user, json_error, login_required
from modules.cm_parameter_audit.cache import get_export_payload, store_export_payload
from modules.cm_parameter_audit.export import build_audit_workbook

cm_parameter_audit_bp = Blueprint(
    "cm_parameter_audit",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/cm_parameter_audit/static",
)


def _json_body() -> dict:
    return request.get_json(silent=True) or {}


def _user_id(user) -> str:
    if not user:
        return ''
    if isinstance(user, dict):
        return str(user.get('id') or '')
    return str(user[0])


@cm_parameter_audit_bp.route("/cm-parameter-audit")
@login_required
def cm_parameter_audit_page():
    return render_template(
        "cm_parameter_audit.html",
        user=format_user(get_current_user()),
        nokia_configured=nokia_configured(),
        huawei_configured=huawei_configured(),
        huawei_enabled=huawei_configured(),
    )


@cm_parameter_audit_bp.route("/api/cm-parameter-audit/areas")
@login_required
def cm_parameter_audit_areas():
    vendor = (request.args.get("vendor") or "nokia").strip().lower()
    scope_level = (request.args.get("scope_level") or "MRBTS").strip().upper()
    try:
        if vendor == "huawei":
            items = list_huawei_areas(scope_level=scope_level)
        else:
            items = list_nokia_inventory_areas(scope_level=scope_level)
        return jsonify({"success": True, "vendor": vendor, "scope_level": scope_level, "areas": items})
    except Exception as exc:
        return json_error(exc)


@cm_parameter_audit_bp.route("/api/cm-parameter-audit/live", methods=["POST"])
@login_required
def cm_parameter_audit_live():
    data = _json_body()
    user = get_current_user()
    try:
        site_ids = data.get("site_ids")
        if isinstance(site_ids, str):
            site_ids = [s.strip() for s in site_ids.split(",") if s.strip()]
        payload = query_live_parameter_status(
            vendor=str(data.get("vendor") or "nokia"),
            scope_level=str(data.get("scope_level") or ""),
            mo_class=str(data.get("mo_class") or data.get("mo_class_id") or ""),
            parameter=str(data.get("parameter") or ""),
            conf_id=int(data.get("conf_id") or 1),
            area=str(data.get("area") or "all"),
            site_ids=site_ids if isinstance(site_ids, list) else None,
            max_nes=int(data.get("max_nes") or 2000),
            mo_version=str(data.get("mo_version") or data.get("version") or ""),
        )
        export_id = store_export_payload(payload, user_id=_user_id(user))
        api_summary = dict(payload.get("summary") or {})
        api_summary.pop("value_distribution_all", None)
        return jsonify({
            "success": True,
            "export_id": export_id,
            **{**payload, "summary": api_summary},
        })
    except (NokiaCmError, HuaweiCmError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return json_error(exc)


@cm_parameter_audit_bp.route("/api/cm-parameter-audit/export", methods=["POST"])
@cm_parameter_audit_bp.route("/api/cm-parameter-audit/export/<export_id>", methods=["GET"])
@login_required
def cm_parameter_audit_export(export_id: str | None = None):
    """Export value distribution and network status into one Excel workbook."""
    user = get_current_user()
    try:
        if export_id:
            token = export_id.strip()
        else:
            data = _json_body()
            token = str(data.get("export_id") or "").strip()

        payload = get_export_payload(token, user_id=_user_id(user)) if token else None
        if payload is None:
            return jsonify({
                "success": False,
                "error": "Export session expired or not found. Run the live scan again.",
            }), 404
        if not payload.get("rows") and not (
            (payload.get("summary") or {}).get("value_distribution")
            or (payload.get("summary") or {}).get("value_distribution_all")
        ):
            return jsonify({
                "success": False,
                "error": "Nothing to export. Run a live scan first.",
            }), 400
        workbook, filename = build_audit_workbook(payload)
        return send_file(
            workbook,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception as exc:
        return json_error(exc)
