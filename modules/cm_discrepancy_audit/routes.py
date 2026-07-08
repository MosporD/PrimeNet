"""CM Discrepancy Audit — workbook-style UI + JSON APIs over stored runs."""

from __future__ import annotations

import os
from datetime import datetime

from flask import Blueprint, jsonify, render_template, request, send_file

from core.radio.web import admin_required, format_user, get_current_user, json_error
from database_enhanced import log_activity

from core.cm_discrepancy import store
from core.cm_discrepancy.audit import normalize_vendor, workbook_path
from core.cm_discrepancy.scheduler import get_state, start_cm_discrepancy_async

cm_discrepancy_audit_bp = Blueprint(
    'cm_discrepancy_audit', __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/cm_discrepancy_audit/static',
)


def _parse_run_date(raw: str) -> str:
    """Accept ISO (2026-07-08) or legacy label (08_07_2026); return ISO."""
    token = (raw or '').strip()
    for fmt in ('%Y-%m-%d', '%d_%m_%Y'):
        try:
            return datetime.strptime(token, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    raise ValueError(f'Invalid run date: {raw!r} (expected YYYY-MM-DD or DD_MM_YYYY)')


def _vendor_arg() -> str:
    return normalize_vendor(request.args.get('vendor') or 'huawei')


def _find_run_or_404(conn, run_date: str, vendor: str):
    run = store.find_run(conn, vendor=vendor, run_date=run_date)
    if not run:
        return None
    return run


@cm_discrepancy_audit_bp.route('/cm-discrepancy-audit')
@admin_required
def cm_discrepancy_audit_page():
    return render_template(
        'cm_discrepancy_audit.html',
        user=format_user(get_current_user()),
    )


@cm_discrepancy_audit_bp.route('/api/cm-discrepancy-audit/runs')
@admin_required
def api_runs():
    try:
        vendor = (request.args.get('vendor') or '').strip().lower()
        if vendor:
            vendor = normalize_vendor(vendor)
        limit = min(365, max(1, int(request.args.get('limit') or 60)))
        conn = store.connect()
        try:
            runs = store.list_runs(conn, vendor=vendor, limit=limit)
        finally:
            conn.close()
        for run in runs:
            try:
                run['date_label'] = datetime.strptime(
                    str(run['run_date']), '%Y-%m-%d'
                ).strftime('%d_%m_%Y')
            except ValueError:
                run['date_label'] = str(run['run_date'])
        return jsonify({'success': True, 'items': runs, 'state': get_state()})
    except Exception as exc:
        return json_error(exc)


@cm_discrepancy_audit_bp.route('/api/cm-discrepancy-audit/runs/<run_date>/summary')
@admin_required
def api_summary(run_date: str):
    try:
        vendor = _vendor_arg()
        iso_date = _parse_run_date(run_date)
        conn = store.connect()
        try:
            run = _find_run_or_404(conn, iso_date, vendor)
            if not run:
                return jsonify({'success': False, 'error': 'Run not found'}), 404
            rows = store.get_summary(conn, int(run['id']))
        finally:
            conn.close()
        return jsonify({'success': True, 'run': run, 'items': rows})
    except ValueError as exc:
        return json_error(exc, 400)
    except Exception as exc:
        return json_error(exc)


@cm_discrepancy_audit_bp.route('/api/cm-discrepancy-audit/runs/<run_date>/master')
@admin_required
def api_master(run_date: str):
    try:
        vendor = _vendor_arg()
        iso_date = _parse_run_date(run_date)
        mo = (request.args.get('mo') or '').strip()
        conn = store.connect()
        try:
            run = _find_run_or_404(conn, iso_date, vendor)
            if not run:
                return jsonify({'success': False, 'error': 'Run not found'}), 404
            rows = store.get_master(conn, int(run['id']), mo=mo)
        finally:
            conn.close()
        return jsonify({'success': True, 'run': run, 'items': rows})
    except ValueError as exc:
        return json_error(exc, 400)
    except Exception as exc:
        return json_error(exc)


@cm_discrepancy_audit_bp.route('/api/cm-discrepancy-audit/runs/<run_date>/detail')
@admin_required
def api_detail(run_date: str):
    try:
        vendor = _vendor_arg()
        iso_date = _parse_run_date(run_date)
        mo = (request.args.get('mo') or '').strip()
        flag = (request.args.get('flag') or '').strip().lower()
        if flag and flag not in ('mismatched', 'added', 'removed'):
            return jsonify({'success': False, 'error': 'Invalid flag filter'}), 400
        page = max(1, int(request.args.get('page') or 1))
        page_size = min(500, max(10, int(request.args.get('page_size') or 100)))
        conn = store.connect()
        try:
            run = _find_run_or_404(conn, iso_date, vendor)
            if not run:
                return jsonify({'success': False, 'error': 'Run not found'}), 404
            payload = store.get_detail(
                conn, int(run['id']), mo=mo, flag=flag, page=page, page_size=page_size
            )
            mos = store.list_detail_mos(conn, int(run['id']))
        finally:
            conn.close()
        return jsonify({'success': True, 'run': run, 'mos': mos, **payload})
    except ValueError as exc:
        return json_error(exc, 400)
    except Exception as exc:
        return json_error(exc)


@cm_discrepancy_audit_bp.route('/api/cm-discrepancy-audit/trend')
@admin_required
def api_trend():
    try:
        vendor = (request.args.get('vendor') or '').strip().lower()
        if vendor:
            vendor = normalize_vendor(vendor)
        limit = min(365, max(1, int(request.args.get('limit') or 90)))
        conn = store.connect()
        try:
            rows = store.get_trend(conn, vendor=vendor, limit=limit)
        finally:
            conn.close()
        return jsonify({'success': True, 'items': rows})
    except Exception as exc:
        return json_error(exc)


@cm_discrepancy_audit_bp.route('/api/cm-discrepancy-audit/runs/<run_date>/download')
@admin_required
def api_download(run_date: str):
    try:
        vendor = _vendor_arg()
        iso_date = _parse_run_date(run_date)
        conn = store.connect()
        try:
            run = _find_run_or_404(conn, iso_date, vendor)
            if not run:
                return jsonify({'success': False, 'error': 'Run not found'}), 404
            path = workbook_path(vendor, iso_date)
            if not os.path.isfile(path):
                from core.cm_discrepancy.excel_export import export_run_workbook

                path = export_run_workbook(conn, int(run['id']))
        finally:
            conn.close()
        user = get_current_user()
        if user:
            log_activity(
                user.get('id') if isinstance(user, dict) else user[0],
                'cm_discrepancy_download',
                f'Downloaded {vendor} discrepancy workbook for {iso_date}',
            )
        return send_file(
            path,
            as_attachment=True,
            download_name=os.path.basename(path),
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
    except ValueError as exc:
        return json_error(exc, 400)
    except Exception as exc:
        return json_error(exc)


@cm_discrepancy_audit_bp.route('/api/cm-discrepancy-audit/run', methods=['POST'])
@admin_required
def api_trigger_run():
    try:
        data = request.get_json(silent=True) or {}
        vendor = (data.get('vendor') or '').strip().lower()
        if vendor:
            vendor = normalize_vendor(vendor)
        mo_subset = data.get('mo_subset') or []
        if isinstance(mo_subset, str):
            mo_subset = [m.strip() for m in mo_subset.split(',') if m.strip()]
        result = start_cm_discrepancy_async(vendor, mo_subset=mo_subset or None)
        user = get_current_user()
        if user and result.get('started'):
            log_activity(
                user.get('id') if isinstance(user, dict) else user[0],
                'cm_discrepancy_run',
                f'Triggered CM discrepancy audit ({vendor or "both vendors"})',
            )
        status = 200 if result.get('started') else 409
        return jsonify({'success': bool(result.get('started')), **result}), status
    except ValueError as exc:
        return json_error(exc, 400)
    except Exception as exc:
        return json_error(exc)


@cm_discrepancy_audit_bp.route('/api/cm-discrepancy-audit/status')
@admin_required
def api_status():
    return jsonify({'success': True, 'state': get_state()})
