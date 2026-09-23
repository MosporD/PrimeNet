"""Configuration Dashboard routes — Hardware (RMOD_R) + WNCELG tabs."""

from __future__ import annotations

from functools import wraps

from flask import Blueprint, jsonify, redirect, render_template, request, send_file, url_for

from core.cm_extractor.config import nokia_configured
from core.platform.session import get_session_token
from database_enhanced import get_user_by_session, log_activity
from modules.configuration_dashboard import wncelg_logic
from modules.configuration_dashboard import wncelg_store
from modules.configuration_dashboard.export import build_wncelg_workbook
from modules.rru_inventory import logic as rru_logic
from modules.rru_inventory import store as rru_store
from modules.rru_inventory.export import build_rmod_workbook

configuration_dashboard_bp = Blueprint(
    'configuration_dashboard',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/configuration-dashboard/static',
)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        session_token = get_session_token()
        if not session_token:
            return redirect(url_for('auth.login_page'))
        user = get_user_by_session(session_token)
        if not user:
            return redirect(url_for('auth.login_page'))
        request.current_user = user
        return f(*args, **kwargs)
    return decorated


def get_current_user():
    session_token = get_session_token()
    if session_token:
        return get_user_by_session(session_token)
    return None


def format_user_data(user):
    if not user:
        return None
    if isinstance(user, dict):
        return {
            'username': user.get('username'),
            'email': user.get('email'),
            'role': user.get('role'),
            'id': user.get('id'),
        }
    return {
        'username': user[1],
        'email': user[2],
        'role': user[6],
        'id': user[0],
    }


def _username(user) -> str:
    if isinstance(user, dict):
        return str(user.get('username') or '').strip()
    return str(user[1] or '').strip()


@configuration_dashboard_bp.route('/configuration-dashboard')
@login_required
def configuration_dashboard_page():
    user = format_user_data(get_current_user())
    rmod_meta = rru_store.get_build_meta()
    wncelg_meta = wncelg_store.get_build_meta()
    tab = (request.args.get('tab') or 'hardware').strip().lower()
    if tab not in ('hardware', 'wncelg'):
        tab = 'hardware'
    return render_template(
        'configuration_dashboard.html',
        user=user,
        nokia_ready=nokia_configured(),
        active_tab=tab,
        hardware_snapshot_ready=bool(rmod_meta and int(rmod_meta.get('row_count') or 0) > 0),
        hardware_built_at=(rmod_meta or {}).get('built_at') or '',
        hardware_status=(rmod_meta or {}).get('status') or '',
        wncelg_snapshot_ready=bool(wncelg_meta and int(wncelg_meta.get('site_count') or 0) > 0),
        wncelg_built_at=(wncelg_meta or {}).get('built_at') or '',
        wncelg_status=(wncelg_meta or {}).get('status') or '',
    )


# ── Hardware (RMOD_R) APIs ──────────────────────────────────────────────────


@configuration_dashboard_bp.route('/api/configuration-dashboard/hardware/areas', methods=['GET'])
@login_required
def hardware_areas():
    try:
        areas = rru_logic.list_areas()
        return jsonify({'success': True, 'areas': areas})
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@configuration_dashboard_bp.route('/api/configuration-dashboard/hardware/status', methods=['GET'])
@login_required
def hardware_status():
    meta = rru_store.get_build_meta() or {}
    return jsonify({
        'success': True,
        'nokia_ready': nokia_configured(),
        'snapshot_ready': bool(meta and int(meta.get('row_count') or 0) > 0),
        'built_at': meta.get('built_at'),
        'row_count': meta.get('row_count', 0),
        'status': meta.get('status'),
        'error': meta.get('error') or '',
        'trigger_source': meta.get('trigger_source'),
        'build_seconds': meta.get('build_seconds'),
        'mo_class': meta.get('mo_class') or '',
        'summary': meta.get('summary') or {},
        'warnings': meta.get('warnings') or [],
    })


