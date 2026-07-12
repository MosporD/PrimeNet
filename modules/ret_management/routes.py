"""RET Management routes — view and edit antenna tilts via live CM APIs."""

from __future__ import annotations

import os
from functools import wraps
from typing import Any

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, url_for

from core.cm_extractor.config import huawei_configured, nokia_configured
from core.cm_extractor.extraction import build_huawei_client, build_nokia_client
from core.cm_extractor.huawei_client import HuaweiCmError
from core.cm_extractor.nokia_client import NokiaCmError
from core.cm_extractor.nokia_operations_client import NokiaOperationsError
from database_enhanced import get_user_by_session, log_activity
from modules.ret_management import logic as ret_logic

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
    return jsonify({
        'success': True,
        'nokia_configured': status['nokia_configured'],
        'huawei_configured': status['huawei_configured'],
        'huawei_enabled': _huawei_feature_enabled(),
        'cm_write_allowed': _cm_write_allowed(user),
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
        site_id = (request.args.get('site_id') or '').strip()
        ne_name = (request.args.get('ne_name') or '').strip()
        ne_name = ret_logic.resolve_huawei_ne(site_id, ne_name)

        client = build_huawei_client()
        client.login()
        rows, warnings = ret_logic.fetch_huawei_rets(client, ne_name=ne_name)

        return jsonify({
            'success': True,
            'vendor': 'huawei',
            'ne_name': ne_name,
            'site_id': site_id,
            'rows': rows,
            'columns': list(ret_logic.HUAWEI_TABLE_COLUMNS),
            'warnings': warnings,
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
        site_id = str(data.get('site_id') or '').strip()
        ne_name = ret_logic.resolve_huawei_ne(site_id, str(data.get('ne_name') or '').strip())
        client = build_huawei_client()
        client.login()
        result = ret_logic.apply_huawei_ret_update(
            client,
            ne_name=ne_name,
            device_no=str(data.get('device_no') or data.get('deviceNo') or ''),
            subunit_no=str(data.get('subunit_no') or data.get('subunitNo') or ''),
            tilt=str(data.get('tilt') or ''),
        )
        user = get_current_user()
        log_activity(
            _user_id(user),
            'ret_management_huawei_mod',
            f'MOD RETSUBUNIT on {ne_name} device={data.get("device_no")} subunit={data.get("subunit_no")} tilt={data.get("tilt")}',
        )
        return jsonify({'success': True, **result})
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


@ret_management_bp.route('/api/ret-management/nokia/lncel', methods=['GET'])
@login_required
def nokia_lncel_list():
    if not nokia_configured():
        return jsonify({'error': 'Nokia NetAct CM is not configured.'}), 400
    try:
        site_id = (request.args.get('site_id') or '').strip()
        conf_id = int(request.args.get('conf_id') or 1)
        client = build_nokia_client()
        rows, warnings = ret_logic.fetch_nokia_lncel_angles(
            client,
            site_id=site_id,
            conf_id=conf_id,
        )
        return jsonify({
            'success': True,
            'vendor': 'nokia',
            'site_id': site_id,
            'conf_id': conf_id,
            'rows': rows,
            'warnings': warnings,
        })
    except (NokiaCmError, ValueError) as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@ret_management_bp.route('/api/ret-management/nokia/lncel/update', methods=['POST'])
@login_required
@cm_write_required
def nokia_lncel_update():
    if not nokia_configured():
        return jsonify({'error': 'Nokia NetAct CM is not configured.'}), 400
    data = _json_body()
    try:
        updates = data.get('updates')
        if not isinstance(updates, list):
            updates = [data] if data.get('dist_name') or data.get('dn') else []
        user = get_current_user()
        result = ret_logic.apply_nokia_angle_changes(
            _username(user),
            updates,
            wait=bool(data.get('wait', True)),
        )
        log_activity(
            _user_id(user),
            'ret_management_nokia_angle',
            f'Updated LNCEL angle ({len(updates)} change(s))',
        )
        return jsonify({'success': True, **result})
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
                    'Provision_Mass_Modification on LNCEL angle — SFTP write access is not required.'
                ),
            }), 500
        return jsonify({'error': str(exc)}), 500
    except Exception as exc:
        current_app.logger.exception('Nokia RET apply failed')
        return jsonify({'error': str(exc)}), 500
