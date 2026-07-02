"""
CM Extractor Routes
Pull configuration data from Nokia NetAct CM Open API and Huawei U2020 MML API.
"""

from __future__ import annotations

import os
import tempfile
import threading
import uuid
from functools import wraps

from flask import Blueprint, g, jsonify, redirect, render_template, request, send_file, url_for

from core.cm_extractor.config import (
    huawei_configured,
    huawei_defaults,
    nokia_bulk_export_settings,
    nokia_configured,
    nokia_defaults,
    nokia_export_ssh_settings,
)
from core.cm_extractor.huawei_client import HuaweiCmClient, HuaweiCmError
from core.cm_extractor.huawei_discovery import (
    get_cached_discovery,
    refresh_discovery_cache,
)
from core.cm_extractor.huawei_semantics import (
    export_huawei_selection_to_excel,
    get_mo_object_catalog,
    get_parameters_for_object,
    preview_huawei_selection,
    resolve_ne_names_for_site_ids,
)
from core.cm_extractor.site_catalog import (
    list_huawei_areas,
    list_huawei_db_sites,
    resolve_huawei_ne_names,
    merge_huawei_ne_names,
)
from core.cm_extractor.nokia_client import NokiaCmClient, NokiaCmError
from core.cm_extractor.nokia_excel_reimport import (
    CONFIRMATION_PHRASE,
    create_preview as create_nokia_reimport_preview,
    execute_preview as execute_nokia_reimport_preview,
)
from core.cm_extractor.nokia_semantics import (
    export_nokia_selection_to_excel,
    fetch_parameters_for_classes,
    get_mo_class_catalog,
    preview_nokia_selection,
)
from core.cm_extractor.site_catalog import (
    list_nokia_areas,
    list_nokia_db_sites,
    list_nokia_inventory_areas,
    list_nokia_inventory_sites,
)
from core.cm_extractor.job_scheduler import (
    create_job as cm_create_job,
    delete_job as cm_delete_job,
    get_job as cm_get_job,
    get_run as cm_get_run,
    list_jobs as cm_list_jobs,
    list_runs as cm_list_runs,
    run_job as cm_run_job,
    set_enabled as cm_set_enabled,
)
from database_enhanced import get_user_by_session, log_activity

cm_extractor_bp = Blueprint(
    'cm_extractor',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/cm_extractor/static',
)

TEMP_FILES: dict[str, dict] = {}


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        session_token = request.cookies.get('session_token')
        if not session_token:
            return redirect(url_for('auth.login_page'))
        user = get_user_by_session(session_token)
        if not user:
            return redirect(url_for('auth.login_page'))
        request.current_user = user
        return f(*args, **kwargs)
    return decorated_function


def get_current_user():
    session_token = request.cookies.get('session_token')
    if session_token:
        return get_user_by_session(session_token)
    return None


def _user_role(user) -> str:
    if not user:
        return ''
    raw = user.get('role') if isinstance(user, dict) else user[6]
    return str(raw or '').strip().lower()


def _huawei_feature_enabled() -> bool:
    """Global on/off switch for the (in-development) Huawei CM workflow."""
    raw = (os.environ.get('CM_HUAWEI_ENABLED') or 'true').strip().lower()
    return raw not in ('0', 'false', 'no', 'off')


def huawei_visible(user) -> bool:
    """Huawei CM workflow is available to all authenticated users when the feature flag is on."""
    if not user:
        return False
    return _huawei_feature_enabled()


def huawei_user_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Unauthorized'}), 401
        if not huawei_visible(user):
            return jsonify({'error': 'Huawei CM extraction is not enabled.'}), 403
        return f(*args, **kwargs)
    return decorated


def huawei_admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Unauthorized'}), 401
        if not _huawei_feature_enabled():
            return jsonify({'error': 'Huawei CM extraction is not enabled.'}), 403
        if _user_role(user) != 'admin':
            return jsonify({'error': 'Administrator access required.'}), 403
        return f(*args, **kwargs)
    return decorated


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


def _user_id(user) -> int:
    return user.get('id') if isinstance(user, dict) else user[0]


def _username(user) -> str:
    if isinstance(user, dict):
        return str(user.get('username') or '').strip()
    return str(user[1] or '').strip()


def _cm_write_allowed_users() -> set[str]:
    raw = os.environ.get('CM_WRITE_ALLOWED_USERS') or 'malek.mohammad'
    return {item.strip().lower() for item in raw.split(',') if item.strip()}


def cm_write_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Unauthorized'}), 401
        if _username(user).lower() not in _cm_write_allowed_users():
            return jsonify({'error': 'CM write actions are currently restricted.'}), 403
        return f(*args, **kwargs)
    return decorated


