"""Per-user vendor credential resolution for RET management with shared-account fallback."""

from __future__ import annotations

import re
from typing import Any, Callable, TypeVar

from core.cm_extractor.config import build_nokia_operations_client, huawei_defaults, nokia_defaults
from core.cm_extractor.extraction import build_huawei_client, build_nokia_client
from core.cm_extractor.huawei_client import HuaweiCmClient, HuaweiCmError
from core.cm_extractor.nokia_client import NokiaCmClient, NokiaCmError
from core.cm_extractor.nokia_operations_client import NokiaOperationsClient, NokiaOperationsError
from core.user_vendor_credentials import get_user_vendor_credentials
from database_enhanced import log_activity

T = TypeVar('T')

FALLBACK_NOTICE = (
    'Your personal vendor credentials could not complete this action '
    '(login failed or insufficient permissions). The operation continued using '
    'the shared service account. An administrator has been notified — please '
    'verify your MantaRay / U2020 credentials in Profile settings.'
)

MISSING_CREDENTIALS_NOTICE = (
    'You have not configured your personal MantaRay / U2020 credentials. '
    'This action used the shared service account instead, so it cannot be '
    'attributed to your vendor account. An administrator has been notified — '
    'please add your credentials in Profile settings.'
)

_PERMISSION_MARKERS = (
    'permission denied',
    'insufficient permission',
    'not authorized',
    'no permission',
    'access denied',
    'credentials rejected',
    'unauthorized',
    '401',
    '94001',
    'invalid_grant',
    'authentication failed',
    'login failed',
)


def _message_for(exc: BaseException) -> str:
    return str(exc or '').strip()


def is_credential_or_permission_error(exc: BaseException) -> bool:
    status = getattr(exc, 'status', None)
    if status == 401 or status == 403:
        return True
    lower = _message_for(exc).lower()
    if any(marker in lower for marker in _PERMISSION_MARKERS):
        return True
    payload = getattr(exc, 'payload', None)
    if isinstance(payload, dict):
        for key in ('errors', 'feedbacks'):
            items = payload.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                text = ''
                if isinstance(item, dict):
                    text = ' '.join(
                        str(item.get(field) or '')
                        for field in ('title', 'details', 'report', 'result')
                    )
                else:
                    text = str(item)
                text_lower = text.lower()
                if any(marker in text_lower for marker in _PERMISSION_MARKERS):
                    return True
    return False


def build_huawei_client_for_user(user_id: int) -> HuaweiCmClient:
    creds = get_user_vendor_credentials(user_id, 'huawei')
    if creds:
        return build_huawei_client({
            'username': creds['username'],
            'password': creds['password'],
        })
    return build_huawei_client()


def build_nokia_client_for_user(user_id: int) -> NokiaCmClient:
    creds = get_user_vendor_credentials(user_id, 'nokia')
    if creds:
        cfg = nokia_defaults()
        return NokiaCmClient(
            host=cfg['host'],
            username=creds['username'],
            password=creds['password'],
            base_url=cfg.get('base_url') or '',
            use_https=cfg['use_https'],
            verify_ssl=cfg['verify_ssl'],
            timeout=cfg.get('timeout', 180),
            mo_batch_size=cfg.get('mo_batch_size', 150),
            batch_delay_sec=cfg.get('batch_delay_sec', 0.4),
            max_retries=cfg.get('max_retries', 8),
            retry_base_delay_sec=cfg.get('retry_base_delay_sec', 2.0),
        )
    return build_nokia_client()


def build_nokia_operations_client_for_user(user_id: int) -> NokiaOperationsClient:
    creds = get_user_vendor_credentials(user_id, 'nokia')
    if creds:
        return build_nokia_operations_client({
            'username': creds['username'],
            'password': creds['password'],
        })
    return build_nokia_operations_client()


def shared_account_label(vendor: str) -> str:
    vendor = (vendor or '').strip().lower()
    if vendor == 'huawei':
        return huawei_defaults().get('username') or 'shared U2020 account'
    return nokia_defaults().get('username') or 'shared MantaRay account'


def flag_credential_fallback(
    user_id: int,
    *,
    vendor: str,
    prime_username: str,
    vendor_username: str,
    error: str,
    action: str,
) -> None:
    shared = shared_account_label(vendor)
    details = (
        f'RET {vendor} fallback: user={prime_username}, vendor_user={vendor_username}, '
        f'fallback_account={shared}, action={action}, error={error[:500]}'
    )
    log_activity(user_id, 'ret_credential_fallback', details)


def flag_missing_credentials(
    user_id: int,
    *,
    vendor: str,
    prime_username: str,
    action: str,
) -> None:
    shared = shared_account_label(vendor)
    details = (
        f'RET {vendor} missing credentials: user={prime_username}, '
        f'shared_account={shared}, action={action}'
    )
    log_activity(user_id, 'ret_missing_credentials', details)


