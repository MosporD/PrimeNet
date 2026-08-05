"""RET Management routes — view and edit antenna tilts via live CM APIs."""

from __future__ import annotations

import os
from functools import wraps
from typing import Any

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, send_file, url_for

from core.cm_extractor.config import huawei_configured, nokia_configured
from core.cm_extractor.extraction import build_nokia_client
from core.cm_extractor.huawei_client import HuaweiCmError
from core.cm_extractor.nokia_client import NokiaCmError
from core.cm_extractor.nokia_operations_client import NokiaOperationsError
from core.user_vendor_credentials import list_user_vendor_credential_status
from database_enhanced import get_user_by_session, log_activity
from modules.ret_management import logic as ret_logic
from modules.ret_management.credentials import (
    run_huawei_with_user_credentials,
    run_nokia_read_with_user_credentials,
    run_nokia_write_with_user_credentials,
)
from modules.ret_management.export import build_ret_workbook

ret_management_bp = Blueprint(
    'ret_management',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/ret-management/static',
)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        session_token = request.cookies.get('session_token')
        if not session_token:
            return redirect(url_for('auth.login_page'))
        user = get_user_by_session(session_token)
        if not user:
            return redirect(url_for('auth.login_page'))
        request.current_user = user
        return f(*args, **kwargs)
    return decorated


def get_current_user():
    session_token = request.cookies.get('session_token')
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


def _user_id(user) -> int:
    return user.get('id') if isinstance(user, dict) else user[0]


def _cm_write_allowed(user) -> bool:
    return bool(user)


def cm_write_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Unauthorized'}), 401
        if not _cm_write_allowed(user):
            return jsonify({'error': 'CM write actions are currently restricted.'}), 403
        return f(*args, **kwargs)
    return decorated


def _huawei_feature_enabled() -> bool:
    raw = (os.environ.get('CM_HUAWEI_ENABLED') or 'true').strip().lower()
    return raw not in ('0', 'false', 'no', 'off')


def _cred_activity_suffix(cred_meta: dict[str, Any]) -> str:
    if cred_meta.get('credential_fallback'):
        return f' [fallback: {cred_meta.get("fallback_account")}]'
    if cred_meta.get('credential_missing'):
        return f' [no personal credentials; shared: {cred_meta.get("fallback_account")}]'
    return ''


def _json_body() -> dict:
    return request.get_json(silent=True) or {}


def _normalize_vendor(value: str) -> str:
    vendor = (value or 'nokia').strip().lower()
    if vendor not in ('nokia', 'huawei'):
        raise ValueError('Vendor must be nokia or huawei')
    return vendor


@ret_management_bp.route('/ret-management')
@login_required
def ret_management_page():
    user = get_current_user()
    return render_template(
        'ret_management.html',
        user=format_user_data(user),
        huawei_enabled=_huawei_feature_enabled(),
        cm_write_allowed=_cm_write_allowed(user),
    )


@ret_management_bp.route('/api/ret-management/defaults', methods=['GET'])
@login_required
def ret_defaults():
    user = get_current_user()
    status = ret_logic.vendor_status()
    cred_status = list_user_vendor_credential_status(_user_id(user))
    return jsonify({
        'success': True,
        'nokia_configured': status['nokia_configured'],
        'huawei_configured': status['huawei_configured'],
        'huawei_enabled': _huawei_feature_enabled(),
        'cm_write_allowed': _cm_write_allowed(user),
        'user_credentials': cred_status,
    })


