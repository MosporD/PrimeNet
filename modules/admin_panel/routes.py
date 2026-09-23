"""
Admin Panel Routes
Engineering operations: sync, API connections, PM Plus, activity / CM / RET alerts.
Identity and module access live on NexusCore Platform Admin (/admin).
"""

import os
import sqlite3
from datetime import datetime
from flask import Blueprint, request, jsonify, render_template, redirect, url_for, send_file
from functools import wraps

from database_enhanced import (
    get_user_by_session,
    log_activity,
    get_db,
)
from db.runtime import execute_query
from core.cm_extractor.config import (
    huawei_configured,
    huawei_defaults,
    nokia_configured,
    nokia_defaults,
)
from core.cm_extractor.huawei_client import HuaweiCmClient, HuaweiCmError
from core.cm_extractor.nokia_client import NokiaCmClient, NokiaCmError
from core.huawei_pm.config import build_pm_client, pm_configured
from core.huawei_pm.client import HuaweiPmError
from core.platform.paths import platform_admin_entry_url
from modules.admin_panel.export import build_table_workbook
from sync_config import (
    DATABASES_ROOT,
    HUAWEI_PM_DAILY_DB,
    HUAWEI_PM_DB,
    NOKIA_PM_DAILY_DB,
    NOKIA_PM_DB,
)
from core.platform.session import get_session_token

admin_panel_bp = Blueprint(
    'admin_panel', __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/admin_panel/static',
)

ROLE_LABELS = {
    'admin': 'Owner',
    'user': 'User',
    'ran_config_user': 'RNC User',
    'noc_sys': 'NOC SYS',
}


def _user_role(user) -> str:
    if not user:
        return ''
    raw = user.get('role') if isinstance(user, dict) else user[6]
    return str(raw or '').strip().lower()


def _is_owner(user) -> bool:
    return _user_role(user) == 'admin'


def login_required(f):
    """Decorator to require login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        session_token = get_session_token()
        if not session_token:
            return redirect(url_for('auth.login_page'))

        user = get_user_by_session(session_token)
        if not user:
            return redirect(url_for('auth.login_page'))

        request.current_user = user
        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    """Decorator to require Owner (engineering ops admin)."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        session_token = get_session_token()
        if not session_token:
            return redirect(url_for('auth.login_page'))

        user = get_user_by_session(session_token)
        if not _is_owner(user):
            return redirect(url_for('auth.dashboard'))

        request.current_user = user
        return f(*args, **kwargs)

    return decorated_function


def get_current_user():
    """Get current logged-in user"""
    session_token = get_session_token()
    if session_token:
        return get_user_by_session(session_token)
    return None


def format_user_data(user):
    """Format user data for templates"""
    if not user:
        return None
    if isinstance(user, dict):
        return {'username': user.get('username'), 'email': user.get('email'), 'role': user.get('role'), 'id': user.get('id')}
    return {
        'username': user[1],
        'email': user[2],
        'role': user[6],
        'id': user[0],
    }


def _platform_admin_moved():
    target = platform_admin_entry_url()
    return jsonify({
        'error': 'User and module access administration moved to NexusCore Platform Admin',
        'redirect': target,
    }), 410


@admin_panel_bp.route('/admin-panel')
@admin_required
def admin_panel_page():
    """Render Engineering Admin Panel page"""
    user = get_current_user()
    return render_template(
        'admin_panel.html',
        user=format_user_data(user),
        role_labels=ROLE_LABELS,
        can_manage_sync=True,
        can_manage_access=False,
    )


@admin_panel_bp.route('/api/admin/feature-access', methods=['GET', 'POST'])
@admin_panel_bp.route('/api/admin/feature-access/reset', methods=['POST'])
def feature_access_moved():
    return _platform_admin_moved()


@admin_panel_bp.route('/api/admin/users', methods=['GET', 'POST'])
@admin_panel_bp.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@admin_panel_bp.route('/api/admin/users/<int:user_id>/reset-password', methods=['POST'])
@admin_panel_bp.route('/api/admin/users/<int:user_id>/portals', methods=['PUT'])
@admin_panel_bp.route('/api/admin/users/<int:user_id>/role', methods=['PUT'])
@admin_panel_bp.route('/api/admin/users/<int:user_id>/status', methods=['PUT'])
def users_admin_moved(**_kwargs):
    return _platform_admin_moved()


