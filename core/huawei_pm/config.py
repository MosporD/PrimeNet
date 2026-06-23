"""Environment-backed defaults for Huawei PM Open API."""

from __future__ import annotations

import os

from core.cm_extractor.config import huawei_configured, huawei_defaults


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


def pm_defaults() -> dict:
    """
    PM Open API uses the same northbound host/credentials as CM (port 31127).

    Falls back to HUAWEI_CM_* then HUAWEI_PM_* (SFTP) env vars via huawei_defaults().
    """
    base = huawei_defaults()
    return {
        **base,
        'timeout': _env_int('HUAWEI_PM_API_TIMEOUT', _env_int('HUAWEI_CM_TIMEOUT', 300)),
        'poll_interval_sec': _env_float('HUAWEI_PM_API_POLL_SEC', 3.0),
        'poll_timeout_sec': _env_int('HUAWEI_PM_API_POLL_TIMEOUT_SEC', 900),
        'page_limit': min(5000, max(1, _env_int('HUAWEI_PM_API_PAGE_LIMIT', 5000))),
        'delete_task_after_query': _env_bool('HUAWEI_PM_API_DELETE_TASK', True),
    }


def pm_configured() -> bool:
    return huawei_configured()


def build_pm_client():
    from core.huawei_pm.client import HuaweiPmClient

    if not pm_configured():
        raise ValueError(
            'Huawei PM Open API is not configured. Set HUAWEI_CM_HOST (or HUAWEI_PM_HOST), '
            'HUAWEI_CM_USER, and HUAWEI_CM_PASSWORD in .env. Use port 31127 for northbound REST.'
        )
    cfg = pm_defaults()
    return HuaweiPmClient(
        host=cfg['host'],
        username=cfg['username'],
        password=cfg['password'],
        port=int(cfg.get('port') or 31127),
        use_https=cfg.get('use_https', True),
        verify_ssl=cfg.get('verify_ssl', False),
        timeout=int(cfg.get('timeout') or 300),
        poll_interval_sec=float(cfg.get('poll_interval_sec') or 3.0),
        poll_timeout_sec=int(cfg.get('poll_timeout_sec') or 900),
        page_limit=int(cfg.get('page_limit') or 5000),
    )
