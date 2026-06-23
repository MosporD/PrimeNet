"""Performance Analytics routes — Huawei MAE PM Open API (section 5.4)."""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from core.cm_extractor.huawei_client import HuaweiCmError
from core.cm_extractor.huawei_discovery import get_cached_discovery
from core.cm_extractor.site_catalog import merge_huawei_ne_names
from core.huawei_pm.client import HuaweiPmError
from core.huawei_pm.config import build_pm_client, pm_configured, pm_defaults
from core.huawei_pm.constants import NE_TYPE_NAMES, QUERY_PERIODS_MINUTES, RAT_TYPE_NAMES
from core.huawei_pm.counter_catalog import (
    filter_counters,
    get_technology_catalog,
    list_technologies,
    subset_ids_for_counters,
)
from database_enhanced import get_user_by_session, log_activity

TECH_NE_TYPE = {
    '2G': 'BSC6900 GSM',
    '3G': 'BSC6900 UMTS',
    '4G': 'eNodeB',
    '5G': 'BTS5900 5G',
}

performance_analytics_bp = Blueprint(
    'performance_analytics',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/performance-analytics/static',
)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get('session_token')
        if not token:
            return redirect(url_for('auth.login_page'))
        user = get_user_by_session(token)
        if not user:
            return redirect(url_for('auth.login_page'))
        request.current_user = user
        return f(*args, **kwargs)

    return decorated


def get_current_user():
    token = request.cookies.get('session_token')
    return get_user_by_session(token) if token else None


def format_user(user):
    if not user:
        return None
    return {
        'id': user.get('id'),
        'username': user.get('username'),
        'role': user.get('role'),
    }


def _parse_counter_ids(raw) -> list[int]:
    if raw is None:
        return []
    if isinstance(raw, list):
        items = raw
    else:
        items = str(raw).replace(';', ',').split(',')
    out: list[int] = []
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        out.append(int(text))
    return out


def _parse_ne_names(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(n).strip() for n in raw if str(n).strip()]
    return [n.strip() for n in str(raw).split(',') if n.strip()]


def _default_time_window(hours: int = 1) -> tuple[str, str]:
    end = datetime.now().replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=max(1, hours))
    fmt = '%Y-%m-%d %H:%M:%S'
    return start.strftime(fmt), end.strftime(fmt)


@performance_analytics_bp.route('/performance-analytics')
@login_required
def performance_analytics_page():
    user = get_current_user()
    cfg = pm_defaults()
    start_default, end_default = _default_time_window(1)
    return render_template(
        'performance_analytics.html',
        user=format_user(user),
        configured=pm_configured(),
        host=cfg.get('host') or '',
        port=cfg.get('port') or 31127,
        ne_types=NE_TYPE_NAMES,
        rat_types=RAT_TYPE_NAMES,
        periods=QUERY_PERIODS_MINUTES,
        start_default=start_default,
        end_default=end_default,
    )


def _parse_site_ids(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(s).strip() for s in raw if str(s).strip()]
    return [s.strip() for s in str(raw).split(',') if s.strip()]


def _ne_type_for_technology(technology: str, explicit: str = '') -> str:
    if explicit.strip():
        return explicit.strip()
    tech = str(technology or '').strip().upper()
    cat = get_technology_catalog(tech)
    if cat.get('ne_type'):
        return str(cat['ne_type'])
    return TECH_NE_TYPE.get(tech, 'eNodeB')


def _resolve_ne_names(site_ids: list[str], explicit_ne_names: list[str]) -> list[str]:
    if explicit_ne_names:
        return explicit_ne_names
    if not site_ids:
        return []
    resolved, unresolved, _alts, _skipped = merge_huawei_ne_names(site_ids, ne_names=None)
    if unresolved:
        raise ValueError(
            f'Could not map U2020 NE name for site id(s): {", ".join(unresolved[:5])}'
            + (f' (+{len(unresolved) - 5} more)' if len(unresolved) > 5 else '')
            + '. Run CM Extractor NE discovery or check site_id ↔ meName mapping.',
        )
    return resolved


@performance_analytics_bp.route('/api/performance-analytics/counter-catalog')
@login_required
def api_counter_catalog():
    return jsonify({'success': True, 'technologies': list_technologies()})


@performance_analytics_bp.route('/api/performance-analytics/counter-subsets')
@login_required
def api_counter_subsets():
    technology = str(request.args.get('technology') or '').strip().upper()
    cat = get_technology_catalog(technology)
    if not cat.get('configured'):
        return jsonify({
            'success': False,
            'error': f'No counter catalog for {technology or "technology"}.',
            'technology': technology,
        }), 404
    return jsonify({
        'success': True,
        'technology': technology,
        'ne_type': cat.get('ne_type'),
        'oss_ne_type': cat.get('oss_ne_type'),
        'total_counters': cat.get('total_counters', 0),
        'subsets': cat.get('subsets') or [],
    })


