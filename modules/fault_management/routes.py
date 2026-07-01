"""Fault Management routes for live OSS alarm views."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from core.cm_extractor.config import (
    huawei_defaults,
    nokia_fm_configured,
    nokia_fm_defaults,
    nokia_fm_missing_settings,
)
from core.cm_extractor.http_util import build_ssl_context, format_connection_error, request_json
from core.cm_extractor.huawei_client import HuaweiCmClient, HuaweiCmError
from core.cm_extractor.huawei_discovery import fetch_fm_alarms
from database_enhanced import get_user_by_session

fault_management_bp = Blueprint(
    'fault_management',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/fault-management/static',
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
    if isinstance(user, dict):
        return {
            'id': user.get('id'),
            'username': user.get('username'),
            'email': user.get('email'),
            'role': user.get('role'),
        }
    return {
        'id': user[0],
        'username': user[1],
        'email': user[2],
        'role': user[6],
    }


def _huawei_client(data: dict | None = None) -> HuaweiCmClient:
    data = dict(data or {})
    defaults = huawei_defaults()
    try:
        port = int(data.get('port') or defaults['port'])
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


def _parse_alarm_time(value: object) -> datetime | None:
    text = str(value or '').strip()
    if not text:
        return None
    candidates = [
        text,
        text.replace('Z', '+00:00'),
        text.replace(' ', 'T'),
    ]
    for item in candidates:
        try:
            dt = datetime.fromisoformat(item)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _request_time_window(data: dict) -> tuple[datetime | None, datetime | None]:
    now = datetime.now(timezone.utc)
    end = _parse_alarm_time(data.get('end_time')) or now
    start = _parse_alarm_time(data.get('start_time'))
    if start:
        return start, end
    try:
        hours = float(data.get('period_hours') or 0)
    except (TypeError, ValueError):
        hours = 0
    if hours > 0:
        return end - timedelta(hours=min(hours, 24 * 31)), end
    return None, None


def _rfc3339(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _filter_alarms(alarms: list[dict], data: dict) -> list[dict]:
    ne_name = str(data.get('ne_name') or data.get('neName') or '').strip().lower()
    start, end = _request_time_window(data)
    out = []
    for alarm in alarms:
        if ne_name and ne_name not in str(alarm.get('me_name') or '').lower():
            continue
        if start or end:
            alarm_dt = _parse_alarm_time(alarm.get('occur_time'))
            if alarm_dt:
                if start and alarm_dt < start:
                    continue
                if end and alarm_dt > end:
                    continue
        out.append(alarm)
    return out


def _netact_fm_token_error_detail(status: int, raw_detail: str) -> str:
    """Turn Keycloak/OAuth failures into actionable setup guidance."""
    parsed: dict = {}
    try:
        maybe = json.loads(raw_detail or '')
        if isinstance(maybe, dict):
            parsed = maybe
    except json.JSONDecodeError:
        pass

    err = str(parsed.get('error') or '').strip()
    desc = str(parsed.get('error_description') or raw_detail or '').strip()
    if status == 401 and err == 'invalid_client':
        return (
            'NetAct FM OAuth client rejected (invalid_client). '
            'Create/register the FM API client on the fmapi-service node, then set '
            'NOKIA_FM_CLIENT_ID (and NOKIA_FM_CLIENT_SECRET only if the client is confidential): '
            '/opt/oss/fmapi-service/tools/api_client.sh --create-client <client_id>. '
            f'Current client_id={_netact_fm_defaults().get("client_id") or "(not set)"}. '
            f'Keycloak: {desc or "Invalid client or Invalid client credentials"}'
        )
    if status == 401 and err == 'invalid_grant':
        return (
            'NetAct FM user credentials rejected (invalid_grant). '
            'Check NOKIA_CM_USER / NOKIA_CM_PASSWORD (or NOKIA_FM_USER / NOKIA_FM_PASSWORD). '
            f'Keycloak: {desc or raw_detail}'
        )
    if desc:
        return desc
    return raw_detail or f'HTTP {status}'


def _netact_fm_defaults() -> dict:
    return nokia_fm_defaults()


def _netact_fm_configured(cfg: dict) -> bool:
    return not _netact_fm_missing_settings(cfg)


def _netact_fm_missing_settings(cfg: dict) -> list[str]:
    return nokia_fm_missing_settings(cfg)


def _netact_token(cfg: dict) -> str:
    token_payload = {
        'grant_type': 'password',
        'client_id': cfg['client_id'],
        'username': cfg['username'],
        'password': cfg['password'],
        'scope': 'openid',
    }
    if cfg.get('client_secret'):
        token_payload['client_secret'] = cfg['client_secret']
    form = urlencode(token_payload).encode('utf-8')
    req = Request(
        cfg['token_url'],
        data=form,
        headers={
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
        },
        method='POST',
    )
    try:
        with urlopen(req, timeout=cfg['timeout'], context=build_ssl_context(cfg['verify_ssl'])) as resp:
            payload = json.loads(resp.read().decode('utf-8', errors='replace') or '{}')
    except HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')
        message = _netact_fm_token_error_detail(exc.code, detail)
        raise RuntimeError(f'NetAct FM token request failed ({exc.code}): {message}') from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ConnectionError(format_connection_error(exc, url=cfg['token_url'], vendor='nokia')) from exc
    token = payload.get('access_token') if isinstance(payload, dict) else ''
    if not token:
        raise RuntimeError('NetAct FM token response did not include access_token.')
    return str(token)


def _netact_filter_model(data: dict) -> list[dict]:
    criteria: list[dict] = []
    data_type = (data.get('data_type') or data.get('dataType') or 'CURRENT').strip().upper()
    criteria.append({
        'attributeName': 'alarmState',
        'attributeValue': 'CLEARED' if data_type == 'HISTORY' else 'ACTIVE',
        'operator': 'EQ',
    })
    ne_name = str(data.get('ne_name') or data.get('neName') or '').strip()
    if ne_name:
        criteria.append({
            'attributeName': 'dn',
            'attributeValue': ne_name,
            'operator': 'CONTAINS',
        })
    start, end = _request_time_window(data)
    if start:
        criteria.append({
            'attributeName': 'alarmTime',
            'attributeValue': _rfc3339(start),
            'operator': 'GTE',
        })
    if end:
        criteria.append({
            'attributeName': 'alarmTime',
            'attributeValue': _rfc3339(end),
            'operator': 'LTE',
        })
    return [{'filterCriteria': criteria}]


def _netact_alarm_name(dn: object) -> str:
    text = str(dn or '').strip()
    if not text:
        return ''
    last = text.split('/')[-1]
    return last or text


def _map_netact_alarm(row: dict) -> dict:
    dn = row.get('dn') or row.get('agentDn') or ''
    return {
        'severity': row.get('perceivedSeverity') or row.get('originalSeverity') or '',
        'me_name': _netact_alarm_name(dn),
        'site_id': dn,
        'product_name': row.get('eventType') or '',
        'alarm_name': row.get('alarmText') or row.get('specificProblem') or f"Alarm {row.get('alarmID') or ''}".strip(),
        'occur_time': row.get('alarmTime') or row.get('lastUpdatedTime') or '',
        'location_info': row.get('agentDn') or dn,
        'probable_cause': row.get('probableCauseCode') or row.get('specificProblem') or '',
        'raw': row,
    }


def _fetch_netact_fm_alarms(data: dict) -> dict:
    cfg = _netact_fm_defaults()
    missing = _netact_fm_missing_settings(cfg)
    if missing:
        raise ValueError(
            'Nokia NetAct FM is not configured. Missing: ' + ', '.join(missing) + '. '
            'FM reuses the existing Nokia CM host/user/password; only NOKIA_FM_CLIENT_ID '
            'is FM-specific unless your Keycloak client also has a secret.'
        )
    try:
        limit = max(1, min(int(data.get('limit') or 200), 1000))
    except (TypeError, ValueError):
        limit = 200
    token = _netact_token(cfg)
    fields = [
        'alarmID', 'dn', 'agentDn', 'alarmTime', 'lastUpdatedTime', 'alarmState',
        'alarmText', 'perceivedSeverity', 'originalSeverity', 'eventType',
        'probableCauseCode', 'specificProblem', 'ackState', 'ackTime', 'ackUser',
        'clearTime', 'clearUser', 'additionalText1', 'additionalText2',
        'additionalText3', 'additionalText4', 'additionalText5', 'additionalText6',
        'additionalText7', 'correlatedAlarm', 'correlatingAlarm', 'originalAlarmID',
    ]
    body = {
        'size': limit,
        'fields': fields,
        'filterModel': _netact_filter_model(data),
        'responseTimezone': 'UTC',
    }
    status, payload = request_json(
        'POST',
        cfg['base_url'].rstrip('/') + '/alarm-search',
        headers={'Authorization': f'Bearer {token}', 'Accept': 'application/json'},
        body=body,
        timeout=cfg['timeout'],
        verify_ssl=cfg['verify_ssl'],
    )
    if not (200 <= status < 300) or not isinstance(payload, dict):
        raise RuntimeError(f'NetAct FM alarm search failed ({status}): {payload}')
    rows = (((payload.get('page') or {}).get('_data') or {}).get('pageResult') or [])
    if not isinstance(rows, list):
        rows = []
    alarms = [_map_netact_alarm(row) for row in rows if isinstance(row, dict)]
    return {
        'alarms': alarms,
        'count': len(alarms),
        'filtered_count': len(alarms),
        'raw': payload,
    }


@fault_management_bp.route('/fault-management')
@login_required
def fault_management_page():
    user = get_current_user()
    cfg = huawei_defaults()
    return render_template(
        'fault_management.html',
        user=format_user(user),
        huawei_configured=bool(cfg['host'] and cfg['username'] and cfg['password']),
        nokia_fm_configured=nokia_fm_configured(),
        nokia_fm_missing=nokia_fm_missing_settings(),
    )


@fault_management_bp.route('/api/fault-management/huawei/faults', methods=['POST'])
@login_required
def huawei_faults():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    try:
        limit = int(data.get('limit') or 200)
    except (TypeError, ValueError):
        limit = 200
    data_type = (data.get('data_type') or data.get('dataType') or 'CURRENT').strip().upper()
    marker = (data.get('marker') or '').strip()

    try:
        client = _huawei_client(data)
        result = fetch_fm_alarms(client, data_type=data_type, limit=limit, marker=marker)
        result['alarms'] = _filter_alarms(result.get('alarms') or [], data)
        result['filtered_count'] = len(result['alarms'])
        return jsonify({'success': True, **result})
    except HuaweiCmError as exc:
        return jsonify({'error': str(exc)}), 502
    except ConnectionError as exc:
        return jsonify({'error': str(exc)}), 502
    except Exception as exc:
        return jsonify({'error': f'FM alarm fetch failed: {exc}'}), 500


@fault_management_bp.route('/api/fault-management/nokia/faults', methods=['POST'])
@login_required
def nokia_faults():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    try:
        result = _fetch_netact_fm_alarms(data)
        return jsonify({'success': True, **result})
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc), 'configuration_required': True}), 400
    except ConnectionError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 502
    except Exception as exc:
        return jsonify({'success': False, 'error': f'NetAct FM alarm fetch failed: {exc}'}), 500