def _sqlite_quote_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _pick_time_column(cols: list) -> str | None:
    """First usable time column (same priority idea as performance routes)."""
    by_lower = {str(c).lower(): c for c in cols}
    for key in ('timestamp', 'period_start_time', 'time', 'date'):
        if key in by_lower:
            return str(by_lower[key])
    return None


def _compare_pm_timestamp(a, b) -> bool:
    """True if b is strictly newer than a (None treated as smallest)."""
    if b is None or str(b).strip() == '':
        return False
    if a is None or str(a).strip() == '':
        return True
    da = _parse_pm_timestamp(a)
    db = _parse_pm_timestamp(b)
    if da is not None and db is not None:
        return db > da
    sa, sb = str(a).strip(), str(b).strip()
    if sa == sb:
        return False
    return sb > sa


def _parse_pm_timestamp(value):
    """Best-effort parser for Nokia/Huawei date-time strings."""
    s = str(value or '').strip()
    if not s:
        return None
    for fmt in (
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %H:%M:%S.%f',
        '%Y-%m-%d',
        '%d/%m/%Y %H:%M',
        '%d/%m/%y %H:%M',
        '%d/%m/%Y',
        '%d/%m/%y',
        '%m.%d.%y %H:%M:%S',
        '%d.%m.%Y %H:%M:%S',
        '%d.%m.%Y',
        '%m.%d.%Y %H:%M:%S',
        '%m.%d.%Y',
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _normalize_pm_timestamp(value):
    dt = _parse_pm_timestamp(value)
    if dt is None:
        return str(value) if value is not None else None
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def _best_timestamp_sqlite(conn, table_name: str, time_column: str):
    """
    Return chronologically latest timestamp by parsing row values, not lexical MAX().
    This avoids wrong ordering for text formats like dd/mm/yyyy.
    """
    best_raw = None
    best_dt = None
    qtbl = _sqlite_quote_ident(table_name)
    qcol = _sqlite_quote_ident(time_column)
    try:
        cur = conn.execute(f'SELECT {qcol} FROM {qtbl}')
        for row in cur.fetchall():
            raw = row[0] if row else None
            dt = _parse_pm_timestamp(raw)
            if dt is None:
                continue
            if best_dt is None or dt > best_dt:
                best_dt = dt
                best_raw = raw
    except Exception:
        return None
    return best_raw


def _sqlite_pm_survey(path: str) -> dict:
    """Return last timestamp across tables that expose a ``timestamp`` column."""
    out = {
        'backend': 'sqlite',
        'path': path,
        'exists': os.path.isfile(path),
        'last_timestamp': None,
        'latest_table': None,
        'per_table': [],
        'error': None,
    }
    if not out['exists']:
        return out
    try:
        conn = sqlite3.connect(path, timeout=20)
        try:
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]
            best_ts, best_tbl = None, None
            for tbl in tables:
                cols = [
                    r[1]
                    for r in conn.execute(f'PRAGMA table_info({_sqlite_quote_ident(tbl)})').fetchall()
                ]
                tcol = _pick_time_column(cols)
                if not tcol:
                    continue
                mx = _best_timestamp_sqlite(conn, tbl, tcol)
                if mx is not None and str(mx).strip() != '':
                    out['per_table'].append({'table': tbl, 'last_timestamp': _normalize_pm_timestamp(mx)})
                    if _compare_pm_timestamp(best_ts, mx):
                        best_ts, best_tbl = mx, tbl
            out['last_timestamp'] = _normalize_pm_timestamp(best_ts) if best_ts is not None else None
            out['latest_table'] = best_tbl
        finally:
            conn.close()
    except Exception as e:
        out['error'] = str(e)
    return out


def _pm_database_definitions():
    """Ordered list of (label, kind, path) for PM cell databases."""
    femto = os.path.join(DATABASES_ROOT, 'cells', 'femto_pm_cells.db')
    femto_kpis = os.path.join(DATABASES_ROOT, 'cells', 'femto_user_kpis.db')
    return [
        ('Nokia PM (hourly)', 'nokia_hourly', NOKIA_PM_DB),
        ('Huawei PM (hourly)', 'huawei_hourly', HUAWEI_PM_DB),
        ('Nokia PM (daily)', 'sqlite', NOKIA_PM_DAILY_DB),
        ('Huawei PM (daily)', 'sqlite', HUAWEI_PM_DAILY_DB),
        ('Femto PM', 'sqlite', femto),
        ('Femto user KPIs', 'sqlite', femto_kpis),
    ]