@performance_analytics_bp.route('/api/performance-analytics/counters')
@login_required
def api_counters():
    technology = str(request.args.get('technology') or '').strip().upper()
    q = str(request.args.get('q') or request.args.get('search') or '').strip()
    subset_raw = str(request.args.get('subset_id') or request.args.get('function_subset_id') or '').strip()
    subset_id = int(subset_raw) if subset_raw.isdigit() else None
    try:
        limit = int(request.args.get('limit') or 300)
    except ValueError:
        limit = 300
    try:
        offset = int(request.args.get('offset') or 0)
    except ValueError:
        offset = 0

    payload = filter_counters(
        technology,
        q=q,
        subset_id=subset_id,
        limit=limit,
        offset=offset,
    )
    if not payload.get('configured'):
        return jsonify({
            'success': False,
            'error': f'Counter catalog not loaded for {technology or "technology"}.',
            **payload,
        }), 404
    return jsonify({'success': True, **payload})


@performance_analytics_bp.route('/api/performance-analytics/config')
@login_required
def api_config():
    cfg = pm_defaults()
    return jsonify({
        'success': True,
        'configured': pm_configured(),
        'host': cfg.get('host') or '',
        'port': cfg.get('port') or 31127,
        'neTypes': list(NE_TYPE_NAMES),
        'ratTypes': list(RAT_TYPE_NAMES),
        'periods': list(QUERY_PERIODS_MINUTES),
        'limits': {
            'maxCounters': 150,
            'maxQueryHours': 24,
            'pageLimit': cfg.get('page_limit') or 5000,
        },
    })


@performance_analytics_bp.route('/api/performance-analytics/nes')
@login_required
def api_nes():
    if not pm_configured():
        return jsonify({'success': False, 'error': 'Huawei PM API is not configured.'}), 503
    try:
        cache = get_cached_discovery()
        nes = cache.get('nes') or []
        rows = [
            {
                'neName': n.get('ne_name') or n.get('name') or '',
                'siteId': n.get('site_id') or '',
                'product': n.get('product') or '',
            }
            for n in nes
            if (n.get('ne_name') or n.get('name'))
        ]
        rows.sort(key=lambda r: (r['siteId'], r['neName']))
        return jsonify({'success': True, 'nes': rows, 'cachedAt': cache.get('fetched_at')})
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500


@performance_analytics_bp.route('/api/performance-analytics/test-connection', methods=['POST'])
@login_required
def api_test_connection():
    if not pm_configured():
        return jsonify({'success': False, 'error': 'Huawei PM API is not configured.'}), 503
    try:
        client = build_pm_client()
        result = client.test_connection()
        return jsonify({'success': True, **result})
    except (HuaweiPmError, HuaweiCmError) as exc:
        return jsonify({'success': False, 'error': str(exc)}), 502
    except ConnectionError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 502


@performance_analytics_bp.route('/api/performance-analytics/query', methods=['POST'])
@login_required
def api_query():
    if not pm_configured():
        return jsonify({'success': False, 'error': 'Huawei PM API is not configured.'}), 503

    body = request.get_json(silent=True) or {}
    try:
        counter_ids = _parse_counter_ids(body.get('counterIds'))
        ne_names = _parse_ne_names(body.get('neNames'))
        site_ids = _parse_site_ids(body.get('siteIds'))
        technology = str(body.get('technology') or '').strip().upper()
        is_query_all = int(body.get('isQueryAllNe') or 0)
        period = int(body.get('period') or 60)
        start_time = str(body.get('startTime') or '').strip()
        end_time = str(body.get('endTime') or '').strip()
        ne_type_name = _ne_type_for_technology(technology, str(body.get('neTypeName') or ''))
        rat_type_name = str(body.get('ratTypeName') or '').strip()

        if not counter_ids:
            raise ValueError('Select at least one counter.')

        if len(counter_ids) > 150:
            raise ValueError(f'At most 150 counters per MAE query ({len(counter_ids)} selected).')

        subset_count = len(subset_ids_for_counters(counter_ids, technology))
        if subset_count > 10:
            raise ValueError(
                f'Selected counters span {subset_count} function subsets; MAE allows at most 10 per query. '
                'Narrow selection to one or few measurement subsets.',
            )

        if not start_time or not end_time:
            start_time, end_time = _default_time_window(1)

        if not is_query_all:
            ne_names = _resolve_ne_names(site_ids, ne_names)
            if not ne_names:
                raise ValueError('Select at least one cell or provide neNames / siteIds.')

        condition: dict = {
            'timeFormat': body.get('timeFormat') or 'timeString',
            'startTime': start_time,
            'endTime': end_time,
            'period': period,
            'counterIds': counter_ids,
            'isQueryAllNe': is_query_all,
            'neTypeName': ne_type_name,
        }
        if rat_type_name:
            condition['ratTypeName'] = rat_type_name
        if ne_names and not is_query_all:
            condition['neNames'] = ne_names

        delete_after = body.get('deleteAfter', True)
        if isinstance(delete_after, str):
            delete_after = delete_after.lower() not in ('0', 'false', 'no')

        client = build_pm_client()
        payload = client.query_performance_data(condition, delete_after=bool(delete_after))

        user = get_current_user()
        if user:
            log_activity(
                user.get('id'),
                'performance_analytics_query',
                f'Huawei PM query {len(payload.get("result") or [])} rows',
            )

        return jsonify({'success': True, 'query': payload})
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except (HuaweiPmError, HuaweiCmError) as exc:
        status = getattr(exc, 'status', None) or 502
        return jsonify({'success': False, 'error': str(exc), 'payload': getattr(exc, 'payload', None)}), status
    except ConnectionError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 502
