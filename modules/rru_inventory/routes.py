"""Radio Hardware Inventory Report routes — Nokia RMOD_R Sankey dashboard."""

from __future__ import annotations

from functools import wraps
from typing import Any

from flask import Blueprint, jsonify, redirect, render_template, request, send_file, url_for

from core.cm_extractor.config import nokia_configured
from core.platform.session import get_session_token
from database_enhanced import get_user_by_session, log_activity
from modules.rru_inventory import logic as rru_logic
from modules.rru_inventory import store as rru_store
from modules.rru_inventory.export import build_rmod_workbook

rru_inventory_bp = Blueprint(
    'rru_inventory',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/rru-inventory/static',
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


@rru_inventory_bp.route('/rru-inventory')
@login_required
def rru_inventory_page():
    """Legacy route — Hardware lives under Configuration Dashboard."""
    return redirect('/configuration-dashboard?tab=hardware')


@rru_inventory_bp.route('/api/rru-inventory/areas', methods=['GET'])
@login_required
def rru_inventory_areas():
    try:
        areas = rru_logic.list_areas()
        return jsonify({'success': True, 'areas': areas})
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@rru_inventory_bp.route('/api/rru-inventory/status', methods=['GET'])
@login_required
def rru_inventory_status():
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


@rru_inventory_bp.route('/api/rru-inventory/sankey', methods=['GET'])
@login_required
def rru_inventory_sankey():
    try:
        user = get_current_user()
        area = (request.args.get('area') or '').strip()
        payload = rru_logic.snapshot_sankey_payload(area=area)
        meta = payload.get('meta')
        if not meta or int(meta.get('row_count') or 0) <= 0:
            return jsonify({
                'error': (
                    'No Radio Hardware Inventory snapshot yet. '
                    'An admin must run the daily job (04:00) or trigger it from Admin → Data Sync.'
                ),
                'snapshot_ready': False,
            }), 404

        sankey = payload.get('sankey') or {}
        try:
            log_activity(
                _username(user),
                'rru_inventory_sankey',
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


@rru_inventory_bp.route('/api/rru-inventory/export', methods=['GET'])
@login_required
def rru_inventory_export():
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
                'rru_inventory_export',
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