def _api_connection_row(
    label: str,
    *,
    configured: bool,
    endpoint: str = '',
    missing: list[str] | None = None,
) -> dict:
    return {
        'label': label,
        'configured': configured,
        'endpoint': endpoint,
        'missing': missing or [],
        'status': 'skipped',
        'message': '',
        'error': None,
    }


def _test_nokia_cm_connection() -> dict:
    row = _api_connection_row('Nokia CM API', configured=nokia_configured())
    cfg = nokia_defaults()
    host = cfg.get('host') or cfg.get('base_url') or ''
    row['endpoint'] = host
    if not row['configured']:
        row['message'] = 'Not configured (.env: NOKIA_CM_HOST, NOKIA_CM_USER, NOKIA_CM_PASSWORD)'
        return row
    try:
        client = NokiaCmClient(
            host=cfg['host'],
            username=cfg['username'],
            password=cfg['password'],
            base_url=cfg.get('base_url') or '',
            use_https=cfg['use_https'],
            verify_ssl=cfg['verify_ssl'],
            timeout=min(int(cfg.get('timeout') or 180), 60),
            max_retries=cfg.get('max_retries', 2),
            retry_base_delay_sec=cfg.get('retry_base_delay_sec', 2.0),
        )
        client.test_connection()
        row['status'] = 'ok'
        row['message'] = 'Connected to Nokia NetAct CM API'
    except NokiaCmError as exc:
        row['status'] = 'error'
        row['error'] = str(exc)
        row['message'] = str(exc)
    except Exception as exc:
        row['status'] = 'error'
        row['error'] = str(exc)
        row['message'] = f'Connection failed: {exc}'
    return row


def _test_huawei_cm_connection() -> dict:
    import os

    row = _api_connection_row('Huawei CM API', configured=huawei_configured())
    cfg = huawei_defaults()
    row['endpoint'] = f"{cfg.get('host') or ''}:{cfg.get('port') or 31127}".strip(':')
    huawei_enabled = (os.environ.get('CM_HUAWEI_ENABLED') or 'true').strip().lower() not in (
        '0', 'false', 'no', 'off',
    )
    if not huawei_enabled:
        row['message'] = 'Huawei CM feature disabled (CM_HUAWEI_ENABLED=false)'
        return row
    if not row['configured']:
        row['message'] = 'Not configured (.env: HUAWEI_CM_HOST, HUAWEI_CM_USER, HUAWEI_CM_PASSWORD)'
        return row
    try:
        client = HuaweiCmClient(
            host=cfg['host'],
            username=cfg['username'],
            password=cfg['password'],
            port=int(cfg.get('port') or 31127),
            use_https=cfg.get('use_https', True),
            verify_ssl=cfg.get('verify_ssl', False),
            api_style=cfg.get('api_style', 'wireless'),
            client_ip=cfg.get('client_ip', ''),
            timeout=min(int(cfg.get('timeout') or 180), 60),
        )
        result = client.test_connection()
        row['status'] = 'ok'
        row['message'] = result.get('message', 'Authentication successful')
    except HuaweiCmError as exc:
        row['status'] = 'error'
        row['error'] = str(exc)
        row['message'] = str(exc)
    except Exception as exc:
        row['status'] = 'error'
        row['error'] = str(exc)
        row['message'] = f'Connection failed: {exc}'
    return row


def _test_huawei_pm_connection() -> dict:
    row = _api_connection_row('Huawei PM API', configured=pm_configured())
    cfg = huawei_defaults()
    row['endpoint'] = f"{cfg.get('host') or ''}:{cfg.get('port') or 31127}".strip(':')
    if not row['configured']:
        row['message'] = 'Not configured (uses HUAWEI_CM_* / HUAWEI_PM_* in .env)'
        return row
    try:
        client = build_pm_client()
        result = client.test_connection()
        row['status'] = 'ok'
        row['message'] = result.get('message', 'Huawei PM Open API authentication successful')
    except (HuaweiPmError, HuaweiCmError, ValueError) as exc:
        row['status'] = 'error'
        row['error'] = str(exc)
        row['message'] = str(exc)
    except Exception as exc:
        row['status'] = 'error'
        row['error'] = str(exc)
        row['message'] = f'Connection failed: {exc}'
    return row