def fallback_response_meta(error: str) -> dict[str, Any]:
    return {
        'credential_fallback': True,
        'credential_notice': FALLBACK_NOTICE,
        'credential_error': re.sub(r'\s+', ' ', error).strip()[:400],
    }


def missing_credentials_response_meta(vendor: str) -> dict[str, Any]:
    return {
        'credential_missing': True,
        'credential_notice': MISSING_CREDENTIALS_NOTICE,
        'credential_source': 'shared',
        'fallback_account': shared_account_label(vendor),
    }


def _use_shared_without_credentials(
    user_id: int,
    *,
    vendor: str,
    prime_username: str,
    action: str,
    operation: Callable[..., T],
    build_client: Callable[[], Any],
) -> tuple[T, dict[str, Any]]:
    client = build_client()
    result = operation(client)
    flag_missing_credentials(
        user_id,
        vendor=vendor,
        prime_username=prime_username,
        action=action,
    )
    meta = missing_credentials_response_meta(vendor)
    return result, meta


def run_huawei_with_user_credentials(
    user_id: int,
    *,
    prime_username: str,
    action: str,
    operation: Callable[[HuaweiCmClient], T],
) -> tuple[T, dict[str, Any]]:
    creds = get_user_vendor_credentials(user_id, 'huawei')
    if not creds:
        return _use_shared_without_credentials(
            user_id,
            vendor='huawei',
            prime_username=prime_username,
            action=action,
            operation=operation,
            build_client=build_huawei_client,
        )

    user_client = build_huawei_client({
        'username': creds['username'],
        'password': creds['password'],
    })
    try:
        return operation(user_client), {
            'credential_source': 'user',
            'vendor_username': creds['username'],
        }
    except (HuaweiCmError, NokiaCmError) as exc:
        if not is_credential_or_permission_error(exc):
            raise
        shared_client = build_huawei_client()
        try:
            result = operation(shared_client)
        except Exception:
            raise exc
        flag_credential_fallback(
            user_id,
            vendor='huawei',
            prime_username=prime_username,
            vendor_username=creds['username'],
            error=_message_for(exc),
            action=action,
        )
        meta = fallback_response_meta(_message_for(exc))
        meta['credential_source'] = 'fallback'
        meta['fallback_account'] = shared_account_label('huawei')
        return result, meta


def run_nokia_read_with_user_credentials(
    user_id: int,
    *,
    prime_username: str,
    action: str,
    operation: Callable[[NokiaCmClient], T],
) -> tuple[T, dict[str, Any]]:
    creds = get_user_vendor_credentials(user_id, 'nokia')
    if not creds:
        return _use_shared_without_credentials(
            user_id,
            vendor='nokia',
            prime_username=prime_username,
            action=action,
            operation=operation,
            build_client=build_nokia_client,
        )

    user_client = build_nokia_client_for_user(user_id)
    try:
        return operation(user_client), {
            'credential_source': 'user',
            'vendor_username': creds['username'],
        }
    except (NokiaCmError, NokiaOperationsError) as exc:
        if not is_credential_or_permission_error(exc):
            raise
        shared_client = build_nokia_client()
        try:
            result = operation(shared_client)
        except Exception:
            raise exc
        flag_credential_fallback(
            user_id,
            vendor='nokia',
            prime_username=prime_username,
            vendor_username=creds['username'],
            error=_message_for(exc),
            action=action,
        )
        meta = fallback_response_meta(_message_for(exc))
        meta['credential_source'] = 'fallback'
        meta['fallback_account'] = shared_account_label('nokia')
        return result, meta


def run_nokia_write_with_user_credentials(
    user_id: int,
    *,
    prime_username: str,
    action: str,
    operation: Callable[[NokiaOperationsClient], T],
) -> tuple[T, dict[str, Any]]:
    creds = get_user_vendor_credentials(user_id, 'nokia')
    if not creds:
        return _use_shared_without_credentials(
            user_id,
            vendor='nokia',
            prime_username=prime_username,
            action=action,
            operation=operation,
            build_client=build_nokia_operations_client,
        )

    user_client = build_nokia_operations_client_for_user(user_id)
    try:
        return operation(user_client), {
            'credential_source': 'user',
            'vendor_username': creds['username'],
        }
    except (NokiaCmError, NokiaOperationsError) as exc:
        if not is_credential_or_permission_error(exc):
            raise
        shared_client = build_nokia_operations_client()
        try:
            result = operation(shared_client)
        except Exception:
            raise exc
        flag_credential_fallback(
            user_id,
            vendor='nokia',
            prime_username=prime_username,
            vendor_username=creds['username'],
            error=_message_for(exc),
            action=action,
        )
        meta = fallback_response_meta(_message_for(exc))
        meta['credential_source'] = 'fallback'
        meta['fallback_account'] = shared_account_label('nokia')
        return result, meta
