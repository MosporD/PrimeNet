"""Huawei Load Balancing — Network Balance NOK sectors → CellMLB proposals → Excel/MML."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from flask import Blueprint, Response, jsonify, render_template, request

from core.cm_extractor.config import huawei_configured
from core.radio.web import admin_required, format_user, get_current_user

from modules.nokia_load_balancing.balance_data import (
    balance_configured,
    balance_root,
    list_nok_sectors,
    sectors_from_balance,
)
from modules.nokia_load_balancing.balance_store import (
    daily_status_summary,
    list_snapshots_in_range,
    snapshot_inventory,
)
from modules.nokia_load_balancing.ingest_job import ingest_status, run_balance_ingest

from . import config
from .logic import analyze_sectors, load_preview, preview_excel, preview_mml, save_preview

huawei_load_balancing_bp = Blueprint(
    "huawei_load_balancing",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/huawei-load-balancing/static",
)


@huawei_load_balancing_bp.before_request
def _guard_huawei_load_balancing_access():
    from core.module_access import module_access_before_request
    return module_access_before_request("/huawei-load-balancing")


def _parse_date(value: str | None) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None


def _parse_date_only(value: str | None) -> date | None:
    parsed = _parse_date(value)
    return parsed.date() if parsed else None


@huawei_load_balancing_bp.route("/huawei-load-balancing")
@admin_required
def huawei_load_balancing_page():
    return render_template(
        "huawei_load_balancing.html",
        user=format_user(get_current_user()),
        huawei_configured=huawei_configured(),
        balance_configured=balance_configured(),
        balance_path=str(balance_root()),
    )


@huawei_load_balancing_bp.route("/api/huawei-load-balancing/nok-sectors")
@admin_required
def huawei_nok_sectors():
    payload = list_nok_sectors(_parse_date(request.args.get("date")), vendor="Huawei")
    status = 200 if payload.get("success") else 503
    return jsonify(payload), status


@huawei_load_balancing_bp.route("/api/huawei-load-balancing/ingest-status")
@admin_required
def huawei_ingest_status():
    return jsonify({"success": True, **ingest_status()})


@huawei_load_balancing_bp.route("/api/huawei-load-balancing/ingest", methods=["POST"])
@admin_required
def huawei_ingest():
    body = request.get_json(silent=True) or {}
    force = bool(body.get("force"))
    lookback = body.get("lookback_days")
    try:
        lookback_days = int(lookback) if lookback is not None else None
    except (TypeError, ValueError):
        lookback_days = None
    summary = run_balance_ingest(
        lookback_days=lookback_days,
        force=force,
        vendors=["huawei"],
    )
    status = 200 if summary.get("success") else 500
    return jsonify(summary), status


@huawei_load_balancing_bp.route("/api/huawei-load-balancing/snapshots")
@admin_required
def huawei_snapshots():
    end_date = _parse_date_only(request.args.get("end")) or date.today()
    days = max(1, min(int(request.args.get("days") or 14), config.TREND_MAX_DAYS))
    start_date = end_date - timedelta(days=days - 1)
    snapshots = list_snapshots_in_range(start_date, end_date, vendor="huawei")
    return jsonify({
        "success": True,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "snapshots": snapshots,
        "inventory": snapshot_inventory(),
        "daily_summary": daily_status_summary(start_date, end_date, vendor="huawei"),
    })


@huawei_load_balancing_bp.route("/api/huawei-load-balancing/analyze", methods=["POST"])
@admin_required
def huawei_analyze():
    user = get_current_user()
    body = request.get_json(silent=True) or {}
    sector_ids = body.get("sectors") or []
    if isinstance(sector_ids, str):
        sector_ids = [s.strip() for s in sector_ids.replace(",", "\n").splitlines() if s.strip()]
    if not sector_ids:
        return jsonify({"success": False, "error": "Select or enter at least one sector."}), 400

    sectors, lookup_errors, source_file = sectors_from_balance(
        sector_ids,
        _parse_date(body.get("date")),
        vendor="Huawei",
    )
    if not sectors:
        return jsonify({
            "success": False,
            "errors": lookup_errors or ["Could not load sector throughput from Network Balance."],
        }), 400

    result = analyze_sectors(sectors)
    all_errors = lookup_errors + (result.get("errors") or [])
    if not result.get("success"):
        return jsonify({
            "success": False,
            "errors": all_errors or ["Analysis failed"],
            "warnings": result.get("warnings") or [],
            "sector_count": len(sectors),
            "source_file": source_file,
        }), 400

    token = save_preview(user["username"], {
        "source_file": source_file,
        "sectors": sectors,
        "rows": result.get("rows") or [],
        "review_rows": result.get("review_rows") or [],
        "changes": result.get("changes") or [],
        "warnings": result.get("warnings") or [],
    })
    return jsonify({
        "success": True,
        "token": token,
        "source_file": source_file,
        "sector_count": len(sectors),
        "rows": result.get("rows") or [],
        "review_rows": result.get("review_rows") or [],
        "change_count": result.get("change_count") or 0,
        "review_row_count": result.get("review_row_count") or 0,
        "summary": result.get("summary") or {},
        "site_ids": result.get("site_ids") or [],
        "warnings": (result.get("warnings") or []) + lookup_errors,
        "errors": all_errors,
        "oss_push_enabled": False,
    })


@huawei_load_balancing_bp.route("/api/huawei-load-balancing/download-excel", methods=["POST"])
@admin_required
def huawei_download_excel():
    user = get_current_user()
    body = request.get_json(silent=True) or {}
    token = (body.get("token") or "").strip()
    if not token:
        return jsonify({"success": False, "error": "Missing preview token. Run Analyze first."}), 400
    try:
        payload = preview_excel(user["username"], token)
    except FileNotFoundError:
        return jsonify({"success": False, "error": "Preview not found or expired."}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except ImportError:
        return jsonify({"success": False, "error": "openpyxl is required for Excel export."}), 500
    filename = f"huawei_lb_{token[:8]}.xlsx"
    return Response(
        payload,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@huawei_load_balancing_bp.route("/api/huawei-load-balancing/download-mml", methods=["POST"])
@admin_required
def huawei_download_mml():
    user = get_current_user()
    body = request.get_json(silent=True) or {}
    token = (body.get("token") or "").strip()
    if not token:
        return jsonify({"success": False, "error": "Missing preview token. Run Analyze first."}), 400
    try:
        text = preview_mml(user["username"], token)
    except FileNotFoundError:
        return jsonify({"success": False, "error": "Preview not found or expired."}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    filename = f"huawei_lb_{token[:8]}.txt"
    return Response(
        text,
        mimetype="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