def _json_body() -> dict:
    return getattr(g, 'sanitized_json', None) or request.get_json(silent=True) or {}


def _nokia_client(_data: dict | None = None) -> NokiaCmClient:
    """Nokia credentials are server-side only (.env); never taken from the browser."""
    defaults = nokia_defaults()
    if not nokia_configured():
        raise NokiaCmError(
            'Nokia NetAct CM is not configured. Set NOKIA_CM_HOST, NOKIA_CM_USER, '
            'and NOKIA_CM_PASSWORD in .env.'
        )
    return NokiaCmClient(
        host=defaults['host'],
        username=defaults['username'],
        password=defaults['password'],
        base_url=defaults.get('base_url') or '',
        use_https=defaults['use_https'],
        verify_ssl=defaults['verify_ssl'],
        timeout=defaults.get('timeout', 180),
        mo_batch_size=defaults.get('mo_batch_size', 150),
        batch_delay_sec=defaults.get('batch_delay_sec', 0.4),
        max_retries=defaults.get('max_retries', 8),
        retry_base_delay_sec=defaults.get('retry_base_delay_sec', 2.0),
    )


def _huawei_client(data: dict) -> HuaweiCmClient:
    defaults = huawei_defaults()
    port = data.get('port', defaults['port'])
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = defaults['port']
    return HuaweiCmClient(
        host=data.get('host') or defaults['host'],
        username=data.get('username') or defaults['username'],
        password=data.get('password') or defaults['password'],
        port=port,
        use_https=bool(data.get('use_https', defaults['use_https'])),
        verify_ssl=bool(data.get('verify_ssl', defaults['verify_ssl'])),
        api_style=data.get('api_style') or defaults.get('api_style', 'wireless'),
        client_ip=data.get('client_ip') or defaults.get('client_ip', ''),
        script_base_url=data.get('script_base_url') or defaults.get('script_base_url', ''),
    )


@cm_extractor_bp.route('/cm-extractor')
@login_required
def cm_extractor_page():
    user = get_current_user()
    return render_template(
        'cm_extractor.html',
        user=format_user_data(user),
        huawei_enabled=huawei_visible(user),
        cm_write_allowed=_username(user).lower() in _cm_write_allowed_users(),
    )


@cm_extractor_bp.route('/api/cm-extractor/defaults')
def api_defaults():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    bulk = nokia_bulk_export_settings()
    nokia_cfg = nokia_defaults()
    is_admin = _user_role(user) == 'admin'
    nokia_info = {
        'configured': nokia_configured(),
        'bulk_export_ssh': nokia_export_ssh_settings().get('configured', False),
        'bulk_operation_timeout_sec': bulk['operation_timeout_sec'],
    }
    huawei_cfg = huawei_defaults()
    huawei_info = {
        **{k: v for k, v in huawei_cfg.items() if k != 'password'},
        'password': '',
        'configured': huawei_configured(),
    }
    if is_admin:
        nokia_info.update({
            'host': nokia_cfg.get('host') or '',
            'username': nokia_cfg.get('username') or '',
            'base_url': nokia_cfg.get('base_url') or '',
        })
        huawei_info.update({
            'host': huawei_cfg.get('host') or '',
            'username': huawei_cfg.get('username') or '',
        })
    return jsonify({
        'nokia': nokia_info,
        'huawei': huawei_info,
        'is_admin': is_admin,
    })


@cm_extractor_bp.route('/api/cm-extractor/test-connection', methods=['POST'])
def test_connection():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = _json_body()
    vendor = (data.get('vendor') or '').lower()
    try:
        if vendor == 'nokia':
            client = _nokia_client(data)
            result = client.test_connection()
            return jsonify({'success': True, 'message': 'Connected to Nokia CM API', 'details': result})
        if vendor == 'huawei':
            if not huawei_visible(user):
                return jsonify({'error': 'Huawei CM extraction is not enabled.'}), 403
            client = _huawei_client(data)
            result = client.test_connection()
            return jsonify({'success': True, 'message': result.get('message', 'Connected'), 'details': result})
        return jsonify({'error': 'Unknown vendor'}), 400
    except (NokiaCmError, HuaweiCmError) as exc:
        return jsonify({'error': str(exc)}), 502
    except ConnectionError as exc:
        return jsonify({'error': str(exc)}), 502
    except Exception as exc:
        return jsonify({'error': f'Connection failed: {exc}'}), 500


