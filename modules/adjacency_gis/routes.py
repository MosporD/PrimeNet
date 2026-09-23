"""Adjacency GIS UI and APIs — 2G configured NCL map (Nokia ADCE + Huawei G2GNCELL)."""

from __future__ import annotations

import threading
from functools import wraps

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from core.cm_extractor.config import huawei_configured, nokia_configured
from core.platform.session import get_session_token
from database_enhanced import get_user_by_session, log_activity
from modules.adjacency_gis import logic as adj_logic
from modules.adjacency_gis import store as adj_store
from modules.adjacency_gis.nokia_parse import DEFAULT_OVERSHOOT_KM, NCL_HARD_LIMIT

adjacency_gis_bp = Blueprint(
    'adjacency_gis',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/adjacency-gis/static',
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


def _is_owner(user) -> bool:
    if not user:
        return False
    role = (user.get('role') if isinstance(user, dict) else user[6] or '') or ''
    return str(role).strip().lower() in ('owner', 'admin')


@adjacency_gis_bp.route('/adjacency-gis')
@login_required
def adjacency_gis_page():
    user = format_user_data(get_current_user())
    meta = adj_store.get_build_meta()
    return render_template(
        'adjacency_gis.html',
        user=user,
        nokia_ready=nokia_configured(),
        huawei_ready=huawei_configured(),
        snapshot_ready=bool(meta and int(meta.get('sector_count') or 0) > 0),
        build_meta=meta,
    )


@adjacency_gis_bp.route('/api/adjacency-gis/status')
@login_required
def adjacency_gis_status():
    from modules.adjacency_gis.ingest_job import last_ingest_result

    meta = adj_store.get_build_meta() or {}
    return jsonify({
        'success': True,
        'nokia_ready': nokia_configured(),
        'huawei_ready': huawei_configured(),
        'snapshot': meta,
        'nokia': adj_store.get_build_meta('nokia'),
        'huawei': adj_store.get_build_meta('huawei'),
        'last_run': last_ingest_result(),
        'last_run_nokia': last_ingest_result('nokia'),
        'last_run_huawei': last_ingest_result('huawei'),
        'defaults': {
            'overshoot_km': DEFAULT_OVERSHOOT_KM,
            'ncl_limit': NCL_HARD_LIMIT,
        },
    })


@adjacency_gis_bp.route('/api/adjacency-gis/data')
@login_required
def adjacency_gis_data():
    meta = adj_store.get_build_meta()
    if not meta or int(meta.get('sector_count') or 0) <= 0:
        return jsonify({
            'success': False,
            'error': (
                'No Adjacency GIS snapshot yet. '
                'Wait for the daily ingest or trigger a refresh from Admin → Data Sync.'
            ),
            'snapshot': meta,
        }), 404

    vendor = str(request.args.get('vendor') or 'all').strip().lower()
    bsc_id = str(request.args.get('bsc') or request.args.get('bsc_id') or 'all').strip()
    area = str(request.args.get('area') or 'all').strip()
    issue = str(request.args.get('issue') or 'all').strip().lower()
    try:
        overshoot_km = float(request.args.get('overshoot_km') or DEFAULT_OVERSHOOT_KM)
    except (TypeError, ValueError):
        overshoot_km = DEFAULT_OVERSHOOT_KM
    try:
        ncl_limit = int(request.args.get('ncl_limit') or NCL_HARD_LIMIT)
    except (TypeError, ValueError):
        ncl_limit = NCL_HARD_LIMIT

    load_vendor = None if vendor in ('all', '*', '') else vendor
    sectors = adj_store.load_sectors(load_vendor)
    edges = adj_store.load_edges(load_vendor)
    payload = adj_logic.build_map_payload(
        sectors,
        edges,
        bsc_id=bsc_id,
        area=area,
        issue=issue,
        vendor=vendor,
        overshoot_km=overshoot_km,
        ncl_limit=ncl_limit,
    )
    store_bscs = adj_store.list_bsc_ids(load_vendor)
    filters = payload.get('filters') or {}
    filters['bscs'] = sorted(set(filters.get('bscs') or []) | set(store_bscs))

    try:
        log_activity(
            _username(get_current_user()),
            'adjacency_gis_query',
            f"vendor={vendor} bsc={bsc_id} area={area} issue={issue} edges={payload['counts'].get('edges')}",
        )
    except Exception:
        pass

    return jsonify({
        'success': True,
        'vendor': vendor,
        'built_at': meta.get('built_at'),
        'snapshot_status': meta.get('status'),
        'warnings': meta.get('warnings') or [],
        'sectors': payload['sectors'],
        'edges': payload['edges'],
        'counts': payload['counts'],
        'filters': filters,
    })


@adjacency_gis_bp.route('/api/adjacency-gis/refresh', methods=['POST'])
@login_required
def adjacency_gis_refresh():
    """Manual snapshot rebuild (owner/admin). Body/query: vendor=nokia|huawei|all."""
    user = get_current_user()
    if not _is_owner(user):
        return jsonify({'error': 'Owner access required'}), 403

    vendor = str(
        (request.get_json(silent=True) or {}).get('vendor')
        or request.args.get('vendor')
        or 'all'
    ).strip().lower()
    if vendor not in ('nokia', 'huawei', 'all', '*'):
        return jsonify({'success': False, 'error': 'vendor must be nokia, huawei, or all'}), 400

    if vendor in ('nokia', 'all', '*') and not nokia_configured():
        if vendor == 'nokia':
            return jsonify({'success': False, 'error': 'Nokia NetAct CM is not configured.'}), 400
    if vendor in ('huawei', 'all', '*') and not huawei_configured():
        if vendor == 'huawei':
            return jsonify({'success': False, 'error': 'Huawei U2020 CM is not configured.'}), 400

    def _run():
        from modules.adjacency_gis.ingest_job import run_adjacency_gis_ingest

        run_adjacency_gis_ingest(trigger_source='manual', vendor=vendor)

    threading.Thread(target=_run, daemon=True).start()
    try:
        log_activity(
            _username(user),
            'adjacency_gis_manual_run',
            f'Manual Adjacency GIS ingest triggered vendor={vendor}',
        )
    except Exception:
        pass
    return jsonify({
        'success': True,
        'vendor': vendor,
        'message': f'Adjacency GIS ingest started in background ({vendor}).',
    })
