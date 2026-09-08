from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request, send_file

from core.cm_extractor.config import huawei_configured, nokia_configured
from core.cm_extractor.huawei_client import HuaweiCmError
from core.cm_extractor.nokia_client import NokiaCmError
from core.cm_extractor.site_catalog import list_huawei_areas, list_nokia_inventory_areas
from core.radio.cm_live import query_live_parameter_status
from core.radio import cm_store
from core.site_area import list_canonical_areas
from core.radio.web import _role, format_user, get_current_user, json_error, login_required
from modules.cm_parameter_audit.version import MODULE_VERSION_LABEL
from modules.cm_parameter_audit.cache import get_export_payload, store_export_payload
from modules.cm_parameter_audit.export import build_audit_workbook
from pathlib import Path

from sync_config import PROJECT_ROOT

_AUDIT_EXPORTS_DIR = Path(PROJECT_ROOT) / 'uploads' / 'cm_parameter_audit' / 'exports'

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


def _admin_only():
    if _role(get_current_user()) != 'admin':
        return jsonify({"success": False, "error": "Admin only."}), 403
    return None


def _slim_audit_payload(payload: dict) -> dict:
    """Drop the object×parameter matrix from JSON; Excel is written separately."""
    slim = dict(payload)
    slim.pop("object_matrix", None)
    slim["rows"] = slim.get("rows") or []
    summary = dict(slim.get("summary") or {})
    summary.pop("value_distribution_all", None)
    slim["summary"] = summary
    trimmed = []
    for item in slim.get("parameter_summaries") or []:
        copy = dict(item)
        copy.pop("value_distribution_all", None)
        trimmed.append(copy)
    if trimmed:
        slim["parameter_summaries"] = trimmed
    return slim


@cm_parameter_audit_bp.route("/cm-parameter-audit")
@login_required
def cm_parameter_audit_page():
    return render_template(
        "cm_parameter_audit.html",
        user=format_user(get_current_user()),
        nokia_configured=nokia_configured(),
        huawei_configured=huawei_configured(),
        huawei_enabled=huawei_configured(),
        module_version=MODULE_VERSION_LABEL,
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
        entire_mo = bool(data.get("entire_mo"))
        if str(data.get("audit_mode") or "").strip().lower() == "mo":
            entire_mo = True
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
            entire_mo=entire_mo,
        )
        workbook_bytes = None
        filename = None
        if payload.get("audit_mode") == "mo":
            workbook_bytes, filename = build_audit_workbook(payload)
            payload = _slim_audit_payload(payload)
        export_id = store_export_payload(payload, user_id=_user_id(user))
        if workbook_bytes is not None and export_id:
            _AUDIT_EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
            (_AUDIT_EXPORTS_DIR / f'{export_id}.xlsx').write_bytes(workbook_bytes.getvalue())
        api_payload = dict(payload)
        api_summary = dict(api_payload.get("summary") or {})
        api_summary.pop("value_distribution_all", None)
        api_payload["summary"] = api_summary
        return jsonify({
            "success": True,
            "export_id": export_id,
            **api_payload,
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
        saved_workbook = _AUDIT_EXPORTS_DIR / f'{token}.xlsx' if token else None
        if saved_workbook and saved_workbook.is_file():
            return send_file(
                saved_workbook,
                as_attachment=True,
                download_name=saved_workbook.name,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
        if payload is None:
            return jsonify({
                "success": False,
                "error": "Export session expired or not found. Run the live scan again.",
            }), 404
        has_mo = payload.get("audit_mode") == "mo" and payload.get("parameter_summaries")
        has_param = payload.get("rows") or (
            (payload.get("summary") or {}).get("value_distribution")
            or (payload.get("summary") or {}).get("value_distribution_all")
        )
        if not has_mo and not has_param:
            return jsonify({
                "success": False,
                "error": "Nothing to export. Run a live scan first.",
            }), 400
        workbook, filename = build_audit_workbook(payload)
        if token:
            _AUDIT_EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
            saved_workbook = _AUDIT_EXPORTS_DIR / f'{token}.xlsx'
            saved_workbook.write_bytes(workbook.getvalue())
        return send_file(
            workbook,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception as exc:
        return json_error(exc)


@cm_parameter_audit_bp.route("/api/cm-parameter-audit/rules", methods=["GET"])
@login_required
def cm_parameter_audit_rules():
    denied = _admin_only()
    if denied:
        return denied
    try:
        return jsonify({
            "success": True,
            "rules": cm_store.list_rules(include_disabled=True),
            "areas": list_canonical_areas(),
        })
    except Exception as exc:
        return json_error(exc)


@cm_parameter_audit_bp.route("/api/cm-parameter-audit/rules", methods=["POST"])
@login_required
def cm_parameter_audit_upsert_rule():
    denied = _admin_only()
    if denied:
        return denied
    data = _json_body()
    user = get_current_user()
    actor = ""
    if isinstance(user, dict):
        actor = str(user.get("username") or user.get("id") or "")
    if not str(data.get("parameter") or "").strip():
        return jsonify({"success": False, "error": "parameter is required"}), 400
    try:
        rule = cm_store.upsert_rule(data, actor=actor)
        return jsonify({"success": True, "rule": rule})
    except Exception as exc:
        return json_error(exc)


@cm_parameter_audit_bp.route("/api/cm-parameter-audit/rules/<rule_id>/approve", methods=["POST"])
@login_required
def cm_parameter_audit_approve_rule(rule_id: str):
    denied = _admin_only()
    if denied:
        return denied
    data = _json_body()
    user = get_current_user()
    actor = ""
    if isinstance(user, dict):
        actor = str(user.get("username") or user.get("id") or "")
    try:
        rule = cm_store.approve_rule(rule_id, actor=actor, baseline=str(data.get("baseline") or ""))
        if not rule:
            return jsonify({"success": False, "error": "Rule not found"}), 404
        return jsonify({"success": True, "rule": rule})
    except Exception as exc:
        return json_error(exc)
