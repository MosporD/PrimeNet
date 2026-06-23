"""Environment-backed defaults for CM extractor connections."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse


def _env(key: str, default: str = '') -> str:
    return (os.getenv(key) or default).strip()


def _env_bool(key: str, default: bool = False) -> bool:
    raw = _env(key)
    if not raw:
        return default
    return raw.lower() in ('1', 'true', 'yes', 'on')


def _env_int(key: str, default: int) -> int:
    raw = _env(key)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    raw = _env(key)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def normalize_netact_host(raw: str) -> str:
    """Accept hostname or full NetAct login URL; return hostname only."""
    value = (raw or '').strip().rstrip('/')
    if not value:
        return ''
    if value.startswith('http://') or value.startswith('https://'):
        parsed = urlparse(value)
        return (parsed.hostname or '').strip()
    return value.split('/')[0].strip()


def nokia_defaults() -> dict:
    base_url = _env('NOKIA_CM_BASE_URL')
    host = normalize_netact_host(_env('NOKIA_CM_HOST'))
    if not host:
        host = normalize_netact_host(_env('NOKIA_CM_LOGIN_URL'))
    if not host:
        host = normalize_netact_host(_env('NOKIA_NETACT_HOST'))
    return {
        'base_url': base_url.rstrip('/') if base_url else '',
        'host': host,
        'username': _env('NOKIA_CM_USER'),
        'password': _env('NOKIA_CM_PASSWORD'),
        'verify_ssl': _env_bool('NOKIA_CM_VERIFY_SSL', False),
        'use_https': _env_bool('NOKIA_CM_USE_HTTPS', True),
        'mo_batch_size': _env_int('NOKIA_CM_MO_BATCH_SIZE', 150),
        'batch_delay_sec': _env_float('NOKIA_CM_BATCH_DELAY_SEC', 0.4),
        'max_retries': _env_int('NOKIA_CM_MAX_RETRIES', 8),
        'retry_base_delay_sec': _env_float('NOKIA_CM_RETRY_BASE_DELAY_SEC', 2.0),
        'timeout': _env_int('NOKIA_CM_TIMEOUT', 180),
    }


def nokia_export_ssh_settings() -> dict[str, Any]:
    """
    SFTP settings to pull Import_Export files from the NetAct OMC.

    Import_Export writes to the OMC filesystem (e.g. 10.119.219.77), not the CM REST
    login hostname. Falls back to NOKIA_PM_* when NOKIA_CM_SSH_* is unset.
    """
    ssh_host = _env('NOKIA_CM_SSH_HOST')
    pm_host = _env('NOKIA_PM_HOST')
    host = ssh_host or pm_host or ''
    user = _env('NOKIA_CM_SSH_USER') or _env('NOKIA_PM_USER') or ''
    password = _env('NOKIA_CM_SSH_PASSWORD') or _env('NOKIA_PM_PASSWORD') or ''
    port = _env_int('NOKIA_CM_SSH_PORT', _env_int('NOKIA_PM_PORT', 22))
    explicit = bool(ssh_host.strip())
    return {
        'host': host.strip(),
        'port': port,
        'username': user.strip(),
        'password': password,
        'remote_dir': _env('NOKIA_CM_EXPORT_DIR', '/d/oss/global/var/racops/export'),
        'remote_dir_extra': _env('NOKIA_CM_EXPORT_DIR_EXTRA', ''),
        'timeout': _env_int('NOKIA_CM_SSH_TIMEOUT', 60),
        'file_wait_sec': _env_int('NOKIA_CM_EXPORT_FILE_WAIT_SEC', 180),
        'configured': bool(host.strip() and user.strip() and password),
        'explicit_ssh': explicit,
        'source': 'NOKIA_CM_SSH_*' if explicit else ('NOKIA_PM_*' if pm_host else ''),
    }


def nokia_bulk_export_settings() -> dict[str, int]:
    """Timeouts for CM Operations Import_Export bulk RNC/BSC export."""
    return {
        'operation_timeout_sec': _env_int('NOKIA_CM_BULK_OPERATION_TIMEOUT_SEC', 3600),
        'file_wait_sec': _env_int('NOKIA_CM_EXPORT_FILE_WAIT_SEC', 600),
    }


def nokia_configured() -> bool:
    cfg = nokia_defaults()
    return bool(cfg['host'] and cfg['username'] and cfg['password'])


def build_nokia_operations_client():
    """CM Operations REST client (Import_Export) using NOKIA_CM_* credentials."""
    from core.cm_extractor.nokia_operations_client import NokiaOperationsClient

    if not nokia_configured():
        raise ValueError(
            'Nokia NetAct CM is not configured. Set NOKIA_CM_HOST, NOKIA_CM_USER, '
            'and NOKIA_CM_PASSWORD in .env.'
        )
    cfg = nokia_defaults()
    return NokiaOperationsClient(
        host=cfg['host'],
        username=cfg['username'],
        password=cfg['password'],
        base_url=cfg.get('base_url') or '',
        use_https=cfg.get('use_https', True),
        verify_ssl=cfg.get('verify_ssl', False),
        timeout=int(cfg.get('timeout') or 180),
    )


def huawei_configured() -> bool:
    cfg = huawei_defaults()
    return bool(cfg['host'] and cfg['username'] and cfg['password'])


def huawei_defaults() -> dict:
    api_style = _env('HUAWEI_CM_API_STYLE', 'wireless').strip().lower()
    if api_style not in ('wireless', 'cn'):
        api_style = 'wireless'
    # 31127 = northbound Open API; 31943 is web/SSO only (OAuth returns 404 there).
    default_port = '31127'
    port_raw = _env('HUAWEI_CM_PORT') or default_port
    try:
        port = int(port_raw)
    except ValueError:
        port = int(default_port)
    return {
        'host': _env('HUAWEI_CM_HOST', _env('HUAWEI_PM_HOST', '')),
        'port': port,
        'username': _env('HUAWEI_CM_USER', _env('HUAWEI_PM_USER', '')),
        'password': _env('HUAWEI_CM_PASSWORD', _env('HUAWEI_PM_PASSWORD', '')),
        'verify_ssl': _env_bool('HUAWEI_CM_VERIFY_SSL', False),
        'use_https': _env_bool('HUAWEI_CM_USE_HTTPS', True),
        'api_style': api_style,
        'client_ip': _env('HUAWEI_CM_CLIENT_IP', ''),
        'script_base_url': _env('HUAWEI_CM_SCRIPT_BASE_URL', ''),
    }