@ret_management_bp.route('/api/ret-management/nes', methods=['GET'])
@login_required
def ret_ne_list():
    try:
        vendor = _normalize_vendor(request.args.get('vendor', 'nokia'))
        query = (request.args.get('q') or '').strip()
        limit = int(request.args.get('limit') or 500)
        items = ret_logic.list_network_elements(vendor, query=query, limit=limit)
        return jsonify({'success': True, 'vendor': vendor, 'items': items})
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@ret_management_bp.route('/api/ret-management/huawei/rets', methods=['GET'])
@login_required
def huawei_ret_list():
    if not _huawei_feature_enabled():
        return jsonify({'error': 'Huawei CM is not enabled.'}), 403
    if not huawei_configured():
        return jsonify({'error': 'Huawei U2020 CM is not configured.'}), 400
    try:
        user = get_current_user()
        site_id = (request.args.get('site_id') or '').strip()
        ne_name = (request.args.get('ne_name') or '').strip()
        ne_name = ret_logic.resolve_huawei_ne(site_id, ne_name)

        def _load(client):
            client.login()
            return ret_logic.fetch_huawei_rets(client, ne_name=ne_name)

        (rows, warnings), cred_meta = run_huawei_with_user_credentials(
            _user_id(user),
            prime_username=_username(user),
            action=f'LST RETSUBUNIT on {ne_name}',
            operation=_load,
        )

        return jsonify({
            'success': True,
            'vendor': 'huawei',
            'ne_name': ne_name,
            'site_id': site_id,
            'rows': rows,
            'columns': list(ret_logic.HUAWEI_TABLE_COLUMNS),
            'warnings': warnings,
            **cred_meta,
        })
    except (HuaweiCmError, ValueError) as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@ret_management_bp.route('/api/ret-management/huawei/rets/update', methods=['POST'])
@login_required
@cm_write_required
def huawei_ret_update():
    if not _huawei_feature_enabled():
        return jsonify({'error': 'Huawei CM is not enabled.'}), 403
    if not huawei_configured():
        return jsonify({'error': 'Huawei U2020 CM is not configured.'}), 400
    data = _json_body()
    try:
        user = get_current_user()
        site_id = str(data.get('site_id') or '').strip()
        ne_name = ret_logic.resolve_huawei_ne(site_id, str(data.get('ne_name') or '').strip())
        device_no = str(data.get('device_no') or data.get('deviceNo') or '')
        subunit_no = str(data.get('subunit_no') or data.get('subunitNo') or '')
        tilt = str(data.get('tilt') or '')

        def _apply(client):
            client.login()
            return ret_logic.apply_huawei_ret_update(
                client,
                ne_name=ne_name,
                device_no=device_no,
                subunit_no=subunit_no,
                tilt=tilt,
            )

        result, cred_meta = run_huawei_with_user_credentials(
            _user_id(user),
            prime_username=_username(user),
            action=(
                f'MOD RETSUBUNIT on {ne_name} device={device_no} '
                f'subunit={subunit_no} tilt={tilt}'
            ),
            operation=_apply,
        )
        log_activity(
            _user_id(user),
            'ret_management_huawei_mod',
            (
                f'MOD RETSUBUNIT on {ne_name} device={device_no} subunit={subunit_no} '
                f'tilt={tilt}'
                + _cred_activity_suffix(cred_meta)
            ),
        )
        return jsonify({'success': True, **result, **cred_meta})
    except HuaweiCmError as exc:
        body: dict[str, Any] = {'error': str(exc)}
        payload = getattr(exc, 'payload', None)
        if isinstance(payload, dict):
            if payload.get('vendor_request'):
                body['vendor_request'] = payload['vendor_request']
            if payload.get('report'):
                body['report'] = payload['report']
        return jsonify(body), 400
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@ret_management_bp.route('/api/ret-management/nokia/retu', methods=['GET'])
@ret_management_bp.route('/api/ret-management/nokia/lncel', methods=['GET'])  # legacy alias
@login_required
def nokia_retu_list():
    if not nokia_configured():
        return jsonify({'error': 'Nokia NetAct CM is not configured.'}), 400
    try:
        user = get_current_user()
        site_id = (request.args.get('site_id') or '').strip()
        conf_id = 1  # Always live network for RET management

        def _load(client):
            return ret_logic.fetch_nokia_retu_angles(
                client,
                site_id=site_id,
                conf_id=conf_id,
            )

        (rows, warnings, mo_class), cred_meta = run_nokia_read_with_user_credentials(
            _user_id(user),
            prime_username=_username(user),
            action=f'RETU_R read on site {site_id or "all"}',
            operation=_load,
        )
        return jsonify({
            'success': True,
            'vendor': 'nokia',
            'site_id': site_id,
            'conf_id': conf_id,
            'mo_class': mo_class,
            'columns': list(ret_logic.NOKIA_DISPLAY_COLUMNS),
            'rows': rows,
            'warnings': warnings,
            **cred_meta,
        })
    except (NokiaCmError, ValueError) as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@ret_management_bp.route('/api/ret-management/nokia/retu/update', methods=['POST'])