def _nokia_selection_payload(data: dict) -> tuple[int, str, list[str], list[dict]]:
    conf_id = int(data.get('conf_id') or 1)
    scope_level = (data.get('scope_level') or 'MRBTS').strip().upper()
    site_ids = data.get('site_ids') or []
    if isinstance(site_ids, str):
        site_ids = [s.strip() for s in site_ids.split(',') if s.strip()]
    site_ids = [str(site_id).strip() for site_id in site_ids if str(site_id).strip()]
    selections = data.get('selections') or []
    if not site_ids:
        raise ValueError('Select at least one site id for the chosen scope')
    if not selections:
        raise ValueError('Select at least one managed object class and its parameters')
    return conf_id, scope_level, site_ids, selections


def _huawei_selection_payload(data: dict) -> tuple[list[str], list[dict], list[dict[str, str]]]:
    site_ids = data.get('site_ids') or []
    if isinstance(site_ids, str):
        site_ids = [s.strip() for s in site_ids.split(',') if s.strip()]
    site_ids = [str(site_id).strip() for site_id in site_ids if str(site_id).strip()]

    ne_names = data.get('ne_names') or []
    if isinstance(ne_names, str):
        ne_names = [n.strip() for n in ne_names.split(',') if n.strip()]
    ne_names = [str(name).strip() for name in ne_names if str(name).strip()]

    scope_level = (data.get('scope_level') or 'ENODEB').strip().upper()

    skipped: list[dict[str, str]] = []
    if not ne_names and site_ids:
        ne_names, unresolved, _alternates, skipped = resolve_huawei_ne_names(site_ids, scope_level=scope_level)
    else:
        ne_names, unresolved, _alternates, skipped = merge_huawei_ne_names(
            site_ids,
            ne_names,
            scope_level=scope_level,
        )

    if unresolved:
        preview = ', '.join(unresolved[:8])
        suffix = '…' if len(unresolved) > 8 else ''
        raise ValueError(
            f'Could not map site id(s) to U2020 NE name: {preview}{suffix}. '
            'Ensure metadata site_name is the OSS meName (e.g. 2222-UL_Site_Name_IBS_M), '
            'or pick NEs from the list after it loads (Sync NEs is optional for IBS sites).',
        )
    if not ne_names and not skipped:
        raise ValueError('Select at least one network element')

    selections = data.get('selections') or []
    if not selections:
        command = (data.get('command') or '').strip()
        if command:
            selections = [{'mo_id': 'CUSTOM', 'command': command, 'export_all': True}]
        else:
            raise ValueError('Select at least one MO object type and its parameters')
    return ne_names, selections, skipped


@cm_extractor_bp.route('/api/cm-extractor/nokia/sites', methods=['GET'])
def nokia_sites():
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    query = (request.args.get('q') or '').strip()
    scope_level = (request.args.get('scope') or 'MRBTS').strip().upper()
    try:
        limit = int(request.args.get('limit') or 2000)
    except (TypeError, ValueError):
        limit = 2000

    try:
        sites, source = list_nokia_inventory_sites(query, scope_level=scope_level, limit=limit)
        return jsonify({
            'success': True,
            'sites': sites,
            'count': len(sites),
            'scope_level': scope_level,
            'source': source,
        })
    except Exception as exc:
        return jsonify({'success': False, 'error': f'Failed to load Nokia sites: {exc}'}), 500


@cm_extractor_bp.route('/api/cm-extractor/nokia/areas', methods=['GET'])
def nokia_areas():
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    scope_level = (request.args.get('scope') or 'MRBTS').strip().upper()
    try:
        areas = list_nokia_inventory_areas(scope_level=scope_level)
        return jsonify({
            'success': True,
            'areas': areas,
            'count': len(areas),
            'scope_level': scope_level,
        })
    except Exception as exc:
        return jsonify({'success': False, 'error': f'Failed to load areas: {exc}'}), 500