@admin_panel_bp.route('/api/admin/test-api-connections', methods=['POST'])
def test_api_connections():
    """Live connectivity checks for vendor northbound APIs (Owner only)."""
    user = get_current_user()
    if not _is_owner(user):
        return jsonify({'error': 'Owner access required'}), 403

    data = request.get_json(silent=True) or {}
    vendor = str(data.get('vendor') or 'all').strip().lower()

    tests = {
        'nokia_cm': _test_nokia_cm_connection,
        'huawei_cm': _test_huawei_cm_connection,
        'huawei_pm': _test_huawei_pm_connection,
    }
    if vendor != 'all' and vendor not in tests:
        return jsonify({'error': 'Unknown vendor'}), 400

    try:
        results = {}
        selected = tests if vendor == 'all' else {vendor: tests[vendor]}
        for key, fn in selected.items():
            results[key] = fn()

        tested = [r for r in results.values() if r.get('status') in ('ok', 'error')]
        ok_count = sum(1 for r in tested if r.get('status') == 'ok')
        error_count = sum(1 for r in tested if r.get('status') == 'error')

        log_activity(
            (user.get('id') if isinstance(user, dict) else user[0]),
            'admin_test_api_connections',
            f'Tested API connections ({vendor}): {ok_count} ok, {error_count} failed',
        )
        return jsonify({
            'success': True,
            'results': results,
            'summary': {
                'tested': len(tested),
                'ok': ok_count,
                'failed': error_count,
                'skipped': sum(1 for r in results.values() if r.get('status') == 'skipped'),
            },
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/api/admin/pm-latest-timestamps', methods=['GET'])
def pm_latest_timestamps():
    """Latest ``timestamp`` value per PM database (Owner only)."""
    user = get_current_user()
    if not _is_owner(user):
        return jsonify({'error': 'Owner access required'}), 403

    databases = []
    try:
        for label, kind, path in _pm_database_definitions():
            if kind == 'nokia_hourly':
                row = {**_sqlite_pm_survey(path), 'label': label}
            elif kind == 'huawei_hourly':
                row = {**_sqlite_pm_survey(path), 'label': label}
            else:
                row = {**_sqlite_pm_survey(path), 'label': label}
            databases.append(row)

        log_activity(
            (user.get('id') if isinstance(user, dict) else user[0]),
            'admin_pm_latest_timestamps',
            'Viewed PM latest timestamps',
        )
        return jsonify({'success': True, 'databases': databases})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/api/admin/rru-inventory/status', methods=['GET'])
@admin_panel_bp.route('/api/admin/configuration-dashboard/status', methods=['GET'])
def rru_inventory_admin_status():
    """Snapshot meta for Configuration Dashboard (Owner only)."""
    user = get_current_user()
    if not _is_owner(user):
        return jsonify({'error': 'Owner access required'}), 403
    try:
        from modules.configuration_dashboard.ingest_job import last_ingest_result
        from modules.configuration_dashboard import wncelg_store
        from modules.rru_inventory import store as rru_store

        rmod_meta = rru_store.get_build_meta() or {}
        wncelg_meta = wncelg_store.get_build_meta() or {}
        return jsonify({
            'success': True,
            'nokia_ready': nokia_configured(),
            'snapshot': rmod_meta,
            'hardware': rmod_meta,
            'wncelg': wncelg_meta,
            'last_run': last_ingest_result(),
            'schedule': 'Daily 04:00 (RRU_INVENTORY_CRON_HOUR/MINUTE) — RMOD_R + WNCELG',
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/api/admin/rru-inventory/run', methods=['POST'])
@admin_panel_bp.route('/api/admin/configuration-dashboard/run', methods=['POST'])
def rru_inventory_admin_run():
    """Manually trigger Configuration Dashboard ingest: RMOD_R + WNCELG (Owner only)."""
    import threading

    user = get_current_user()
    if not _is_owner(user):
        return jsonify({'error': 'Owner access required'}), 403
    if not nokia_configured():
        return jsonify({'success': False, 'error': 'Nokia NetAct CM is not configured.'}), 400

    def _run():
        from modules.configuration_dashboard.ingest_job import run_config_dashboard_ingest

        run_config_dashboard_ingest(trigger_source='manual')

    threading.Thread(target=_run, daemon=True).start()
    try:
        log_activity(
            (user.get('id') if isinstance(user, dict) else user[0]),
            'configuration_dashboard_manual_run',
            'Manual Configuration Dashboard ingest triggered (RMOD_R + WNCELG)',
        )
    except Exception:
        pass
    return jsonify({
        'success': True,
        'message': 'Configuration Dashboard ingest started in background (RMOD_R + WNCELG).',
    })


@admin_panel_bp.route('/api/admin/adjacency-gis/status', methods=['GET'])
def adjacency_gis_admin_status():
    """Snapshot meta for Adjacency GIS (Owner only)."""
    user = get_current_user()
    if not _is_owner(user):
        return jsonify({'error': 'Owner access required'}), 403
    try:
        from modules.adjacency_gis import store as adj_store
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
            'schedule': (
                'Nokia daily 04:30 (ADJACENCY_GIS_CRON_*); '
                'Huawei daily 04:45 (ADJACENCY_GIS_HUAWEI_CRON_*)'
            ),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/api/admin/adjacency-gis/run', methods=['POST'])
def adjacency_gis_admin_run():
    """Manually trigger adjacency CM snapshot ingest (Owner only).

    JSON/query ``vendor``: nokia | huawei | all (default all).
    """
    import threading

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

    if vendor in ('nokia', 'all', '*') and not nokia_configured() and vendor == 'nokia':
        return jsonify({'success': False, 'error': 'Nokia NetAct CM is not configured.'}), 400
    if vendor in ('huawei', 'all', '*') and not huawei_configured() and vendor == 'huawei':
        return jsonify({'success': False, 'error': 'Huawei U2020 CM is not configured.'}), 400
    if vendor in ('all', '*') and not nokia_configured() and not huawei_configured():
        return jsonify({'success': False, 'error': 'Neither Nokia nor Huawei CM is configured.'}), 400

    def _run():
        from modules.adjacency_gis.ingest_job import run_adjacency_gis_ingest

        run_adjacency_gis_ingest(trigger_source='manual', vendor=vendor)

    threading.Thread(target=_run, daemon=True).start()
    try:
        log_activity(
            (user.get('id') if isinstance(user, dict) else user[0]),
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


@admin_panel_bp.route('/api/admin/ret-credential-fallbacks', methods=['GET'])
def ret_credential_fallbacks():
    """RET accountability alerts: missing personal credentials or failed credential fallback."""
    user = get_current_user()
    if not _is_owner(user):
        return jsonify({'error': 'Owner access required'}), 403

    limit = min(max(int(request.args.get('limit') or 50), 1), 200)
    conn = get_db()
    rows = execute_query(conn, '''
        SELECT a.timestamp, a.action, a.details, a.user_id, u.username
        FROM activity_log a
        LEFT JOIN users u ON u.id = a.user_id
        WHERE a.action IN ('ret_credential_fallback', 'ret_missing_credentials')
        ORDER BY a.timestamp DESC
        LIMIT ?
    ''', (limit,)).fetchall()
    conn.close()
    return jsonify({
        'success': True,
        'items': [dict(row) for row in rows],
    })


_CM_ACTIVITY_ACTIONS = (
    'cm_extract_start',
    'cm_extract',
    'cm_extract_async',
    'cm_extract_fail',
    'cm_extract_download',
    'cm_job_create',
    'cm_job_delete',
    'cm_job_download',
)


@admin_panel_bp.route('/api/admin/cm-extract-activity', methods=['GET'])
def cm_extract_activity():
    """CM Extractor start/success/fail and job actions for Owner review."""
    user = get_current_user()
    if not _is_owner(user):
        return jsonify({'error': 'Owner access required'}), 403

    limit = min(max(int(request.args.get('limit') or 200), 1), 1000)
    placeholders = ','.join('?' for _ in _CM_ACTIVITY_ACTIONS)
    conn = get_db()
    rows = execute_query(conn, f'''
        SELECT a.timestamp, a.action, a.details, a.ip_address, a.user_id, u.username
        FROM activity_log a
        LEFT JOIN users u ON u.id = a.user_id
        WHERE a.action IN ({placeholders})
        ORDER BY a.timestamp DESC
        LIMIT ?
    ''', (*_CM_ACTIVITY_ACTIONS, limit)).fetchall()
    conn.close()
    return jsonify({
        'success': True,
        'items': [dict(row) for row in rows],
    })


_ACTIVITY_DEFAULT_LIMIT = 200
_ACTIVITY_MAX_LIMIT = 1000


@admin_panel_bp.route('/api/admin/activity')
def admin_recent_activity():
    """Return the platform-wide activity log (Owner only)."""
    user = get_current_user()
    if not _is_owner(user):
        return jsonify({'error': 'Owner access required'}), 403
    try:
        limit = int(request.args.get('limit') or _ACTIVITY_DEFAULT_LIMIT)
    except (TypeError, ValueError):
        limit = _ACTIVITY_DEFAULT_LIMIT
    limit = min(max(limit, 1), _ACTIVITY_MAX_LIMIT)
    conn = get_db()
    rows = execute_query(conn, '''
        SELECT a.timestamp, a.action, a.details, a.ip_address, a.user_id, u.username
        FROM activity_log a
        LEFT JOIN users u ON u.id = a.user_id
        ORDER BY a.timestamp DESC
        LIMIT ?
    ''', (limit,)).fetchall()
    conn.close()
    return jsonify({'success': True, 'activity': [dict(row) for row in rows]})


_EXPORT_TABLES_OWNER = frozenset({
    'sync_status',
    'sync_history',
    'ret_credential_alerts',
    'cm_extract_activity',
    'recent_activity',
})


@admin_panel_bp.route('/api/admin/export/excel', methods=['POST'])
@admin_required
def admin_export_excel():
    """Download an Admin Panel table view as Excel."""
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    table_key = str(data.get('table') or '').strip().lower()
    columns = [str(c) for c in (data.get('columns') or []) if str(c).strip()]
    rows = data.get('rows')
    if table_key not in _EXPORT_TABLES_OWNER:
        return jsonify({'error': 'Unknown export table'}), 400
    if not _is_owner(user):
        return jsonify({'error': 'Owner access required'}), 403
    if not isinstance(rows, list) or not rows:
        return jsonify({'error': 'No rows to export'}), 400

    report_title = str(data.get('report_title') or table_key.replace('_', ' ').title())
    sheet_title = str(data.get('sheet_title') or report_title)[:31]
    filename_stem = str(data.get('filename_stem') or f'Admin_{table_key}')
    meta = data.get('meta') if isinstance(data.get('meta'), dict) else {}
    column_labels = data.get('column_labels') if isinstance(data.get('column_labels'), dict) else {}

    try:
        workbook, filename = build_table_workbook(
            filename_stem=filename_stem,
            report_title=report_title,
            sheet_title=sheet_title,
            columns=columns,
            rows=rows,
            column_labels=column_labels,
            meta={
                **meta,
                'Exported By': (user.get('username') if isinstance(user, dict) else user[1]),
                'Row Count': len(rows),
            },
        )
        log_activity(
            (user.get('id') if isinstance(user, dict) else user[0]),
            'admin_table_export',
            f'Exported {table_key} ({len(rows)} rows)',
        )
        return send_file(
            workbook,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


# ── PM Plus aggregation rules (Owner) ───────────────────────────────────────

@admin_panel_bp.route('/api/admin/pm-plus/rules/families', methods=['GET'])
@admin_required
def api_pm_plus_rules_families():
    user = get_current_user()
    if not _is_owner(user):
        return jsonify({'success': False, 'error': 'Owner access required'}), 403
    try:
        from core.pm_plus.agg_rules import get_family_rules
        from core.pm_plus.schema import init_schema
        init_schema()
        return jsonify({'success': True, 'families': get_family_rules()})
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500


@admin_panel_bp.route('/api/admin/pm-plus/rules/families', methods=['POST'])
@admin_required
def api_pm_plus_rules_families_save():
    user = get_current_user()
    if not _is_owner(user):
        return jsonify({'success': False, 'error': 'Owner access required'}), 403
    body = request.get_json(silent=True) or {}
    family = (body.get('family') or '').strip()
    if not family:
        return jsonify({'success': False, 'error': 'family required'}), 400
    try:
        from core.pm_plus.agg_rules import upsert_family_rule
        from core.pm_plus.schema import init_schema
        init_schema()
        row = upsert_family_rule(
            family=family,
            time_agg=body.get('time_agg') or 'SUM',
            nw_agg=body.get('nw_agg') or 'SUM',
            ne_type=body.get('ne_type') or '',
            enabled=bool(body.get('enabled', True)),
        )
        return jsonify({'success': True, 'rule': row})
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500


@admin_panel_bp.route('/api/admin/pm-plus/rules/counters', methods=['GET'])
@admin_required
def api_pm_plus_rules_counters():
    user = get_current_user()
    if not _is_owner(user):
        return jsonify({'success': False, 'error': 'Owner access required'}), 403
    q = (request.args.get('q') or '').strip()
    family = (request.args.get('family') or '').strip()
    limit = min(2000, max(1, int(request.args.get('limit', 200))))
    try:
        from core.pm_plus.db import connect, fetchall
        from core.pm_plus.schema import init_schema
        init_schema()
        params: list = []
        sql = (
            "SELECT counter_id, family, display_name, time_agg, nw_agg, "
            "time_agg_override, nw_agg_override, agg_rule FROM dim_counter WHERE 1=1"
        )
        if q:
            sql += (
                " AND (counter_id LIKE ? OR COALESCE(display_name,'') LIKE ?"
                " OR COALESCE(family,'') LIKE ?)"
            )
            like = f"%{q}%"
            params.extend([like, like, like])
        if family:
            sql += " AND family = ?"
            params.append(family)
        sql += " ORDER BY counter_id LIMIT ?"
        params.append(limit)
        with connect() as conn:
            rows = fetchall(conn, sql, tuple(params))
        return jsonify({'success': True, 'counters': rows})
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500


@admin_panel_bp.route('/api/admin/pm-plus/rules/counters', methods=['POST'])
@admin_required
def api_pm_plus_rules_counters_save():
    user = get_current_user()
    if not _is_owner(user):
        return jsonify({'success': False, 'error': 'Owner access required'}), 403
    body = request.get_json(silent=True) or {}
    cid = (body.get('counter_id') or '').strip()
    if not cid:
        return jsonify({'success': False, 'error': 'counter_id required'}), 400
    try:
        from core.pm_plus.agg_rules import set_counter_override
        from core.pm_plus.schema import init_schema
        init_schema()
        if body.get('clear'):
            return jsonify({'success': True, **set_counter_override(counter_id=cid, clear=True)})
        return jsonify({
            'success': True,
            **set_counter_override(
                counter_id=cid,
                time_agg=body.get('time_agg'),
                nw_agg=body.get('nw_agg'),
            ),
        })
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500


@admin_panel_bp.route('/api/admin/pm-plus/catalog/import', methods=['POST'])
@admin_required
def api_pm_plus_catalog_import():
    """Upload Nokia ref_bts xlsx or import from server default path."""
    from pathlib import Path
    from werkzeug.utils import secure_filename

    user = get_current_user()
    if not _is_owner(user):
        return jsonify({'success': False, 'error': 'Owner access required'}), 403
    upload = request.files.get('file')
    if upload and upload.filename:
        dest = Path('raw/pm_plus/_debug') / secure_filename(upload.filename)
        dest.parent.mkdir(parents=True, exist_ok=True)
        upload.save(dest)
        path = dest
    else:
        body = request.get_json(silent=True) or {}
        path = Path(
            body.get('path')
            or 'raw/pm_plus/_debug/ref_bts_performance_measurements_24R3_24R2.xlsx'
        )
    if not path.exists():
        return jsonify({'success': False, 'error': f'file not found: {path}'}), 404
    try:
        from core.pm_plus.catalog_import import import_nokia_catalog
        result = import_nokia_catalog(path)
        log_activity(
            (user.get('id') if isinstance(user, dict) else user[0]),
            'pm_plus_catalog_import',
            f'Imported catalog {path.name}',
        )
        return jsonify({'success': True, **result, 'path': str(path)})
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500


@admin_panel_bp.route('/api/admin/pm-plus/rollup', methods=['POST'])
@admin_required
def api_pm_plus_rollup():
    user = get_current_user()
    if not _is_owner(user):
        return jsonify({'success': False, 'error': 'Owner access required'}), 403
    body = request.get_json(silent=True) or {}
    try:
        from core.pm_plus.rollup import apply_retention, rollup_all
        from core.pm_plus.schema import init_schema
        init_schema()
        out = {
            'rollup': rollup_all(
                ts_from=body.get('ts_from') or body.get('day_from'),
                ts_to=body.get('ts_to') or body.get('day_to'),
            )
        }
        if body.get('retention'):
            out['retention'] = apply_retention()
        return jsonify({'success': True, **out})
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500