@configuration_dashboard_bp.route('/api/configuration-dashboard/hardware/sankey', methods=['GET'])
@login_required
def hardware_sankey():
    try:
        user = get_current_user()
        area = (request.args.get('area') or '').strip()
        payload = rru_logic.snapshot_sankey_payload(area=area)
        meta = payload.get('meta')
        if not meta or int(meta.get('row_count') or 0) <= 0:
            return jsonify({
                'error': (
                    'No Hardware inventory snapshot yet. '
                    'An admin must run the daily job (04:00) or trigger it from Admin → Data Sync.'
                ),
                'snapshot_ready': False,
            }), 404

        sankey = payload.get('sankey') or {}
        try:
            log_activity(
                _username(user),
                'config_dashboard_hardware_sankey',
                (
                    f'RMOD snapshot area={area or "all"} '
                    f'physical={sankey.get("summary", {}).get("physical_rrus", 0)} '
                    f'built_at={meta.get("built_at")}'
                ),
            )
        except Exception:
            pass

        return jsonify({
            'success': True,
            'vendor': 'nokia',
            'source': 'snapshot',
            'area': area or 'all',
            'network_view': bool(payload.get('network_view')),
            'mo_class': payload.get('mo_class') or meta.get('mo_class') or '',
            'warnings': payload.get('warnings') or [],
            'built_at': meta.get('built_at'),
            'snapshot_status': meta.get('status'),
            'trigger_source': meta.get('trigger_source'),
            'nodes': sankey.get('nodes') or [],
            'links': sankey.get('links') or [],
            'summary': sankey.get('summary') or {},
            'rows': payload.get('rows') or [],
        })
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@configuration_dashboard_bp.route('/api/configuration-dashboard/hardware/export', methods=['GET'])
@login_required
def hardware_export():
    try:
        user = get_current_user()
        area = (request.args.get('area') or '').strip()
        payload = rru_logic.snapshot_sankey_payload(area=area)
        meta = payload.get('meta') or {}
        rows = payload.get('rows') or []
        if not rows:
            return jsonify({'error': 'No snapshot rows to export for this area.'}), 404

        buf, filename = build_rmod_workbook({
            'rows': rows,
            'area': area or 'all',
            'username': _username(user),
            'built_at': meta.get('built_at') or '',
            'mo_class': payload.get('mo_class') or meta.get('mo_class') or '',
            'summary': (payload.get('sankey') or {}).get('summary') or {},
        })
        try:
            log_activity(
                _username(user),
                'config_dashboard_hardware_export',
                f'Excel export area={area or "all"} rows={len(rows)}',
            )
        except Exception:
            pass
        return send_file(
            buf,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename,
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


# ── WNCELG APIs ─────────────────────────────────────────────────────────────


@configuration_dashboard_bp.route('/api/configuration-dashboard/wncelg/areas', methods=['GET'])
@login_required
def wncelg_areas():
    try:
        areas = wncelg_logic.list_areas()
        return jsonify({'success': True, 'areas': areas})
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@configuration_dashboard_bp.route('/api/configuration-dashboard/wncelg/status', methods=['GET'])
@login_required
def wncelg_status_api():
    meta = wncelg_store.get_build_meta() or {}
    return jsonify({
        'success': True,
        'nokia_ready': nokia_configured(),
        'snapshot_ready': bool(meta and int(meta.get('site_count') or 0) > 0),
        'built_at': meta.get('built_at'),
        'site_count': meta.get('site_count', 0),
        'group_count': meta.get('group_count', 0),
        'status': meta.get('status'),
        'error': meta.get('error') or '',
        'trigger_source': meta.get('trigger_source'),
        'build_seconds': meta.get('build_seconds'),
        'mo_class': meta.get('mo_class') or '',
        'summary': meta.get('summary') or {},
        'warnings': meta.get('warnings') or [],
    })


@configuration_dashboard_bp.route('/api/configuration-dashboard/wncelg/sites', methods=['GET'])
@login_required
def wncelg_sites():
    try:
        user = get_current_user()
        area = (request.args.get('area') or '').strip()
        status = (request.args.get('status') or '').strip()
        payload = wncelg_logic.snapshot_sites_payload(area=area, status=status)
        meta = payload.get('meta')
        if not meta or int(meta.get('site_count') or 0) <= 0:
            return jsonify({
                'error': (
                    'No WNCELG snapshot yet. '
                    'An admin must run the daily Configuration Dashboard job (04:00) '
                    'or trigger it from Admin → Data Sync.'
                ),
                'snapshot_ready': False,
            }), 404

        try:
            log_activity(
                _username(user),
                'config_dashboard_wncelg_sites',
                (
                    f'WNCELG snapshot area={area or "all"} status={status or "all"} '
                    f'sites={len(payload.get("sites") or [])} '
                    f'built_at={meta.get("built_at")}'
                ),
            )
        except Exception:
            pass

        return jsonify({
            'success': True,
            'vendor': 'nokia',
            'source': 'snapshot',
            'area': area or 'all',
            'status_filter': status or 'all',
            'mo_class': payload.get('mo_class') or meta.get('mo_class') or '',
            'warnings': payload.get('warnings') or [],
            'built_at': meta.get('built_at'),
            'snapshot_status': meta.get('status'),
            'trigger_source': meta.get('trigger_source'),
            'summary': payload.get('summary') or {},
            'network_summary': payload.get('network_summary') or {},
            'sites': payload.get('sites') or [],
        })
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@configuration_dashboard_bp.route('/api/configuration-dashboard/wncelg/export', methods=['GET'])
@login_required
def wncelg_export():
    try:
        user = get_current_user()
        area = (request.args.get('area') or '').strip()
        status = (request.args.get('status') or '').strip()
        payload = wncelg_logic.snapshot_sites_payload(area=area, status=status)
        meta = payload.get('meta') or {}
        sites = payload.get('sites') or []
        if not sites:
            return jsonify({'error': 'No WNCELG sites to export for these filters.'}), 404

        buf, filename = build_wncelg_workbook({
            'sites': sites,
            'area': area or 'all',
            'status': status or 'all',
            'username': _username(user),
            'built_at': meta.get('built_at') or '',
            'mo_class': payload.get('mo_class') or meta.get('mo_class') or '',
            'summary': payload.get('summary') or {},
        })
        try:
            log_activity(
                _username(user),
                'config_dashboard_wncelg_export',
                f'Excel export area={area or "all"} status={status or "all"} sites={len(sites)}',
            )
        except Exception:
            pass
        return send_file(
            buf,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename,
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@configuration_dashboard_bp.route('/api/configuration-dashboard/status', methods=['GET'])
@login_required
def combined_status():
    """Combined snapshot status for both tabs."""
    from modules.configuration_dashboard.ingest_job import last_ingest_result

    rmod_meta = rru_store.get_build_meta() or {}
    wncelg_meta = wncelg_store.get_build_meta() or {}
    return jsonify({
        'success': True,
        'nokia_ready': nokia_configured(),
        'hardware': {
            'snapshot_ready': bool(rmod_meta and int(rmod_meta.get('row_count') or 0) > 0),
            'built_at': rmod_meta.get('built_at'),
            'row_count': rmod_meta.get('row_count', 0),
            'status': rmod_meta.get('status'),
            'error': rmod_meta.get('error') or '',
        },
        'wncelg': {
            'snapshot_ready': bool(wncelg_meta and int(wncelg_meta.get('site_count') or 0) > 0),
            'built_at': wncelg_meta.get('built_at'),
            'site_count': wncelg_meta.get('site_count', 0),
            'group_count': wncelg_meta.get('group_count', 0),
            'status': wncelg_meta.get('status'),
            'error': wncelg_meta.get('error') or '',
            'summary': wncelg_meta.get('summary') or {},
        },
        'last_run': last_ingest_result(),
    })