@ret_management_bp.route('/api/ret-management/nokia/lncel/update', methods=['POST'])  # legacy alias
@login_required
@cm_write_required
def nokia_retu_update():
    if not nokia_configured():
        return jsonify({'error': 'Nokia NetAct CM is not configured.'}), 400
    data = _json_body()
    try:
        updates = data.get('updates')
        if not isinstance(updates, list):
            updates = [data] if data.get('dist_name') or data.get('dn') else []
        site_id = str(data.get('site_id') or '').strip()
        if site_id:
            for item in updates:
                if isinstance(item, dict) and not str(item.get('site_id') or '').strip():
                    item['site_id'] = site_id
        user = get_current_user()
        mo_class = str(data.get('mo_class') or '').strip() or None
        if not mo_class:
            try:
                mo_class = ret_logic.resolve_nokia_retu_mo_class(build_nokia_client())
            except Exception:
                mo_class = ret_logic.NOKIA_MO_CLASS_FALLBACK

        def _apply(ops_client):
            return ret_logic.apply_nokia_angle_changes(
                _username(user),
                updates,
                wait=bool(data.get('wait', True)),
                mo_class=mo_class,
                operations_client=ops_client,
            )

        result, cred_meta = run_nokia_write_with_user_credentials(
            _user_id(user),
            prime_username=_username(user),
            action=f'RETU angle update ({len(updates)} change(s)) on {mo_class}',
            operation=_apply,
        )
        log_activity(
            _user_id(user),
            'ret_management_nokia_angle',
            (
                f'Updated RETU angle via RETU_R read ({len(updates)} change(s)) on {mo_class}'
                + _cred_activity_suffix(cred_meta)
            ),
        )
        return jsonify({'success': True, 'mo_class': mo_class, **result, **cred_meta})
    except (NokiaCmError, NokiaOperationsError, ValueError, RuntimeError) as exc:
        return jsonify({'error': str(exc)}), 400
    except OSError as exc:
        current_app.logger.exception('Nokia RET apply failed with OS error')
        if getattr(exc, 'errno', None) == 13:
            return jsonify({
                'error': (
                    'Permission denied on the PrimeNet server (local filesystem/SFTP), '
                    'not a NetAct CM API rejection. RET apply uses Provision_Mass_Modification '
                    '(no file upload). Restart the Flask server, then hard-refresh the page. '
                    'If it persists, ask sys admins to confirm NOKIA_CM_USER can run '
                    'Provision_Mass_Modification on RETU angle — SFTP write access is not required.'
                ),
            }), 500
        return jsonify({'error': str(exc)}), 500
    except Exception as exc:
        current_app.logger.exception('Nokia RET apply failed')
        return jsonify({'error': str(exc)}), 500


@ret_management_bp.route('/api/ret-management/export/excel', methods=['POST'])
@login_required
def ret_export_excel():
    """Download the currently viewed RET table as an Excel workbook."""
    user = get_current_user()
    data = _json_body()
    try:
        rows = data.get('rows')
        if not isinstance(rows, list) or not rows:
            return jsonify({'error': 'No table rows to export. Load RET data first.'}), 400
        payload = {
            **data,
            'username': _username(user),
        }
        workbook, filename = build_ret_workbook(payload)
        log_activity(
            _user_id(user),
            'ret_management_export',
            (
                f'Exported RET Excel ({payload.get("vendor")}) '
                f'site={payload.get("site_id") or ""} rows={len(rows)}'
            ),
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
        current_app.logger.exception('RET Excel export failed')
        return jsonify({'error': str(exc)}), 500
