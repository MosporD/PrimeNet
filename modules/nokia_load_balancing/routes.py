"""Nokia Load Balancing — admin module for AMLE parameter proposals."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from flask import Blueprint, Response, jsonify, render_template, request

from core.cm_extractor.config import nokia_configured, nokia_export_ssh_settings
from core.cm_extractor.nokia_excel_reimport import CONFIRMATION_PHRASE
from core.radio.web import admin_required, format_user, get_current_user

from . import config
from .balance_data import balance_configured, balance_root, list_nok_sectors, sectors_from_balance
from .balance_store import (
    daily_status_summary,
    list_snapshots_in_range,
    sector_status_trend,
    snapshot_inventory,
)
from .ingest_job import ingest_status, run_balance_ingest
from .logic import analyze_sectors, load_preview, preview_backup_xml, preview_xml, save_preview
from .push import apply_preview_to_oss

nokia_load_balancing_bp = Blueprint(
    "nokia_load_balancing",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/nokia-load-balancing/static",
)


@nokia_load_balancing_bp.before_request
def _guard_nokia_load_balancing_access():
    from core.module_access import module_access_before_request
    return module_access_before_request("/nokia-load-balancing")


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


def _parse_date_range(start: str | None, end: str | None) -> tuple[date, date] | None:
    start_date = _parse_date_only(start)
    end_date = _parse_date_only(end)
    if not start_date or not end_date:
        return None
    span = abs((end_date - start_date).days) + 1
    if span > config.TREND_MAX_DAYS:
        raise ValueError(f"Date range cannot exceed {config.TREND_MAX_DAYS} days.")
    return start_date, end_date


@nokia_load_balancing_bp.route("/nokia-load-balancing")
@admin_required
def nokia_load_balancing_page():
    oss_push_configured = bool(nokia_configured() and nokia_export_ssh_settings().get("configured"))
    return render_template(
        "nokia_load_balancing.html",
        user=format_user(get_current_user()),
        nokia_configured=nokia_configured(),
        oss_push_configured=oss_push_configured,
        balance_configured=balance_configured(),
        balance_path=str(balance_root()),
        apply_confirmation=CONFIRMATION_PHRASE,
    )


@nokia_load_balancing_bp.route("/api/nokia-load-balancing/nok-sectors")
@admin_required
def nokia_nok_sectors():
    date = _parse_date(request.args.get("date"))
    payload = list_nok_sectors(date)
    status = 200 if payload.get("success") else 503
    return jsonify(payload), status


@nokia_load_balancing_bp.route("/api/nokia-load-balancing/ingest-status")
@admin_required
def nokia_ingest_status():
    return jsonify({"success": True, **ingest_status()})


@nokia_load_balancing_bp.route("/api/nokia-load-balancing/ingest", methods=["POST"])
@admin_required
def nokia_ingest():
    body = request.get_json(silent=True) or {}
    force = bool(body.get("force"))
    lookback = body.get("lookback_days")
    try:
        lookback_days = int(lookback) if lookback is not None else None
    except (TypeError, ValueError):
        lookback_days = None

    vendors = body.get("vendors")
    if isinstance(vendors, str):
        vendors = [v.strip().lower() for v in vendors.split(",") if v.strip()]
    elif isinstance(vendors, list):
        vendors = [str(v).strip().lower() for v in vendors if str(v).strip()]
    else:
        vendors = None

    start_date = _parse_date_only(body.get("start_date"))
    end_date = _parse_date_only(body.get("end_date"))
    if start_date and end_date:
        span = abs((end_date - start_date).days) + 1
        if span > config.TREND_MAX_DAYS:
            return jsonify({
                "success": False,
                "errors": [f"Date range cannot exceed {config.TREND_MAX_DAYS} days."],
            }), 400

    summary = run_balance_ingest(
        lookback_days=lookback_days,
        start_date=start_date,
        end_date=end_date,
        force=force,
        vendors=vendors,
    )
    status = 200 if summary.get("success") else 500
    return jsonify(summary), status


@nokia_load_balancing_bp.route("/api/nokia-load-balancing/snapshots")
@admin_required
def nokia_snapshots():
    try:
        if request.args.get("start") and request.args.get("end"):
            parsed = _parse_date_range(request.args.get("start"), request.args.get("end"))
            if not parsed:
                return jsonify({"success": False, "error": "Invalid start/end date."}), 400
            start_date, end_date = parsed
        else:
            end_date = _parse_date_only(request.args.get("end")) or date.today()
            days = int(request.args.get("days") or 14)
            days = max(1, min(days, config.TREND_MAX_DAYS))
            start_date = end_date - timedelta(days=days - 1)

        vendor = (request.args.get("vendor") or "").strip().lower() or None
        snapshots = list_snapshots_in_range(start_date, end_date, vendor=vendor)
        return jsonify({
            "success": True,
            "start_date": min(start_date, end_date).isoformat(),
            "end_date": max(start_date, end_date).isoformat(),
            "snapshots": snapshots,
            "inventory": snapshot_inventory(),
        })
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@nokia_load_balancing_bp.route("/api/nokia-load-balancing/trend")
@admin_required
def nokia_trend():
    try:
        parsed = _parse_date_range(request.args.get("start"), request.args.get("end"))
        if not parsed:
            return jsonify({"success": False, "error": "start and end dates are required."}), 400
        start_date, end_date = parsed

        vendor = (request.args.get("vendor") or "nokia").strip().lower()
        status_filter = (request.args.get("status") or config.NOK_STATUS_VALUE).strip().upper()

        sector_ids = request.args.get("sectors") or request.args.get("sector_ids") or ""
        if isinstance(sector_ids, str):
            sector_ids = [s.strip() for s in sector_ids.replace(",", "\n").splitlines() if s.strip()]
        else:
            sector_ids = [str(s).strip() for s in (sector_ids or []) if str(s).strip()]

        limit = int(request.args.get("limit") or 500)
        limit = max(1, min(limit, 2000))

        summary = daily_status_summary(start_date, end_date, vendor=vendor or None)
        trend = sector_status_trend(
            start_date,
            end_date,
            vendor=vendor,
            sector_ids=sector_ids or None,
            status_filter=status_filter,
            limit=limit,
        )
        return jsonify({
            "success": True,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "vendor": vendor,
            "status_filter": status_filter,
            "daily_summary": summary,
            "trend": trend,
        })
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@nokia_load_balancing_bp.route("/api/nokia-load-balancing/analyze", methods=["POST"])
@admin_required
def nokia_analyze():
    user = get_current_user()
    body = request.get_json(silent=True) or {}
    sector_ids = body.get("sectors") or []
    if isinstance(sector_ids, str):
        sector_ids = [s.strip() for s in sector_ids.replace(",", "\n").splitlines() if s.strip()]
    if not sector_ids:
        return jsonify({"success": False, "error": "Select or enter at least one sector."}), 400

    date = _parse_date(body.get("date"))
    sectors, lookup_errors, source_file = sectors_from_balance(sector_ids, date)
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
        "amle_row_count": result.get("amle_row_count") or 0,
        "site_ids": result.get("site_ids") or [],
        "warnings": (result.get("warnings") or []) + lookup_errors,
        "errors": all_errors,
        "oss_push_configured": bool(nokia_configured() and nokia_export_ssh_settings().get("configured")),
    })


@nokia_load_balancing_bp.route("/api/nokia-load-balancing/download-xml", methods=["POST"])
@admin_required
def nokia_download_xml():
    user = get_current_user()
    body = request.get_json(silent=True) or {}
    token = (body.get("token") or "").strip()
    if not token:
        return jsonify({"success": False, "error": "Missing preview token. Run Analyze first."}), 400

    try:
        xml_text = preview_xml(user["username"], token)
    except FileNotFoundError:
        return jsonify({"success": False, "error": "Preview not found or expired."}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    filename = f"nokia_lb_{token[:8]}.xml"
    return Response(
        xml_text,
        mimetype="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@nokia_load_balancing_bp.route("/api/nokia-load-balancing/download-backup-xml", methods=["POST"])
@admin_required
def nokia_download_backup_xml():
    user = get_current_user()
    body = request.get_json(silent=True) or {}
    token = (body.get("token") or "").strip()
    if not token:
        return jsonify({"success": False, "error": "Missing preview token. Run Analyze first."}), 400

    try:
        xml_text = preview_backup_xml(user["username"], token)
    except FileNotFoundError:
        return jsonify({"success": False, "error": "Preview not found or expired."}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    filename = f"nokia_lb_backup_{token[:8]}.xml"
    return Response(
        xml_text,
        mimetype="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@nokia_load_balancing_bp.route("/api/nokia-load-balancing/download-excel", methods=["POST"])
@admin_required
def nokia_download_excel():
    user = get_current_user()
    body = request.get_json(silent=True) or {}
    token = (body.get("token") or "").strip()
    if not token:
        return jsonify({"success": False, "error": "Missing preview token. Run Analyze first."}), 400

    from .export import build_review_excel

    try:
        preview = load_preview(user["username"], token)
    except FileNotFoundError:
        return jsonify({"success": False, "error": "Preview not found or expired."}), 404

    review_rows = preview.get("review_rows") or preview.get("rows") or []
    if not review_rows:
        return jsonify({"success": False, "error": "No AMLE review rows in preview."}), 400

    try:
        payload = build_review_excel(review_rows, config_gaps=preview.get("warnings") or [])
    except ImportError:
        return jsonify({"success": False, "error": "openpyxl is required for Excel export."}), 500

    filename = f"nokia_lb_{token[:8]}.xlsx"
    return Response(
        payload,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@nokia_load_balancing_bp.route("/api/nokia-load-balancing/apply", methods=["POST"])
@admin_required
def nokia_apply_to_oss():
    """Upload RAML plan to NetAct and trigger CM Operations actualImport (admin only)."""
    user = get_current_user()
    body = request.get_json(silent=True) or {}
    token = (body.get("token") or "").strip()
    confirmation = (body.get("confirmation") or "").strip()
    if not token:
        return jsonify({"success": False, "error": "Missing preview token. Run Analyze first."}), 400
    if confirmation != CONFIRMATION_PHRASE:
        return jsonify({
            "success": False,
            "error": f"Type {CONFIRMATION_PHRASE!r} to apply these changes to the network.",
        }), 400
    if not nokia_export_ssh_settings().get("configured"):
        return jsonify({
            "success": False,
            "error": "OSS push is not configured. Set NOKIA_CM_SSH_* (or NOKIA_PM_*) and reimport path in .env.",
        }), 503

    wait = str(body.get("wait") or "").strip().lower() in ("1", "true", "yes", "on")
    try:
        result = apply_preview_to_oss(user["username"], token, wait=wait)
    except FileNotFoundError:
        return jsonify({"success": False, "error": "Preview not found or expired."}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": f"OSS apply failed: {exc}"}), 500

    return jsonify({"success": True, **result})