@cm_extractor_bp.route('/api/cm-extractor/nokia/discover', methods=['POST'])
def nokia_discover():
    """Force a NetAct inventory discovery + cache refresh (also runs on a schedule)."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        from core.cm_extractor.nokia_discovery import refresh_nokia_inventory_cache

        client = _nokia_client()
        result = refresh_nokia_inventory_cache(client)
        return jsonify({
            'success': True,
            'counts': result.get('counts', {}),
            'errors': result.get('errors', {}),
            'message': (
                'Discovered NEs from NetAct: '
                + ', '.join(f'{k}={v}' for k, v in (result.get('counts') or {}).items())
            ),
        })
    except NokiaCmError as exc:
        return jsonify({'error': str(exc)}), 502
    except ConnectionError as exc:
        return jsonify({'error': str(exc)}), 502
    except Exception as exc:
        return jsonify({'error': f'NetAct discovery failed: {exc}'}), 500


def _reimport_max_changes() -> int:
    try:
        return max(1, int(os.environ.get('NOKIA_CM_REIMPORT_MAX_CHANGES', '100')))
    except ValueError:
        return 100


@cm_extractor_bp.route('/api/cm-extractor/nokia/reimport/preview', methods=['POST'])
@cm_write_required
def nokia_reimport_preview():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    upload = request.files.get('workbook')
    if not upload or not upload.filename:
        return jsonify({'error': 'Upload the edited Nokia Excel workbook.'}), 400
    if not upload.filename.lower().endswith(('.xlsx', '.xlsm')):
        return jsonify({'error': 'Only .xlsx/.xlsm workbooks are supported.'}), 400

    baseline_file_id = (request.form.get('baseline_file_id') or '').strip()
    baseline_info = TEMP_FILES.get(baseline_file_id)
    if not baseline_info or baseline_info.get('user_id') != _user_id(user):
        return jsonify({
            'error': 'Original baseline export not found. Export the Nokia Excel file again, then upload your edited copy in the same session.',
        }), 400
    baseline_path = baseline_info.get('path')
    if not baseline_path or not os.path.isfile(baseline_path):
        return jsonify({'error': 'Original baseline export file is no longer available.'}), 400

    allow_blank = (request.form.get('allow_blank') or '').strip().lower() in ('1', 'true', 'yes', 'on')
    suffix = '.xlsm' if upload.filename.lower().endswith('.xlsm') else '.xlsx'
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.close()
    try:
        upload.save(tmp.name)
        preview = create_nokia_reimport_preview(
            username=_username(user),
            baseline_path=baseline_path,
            edited_path=tmp.name,
            edited_filename=upload.filename,
            allow_blank=allow_blank,
            max_changes=_reimport_max_changes(),
        )
    except Exception as exc:
        return jsonify({'error': f'Could not preview Nokia Excel reimport: {exc}'}), 400
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    log_activity(
        _user_id(user),
        'cm_nokia_reimport_preview',
        f"Previewed Nokia Excel reimport {preview['token']} with {preview['change_count']} change(s)",
    )
    return jsonify({
        'success': True,
        'confirmation': CONFIRMATION_PHRASE,
        **{
            key: preview[key]
            for key in (
                'token', 'edited_filename', 'change_count', 'blocked_count',
                'changes', 'blocked', 'warnings', 'executable',
            )
        },
    })


@cm_extractor_bp.route('/api/cm-extractor/nokia/reimport/execute', methods=['POST'])
@cm_write_required
def nokia_reimport_execute():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    data = _json_body()
    token = str(data.get('token') or '').strip()
    confirmation = str(data.get('confirmation') or '').strip()
    if not token:
        return jsonify({'error': 'Preview token is required.'}), 400
    if confirmation != CONFIRMATION_PHRASE:
        return jsonify({'error': f'Type {CONFIRMATION_PHRASE} to execute these Nokia changes.'}), 400
    wait = str(data.get('wait') or '').strip().lower() in ('1', 'true', 'yes', 'on')
    try:
        result = execute_nokia_reimport_preview(_username(user), token, wait=wait)
    except FileNotFoundError as exc:
        return jsonify({'error': str(exc)}), 404
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'error': f'Nokia Excel reimport execution failed: {exc}'}), 502

    log_activity(
        _user_id(user),
        'cm_nokia_reimport_execute',
        f"Executed Nokia Excel reimport {token}: operation {result.get('operation_id')}",
    )
    return jsonify({'success': True, **result})


@cm_extractor_bp.route('/api/cm-extractor/huawei/sites', methods=['GET'])
@huawei_user_required
def huawei_sites():
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    query = (request.args.get('q') or '').strip()
    scope_level = (request.args.get('scope') or 'ENODEB').strip().upper()
    refresh = (request.args.get('refresh') or '').strip().lower() in ('1', 'true', 'yes')
    if refresh and _user_role(user) != 'admin':
        return jsonify({
            'success': False,
            'error': 'Only administrators can sync NE names from U2020.',
        }), 403
    try:
        limit = int(request.args.get('limit') or 2000)
    except (TypeError, ValueError):
        limit = 2000

    discovery_meta = None
    try:
        if refresh:
            client = _huawei_client({})
            discovery_meta = refresh_discovery_cache(
                client,
                include_history=False,
                discover_mos=False,
            )
        sites = list_huawei_db_sites(query, scope_level=scope_level, limit=limit)
        cache = get_cached_discovery(max_age_sec=10**9)
        resolved_count = sum(1 for site in sites if site.get('u2020_resolved'))
        response = {
            'success': True,
            'sites': sites,
            'count': len(sites),
            'scope_level': scope_level,
            'u2020_catalog_size': len((cache or {}).get('nes') or []),
            'u2020_resolved_in_list': resolved_count,
        }
        if discovery_meta:
            response['discovery'] = {
                'ne_count': discovery_meta.get('ne_count', 0),
                'site_id_count': discovery_meta.get('site_id_count', 0),
                'sample_ne': discovery_meta.get('sample_ne', ''),
            }
        return jsonify(response)
    except HuaweiCmError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 502
    except ConnectionError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 502
    except Exception as exc:
        return jsonify({'success': False, 'error': f'Failed to load Huawei NEs: {exc}'}), 500


@cm_extractor_bp.route('/api/cm-extractor/huawei/areas', methods=['GET'])
@huawei_user_required
def huawei_areas():
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    scope_level = (request.args.get('scope') or 'ENODEB').strip().upper()
    try:
        areas = list_huawei_areas(scope_level=scope_level)
        return jsonify({
            'success': True,
            'areas': areas,
            'count': len(areas),
            'scope_level': scope_level,
        })
    except Exception as exc:
        return jsonify({'success': False, 'error': f'Failed to load areas: {exc}'}), 500


@cm_extractor_bp.route('/api/cm-extractor/huawei/discover', methods=['POST'])
@huawei_admin_required
def huawei_discover():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = _json_body()
    include_history = bool(data.get('include_history', False))
    discover_mos = bool(data.get('discover_mos', True))
    sample_ne = (data.get('sample_ne') or '').strip()

    try:
        client = _huawei_client(data)
        result = refresh_discovery_cache(
            client,
            include_history=include_history,
            discover_mos=discover_mos,
            sample_ne_for_mo=sample_ne,
        )
        nes = result.get('nes') or []
        mo_catalog = result.get('mo_catalog') or []
        product_samples = result.get('product_samples') or {}
        return jsonify({
            'success': True,
            'ne_count': result.get('ne_count', len(nes)),
            'site_id_count': result.get('site_id_count', 0),
            'sample_ne': result.get('sample_ne', ''),
            'sample_nes': [row['ne_name'] for row in nes[:15]],
            'mo_object_count': len(mo_catalog),
            'mo_catalog': mo_catalog,
            'product_samples': product_samples,
            'message': (
                f'Discovered {result.get("ne_count", 0)} NE name(s) and '
                f'{len(mo_catalog)} executable MML object type(s) '
                f'across {len(product_samples)} product type(s).'
            ),
        })
    except HuaweiCmError as exc:
        return jsonify({'error': str(exc)}), 502
    except ConnectionError as exc:
        return jsonify({'error': str(exc)}), 502
    except Exception as exc:
        return jsonify({'error': f'Discovery failed: {exc}'}), 500


@cm_extractor_bp.route('/api/cm-extractor/huawei/mo-objects', methods=['GET'])
@huawei_user_required
def huawei_mo_objects():
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    from core.cm_extractor.huawei_discovery import get_cached_discovery, load_discovery_from_disk

    load_discovery_from_disk()
    cache = get_cached_discovery(max_age_sec=10**9) or {}
    items = get_mo_object_catalog()
    catalog_source = items[0].get('source') if items else 'builtin'
    return jsonify({
        'success': True,
        'mo_objects': items,
        'count': len(items),
        'discovered': bool(cache.get('mo_catalog')),
        'catalog_source': catalog_source,
        'product_samples': cache.get('product_samples') or {},
    })


@cm_extractor_bp.route('/api/cm-extractor/huawei/rebuild-dictionary', methods=['POST'])
@huawei_admin_required
def huawei_rebuild_dictionary():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        from core.cm_extractor.huawei_param_dict import load_catalog

        result = load_catalog(rebuild=True)
        return jsonify({
            'success': True,
            'mo_count': result.get('mo_count', 0),
            'param_count': result.get('param_count', 0),
            'message': (
                f"Built read-only MO catalog from the parameter dictionary: "
                f"{result.get('mo_count', 0)} MO type(s) (LST/DSP), "
                f"{result.get('param_count', 0)} parameter(s)."
            ),
        })
    except Exception as exc:
        return jsonify({'error': f'Dictionary rebuild failed: {exc}'}), 500


@cm_extractor_bp.route('/api/cm-extractor/huawei/parameters', methods=['POST'])
@huawei_user_required
def huawei_parameters():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = _json_body()
    mo_ids = data.get('mo_ids') or data.get('mo_objects') or []
    if isinstance(mo_ids, str):
        mo_ids = [mo_ids]
    if not mo_ids:
        return jsonify({'error': 'mo_ids is required'}), 400

    by_object: dict[str, list] = {}
    for mo_id in mo_ids:
        try:
            by_object[str(mo_id).strip().upper()] = get_parameters_for_object(str(mo_id))
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
    return jsonify({'success': True, 'parameters': by_object})


@cm_extractor_bp.route('/api/cm-extractor/huawei/preview', methods=['POST'])
@huawei_user_required
def huawei_preview():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = _json_body()
    try:
        ne_names, selections, skipped = _huawei_selection_payload(data)
        client = _huawei_client(data)
        result = preview_huawei_selection(client, ne_names=ne_names, selections=selections)
        if skipped:
            result.setdefault('warnings', [])
            preview = ', '.join(row['NE name'] for row in skipped[:8])
            suffix = '…' if len(skipped) > 8 else ''
            result['warnings'].append(
                f'Skipped {len(skipped)} NE(s) without Huawei 4G inventory: {preview}{suffix}',
            )
        return jsonify({'success': True, **result})
    except HuaweiCmError as exc:
        return jsonify({'error': str(exc)}), 502
    except ConnectionError as exc:
        return jsonify({'error': str(exc)}), 502
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400


@cm_extractor_bp.route('/api/cm-extractor/nokia/mo-classes', methods=['GET'])
def nokia_mo_classes():
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    scope_level = (request.args.get('scope') or 'MRBTS').strip().upper()
    try:
        client = _nokia_client()
        items = get_mo_class_catalog(client, scope_level=scope_level)
        return jsonify({'success': True, 'mo_classes': items, 'count': len(items), 'scope_level': scope_level})
    except NokiaCmError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 502
    except ConnectionError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 502
    except Exception as exc:
        return jsonify({'success': False, 'error': f'Failed to load MO classes: {exc}'}), 500


@cm_extractor_bp.route('/api/cm-extractor/nokia/parameters', methods=['POST'])
def nokia_parameters():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = _json_body()
    mo_classes = data.get('mo_classes') or []
    if not mo_classes:
        return jsonify({'error': 'mo_classes is required'}), 400

    try:
        client = _nokia_client()
        by_class = fetch_parameters_for_classes(client, mo_classes)
        return jsonify({'success': True, 'parameters': by_class})
    except NokiaCmError as exc:
        return jsonify({'error': str(exc)}), 502
    except ConnectionError as exc:
        return jsonify({'error': str(exc)}), 502
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400


@cm_extractor_bp.route('/api/cm-extractor/nokia/preview', methods=['POST'])
def nokia_preview():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = _json_body()
    try:
        conf_id, scope_level, site_ids, selections = _nokia_selection_payload(data)
        client = _nokia_client()
        result = preview_nokia_selection(
            client,
            selections=selections,
            site_ids=site_ids,
            scope_level=scope_level,
            conf_id=conf_id,
        )
        return jsonify({'success': True, **result})
    except NokiaCmError as exc:
        return jsonify({'error': str(exc)}), 502
    except ConnectionError as exc:
        return jsonify({'error': str(exc)}), 502
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400


@cm_extractor_bp.route('/api/cm-extractor/extract', methods=['POST'])
def extract():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = _json_body()
    vendor = (data.get('vendor') or '').lower()
    file_id = str(uuid.uuid4())
    output_path = os.path.join(tempfile.gettempdir(), f'cm_extract_{file_id}.xlsx')

    try:
        warnings: list[str] = []
        if vendor == 'nokia':
            conf_id, scope_level, site_ids, selections = _nokia_selection_payload(data)
            client = _nokia_client()
            row_count, sheet_names, summary = export_nokia_selection_to_excel(
                client,
                output_path,
                selections=selections,
                site_ids=site_ids,
                scope_level=scope_level,
                conf_id=conf_id,
            )
            label = f'Nokia CM ({row_count} rows, {len(sheet_names)} sheets)'
            mode = (
                'bulk_operations'
                if scope_level in ('RNC', 'BSC') and nokia_export_ssh_settings().get('configured')
                else 'selection'
            )

        elif vendor == 'huawei':
            if not huawei_visible(user):
                return jsonify({'error': 'Huawei CM extraction is not enabled.'}), 403
            ne_names, selections, skipped = _huawei_selection_payload(data)
            client = _huawei_client(data)

            if len(selections) == 1 and selections[0].get('mo_id') == 'CUSTOM':
                command = (selections[0].get('command') or data.get('command') or '').strip()
                if not command:
                    return jsonify({'error': 'MML command is required'}), 400
                client.clear_skipped_mml_nes()
                for row in skipped:
                    client._record_skipped_mml_nes([row['NE name']], reason=row['Reason'])
                rows = client.run_mml_chunked(command, ne_names) if ne_names else []
                mml_errors = client.consume_mml_errors()
                skipped_nes = client.consume_skipped_mml_nes()
                if not rows and mml_errors and not skipped_nes:
                    raise HuaweiCmError('; '.join(mml_errors[:5]))
                from core.cm_extractor.excel_writer import write_huawei_sheets_excel
                sheets = {'MML_Result': rows}
                sheet_names = ['MML_Result']
                warnings = [f'MML: {err}' for err in mml_errors]
                if skipped_nes:
                    sheets['Skipped_NEs'] = skipped_nes
                    sheet_names.append('Skipped_NEs')
                    preview = ', '.join(row['NE name'] for row in skipped_nes[:8])
                    suffix = '…' if len(skipped_nes) > 8 else ''
                    warnings.append(f'Skipped {len(skipped_nes)} NE(s) — see Skipped_NEs sheet ({preview}{suffix}).')
                write_huawei_sheets_excel(output_path, sheets)
                row_count = len(rows)
                summary = f'Huawei MML custom command on {len(ne_names)} NE(s), {row_count} row(s).'
            else:
                row_count, sheet_names, summary, warnings = export_huawei_selection_to_excel(
                    client,
                    output_path,
                    ne_names=ne_names,
                    selections=selections,
                    pre_skipped_nes=skipped,
                )
            label = f'Huawei MML ({row_count} rows, {len(sheet_names)} sheets)'
            mode = 'selection'
        else:
            return jsonify({'error': 'Unknown vendor'}), 400

        filename = f'{vendor}_cm_extract.xlsx'
        TEMP_FILES[file_id] = {
            'path': output_path,
            'filename': filename,
            'user_id': _user_id(user),
        }
        log_activity(_user_id(user), 'cm_extract', label)
        response = {
            'success': True,
            'file_id': file_id,
            'filename': filename,
            'row_count': row_count,
        }
        if vendor in ('nokia', 'huawei'):
            response['summary'] = summary
            response['sheet_names'] = sheet_names
            response['extraction_mode'] = mode
        if vendor == 'huawei' and warnings:
            response['warnings'] = warnings
        return jsonify(response)

    except (NokiaCmError, HuaweiCmError) as exc:
        return jsonify({'error': str(exc)}), 502
    except ConnectionError as exc:
        return jsonify({'error': str(exc)}), 502
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception:
        return jsonify({'error': 'Extraction failed'}), 500


def _can_manage_job(user, job) -> bool:
    if _user_role(user) == 'admin':
        return True
    if not int(job.get('user_specific', 1) or 0):
        return False
    return job.get('created_by') == _user_id(user)


@cm_extractor_bp.route('/api/cm-extractor/jobs', methods=['GET'])
def list_scheduled_jobs():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    is_admin = _user_role(user) == 'admin'
    jobs = cm_list_jobs(user_id=_user_id(user), include_all=is_admin)
    # Don't leak stored payloads wholesale; expose a compact summary per job.
    for job in jobs:
        payload = job.pop('payload', {}) or {}
        job.pop('payload_json', None)
        job['site_count'] = len(payload.get('site_ids') or [])
        job['mo_count'] = len(payload.get('selections') or [])
        job['scope_level'] = payload.get('scope_level')
    return jsonify({
        'success': True,
        'jobs': jobs,
        'is_admin': is_admin,
        'current_username': _username(user),
        'huawei_enabled': huawei_visible(user),
    })


@cm_extractor_bp.route('/api/cm-extractor/jobs', methods=['POST'])
def create_scheduled_job():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = _json_body()
    payload = data.get('payload') or {}
    vendor = (payload.get('vendor') or data.get('vendor') or '').lower()
    payload['vendor'] = vendor
    if vendor == 'huawei' and not huawei_visible(user):
        return jsonify({'error': 'Huawei CM extraction is not enabled.'}), 403
    if vendor not in ('nokia', 'huawei'):
        return jsonify({'error': 'Unknown vendor'}), 400
    if not (payload.get('site_ids') or payload.get('ne_names')):
        return jsonify({'error': 'Select at least one site/NE before scheduling.'}), 400
    if not payload.get('selections'):
        return jsonify({'error': 'Select at least one MO and its parameters before scheduling.'}), 400

    try:
        raw_specific = data.get('user_specific')
        user_specific = True if raw_specific is None else bool(raw_specific)
        if _user_role(user) != 'admin':
            user_specific = True

        job_id = cm_create_job(
            name=(data.get('name') or '').strip(),
            vendor=vendor,
            payload=payload,
            schedule_type=(data.get('schedule_type') or '').lower(),
            schedule_time=(data.get('schedule_time') or '').strip(),
            schedule_days=(data.get('schedule_days') or '').strip(),
            interval_hours=data.get('interval_hours'),
            run_at=(data.get('run_at') or '').strip(),
            keep_runs=int(data.get('keep_runs') or 5),
            created_by=_user_id(user),
            owner_username=_username(user),
            user_specific=user_specific,
            storage_subpath=(data.get('storage_subpath') or data.get('optional_path') or '').strip(),
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'error': f'Could not create job: {exc}'}), 500

    log_activity(
        _user_id(user),
        'cm_job_create',
        f'Created CM scheduled job {job_id} ({vendor}) for {_username(user)}',
    )
    return jsonify({'success': True, 'job_id': job_id})


@cm_extractor_bp.route('/api/cm-extractor/jobs/<int:job_id>', methods=['DELETE'])
def delete_scheduled_job(job_id: int):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    job = cm_get_job(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    if not _can_manage_job(user, job):
        return jsonify({'error': 'You can only manage your own jobs.'}), 403
    cm_delete_job(job_id)
    log_activity(_user_id(user), 'cm_job_delete', f'Deleted CM scheduled job {job_id}')
    return jsonify({'success': True})


@cm_extractor_bp.route('/api/cm-extractor/jobs/<int:job_id>/toggle', methods=['POST'])
def toggle_scheduled_job(job_id: int):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    job = cm_get_job(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    if not _can_manage_job(user, job):
        return jsonify({'error': 'You can only manage your own jobs.'}), 403
    enabled = bool(_json_body().get('enabled'))
    cm_set_enabled(job_id, enabled)
    return jsonify({'success': True, 'enabled': enabled})


@cm_extractor_bp.route('/api/cm-extractor/jobs/<int:job_id>/run-now', methods=['POST'])
def run_scheduled_job_now(job_id: int):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    job = cm_get_job(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    if not _can_manage_job(user, job):
        return jsonify({'error': 'You can only manage your own jobs.'}), 403
    if job['vendor'] == 'huawei' and not huawei_visible(user):
        return jsonify({'error': 'Huawei CM extraction is not enabled.'}), 403

    actor_id = _user_id(user)
    threading.Thread(
        target=cm_run_job,
        args=(job_id,),
        kwargs={'trigger': 'manual', 'actor_id': actor_id, 'advance_schedule': False},
        daemon=True,
    ).start()
    return jsonify({'success': True, 'message': 'Run started. Refresh the run history to see progress.'})


@cm_extractor_bp.route('/api/cm-extractor/jobs/<int:job_id>/runs', methods=['GET'])
def list_scheduled_job_runs(job_id: int):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    job = cm_get_job(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    if not _can_manage_job(user, job):
        return jsonify({'error': 'You can only view your own jobs.'}), 403
    runs = cm_list_runs(job_id)
    for run in runs:
        run.pop('file_path', None)
        run['has_file'] = bool(run.get('file_name'))
    return jsonify({'success': True, 'runs': runs})


@cm_extractor_bp.route('/api/cm-extractor/jobs/runs/<int:run_id>/download', methods=['GET'])
def download_scheduled_run(run_id: int):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    run = cm_get_run(run_id)
    if not run or not run.get('file_path'):
        return jsonify({'error': 'Result file not found'}), 404
    job = cm_get_job(run['job_id'])
    if not job or not _can_manage_job(user, job):
        return jsonify({'error': 'You can only download your own results.'}), 403
    if not os.path.isfile(run['file_path']):
        return jsonify({'error': 'Result file is no longer available (retention).'}), 404
    log_activity(_user_id(user), 'cm_job_download', f'Downloaded CM job run {run_id}')
    return send_file(run['file_path'], as_attachment=True, download_name=run.get('file_name') or 'cm_extract.xlsx')


@cm_extractor_bp.route('/api/cm-extractor/download/<file_id>')
def download(file_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    info = TEMP_FILES.get(file_id)
    if not info or info.get('user_id') != _user_id(user):
        return jsonify({'error': 'File not found'}), 404

    log_activity(_user_id(user), 'file_download', f'Downloaded {info["filename"]}')
    return send_file(info['path'], as_attachment=True, download_name=info['filename'])
