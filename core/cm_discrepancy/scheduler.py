"""Daily job entrypoint for the CM discrepancy audit (called by sync scheduler)."""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)

_run_lock = threading.Lock()
_state: dict[str, Any] = {'running': False, 'vendor': '', 'message': '', 'last_result': {}}
_state_lock = threading.Lock()

DEFAULT_DAILY_HOUR = 3


def daily_hour() -> int:
    raw = (os.getenv('CM_DISCREPANCY_DAILY_HOUR') or '').strip()
    try:
        hour = int(raw) if raw else DEFAULT_DAILY_HOUR
    except ValueError:
        hour = DEFAULT_DAILY_HOUR
    return max(0, min(23, hour))


def enabled() -> bool:
    return (os.getenv('CM_DISCREPANCY_DISABLE') or '').strip().lower() not in ('1', 'true', 'yes')


def get_state() -> dict[str, Any]:
    with _state_lock:
        return dict(_state)


def _set_state(**fields: Any) -> None:
    with _state_lock:
        _state.update(fields)


def run_cm_discrepancy_daily(
    vendors: tuple[str, ...] = ('nokia', 'huawei'),
    *,
    run_date: str | None = None,
    mo_subset: list[str] | None = None,
) -> dict[str, Any]:
    """
    Run the full-network discrepancy audit for both vendors sequentially.

    Guarded so overlapping scheduler ticks / manual triggers are skipped while
    a run is still in progress.
    """
    if not _run_lock.acquire(blocking=False):
        logger.warning('CM discrepancy daily run skipped: previous run still in progress')
        return {'skipped': True, 'reason': 'previous run still in progress'}
    try:
        from core.cm_discrepancy.audit import run_audit
        from core.cm_extractor.config import huawei_configured, nokia_configured

        results: dict[str, Any] = {}
        for vendor in vendors:
            configured = nokia_configured() if vendor == 'nokia' else huawei_configured()
            if not configured:
                results[vendor] = {'skipped': True, 'reason': f'{vendor} CM not configured'}
                logger.info('CM discrepancy: %s skipped (CM not configured)', vendor)
                continue
            _set_state(running=True, vendor=vendor, message=f'{vendor} audit running')
            try:
                results[vendor] = run_audit(
                    vendor,
                    run_date=run_date,
                    mo_subset=mo_subset,
                    progress_cb=lambda msg: _set_state(message=msg),
                )
            except Exception as exc:
                logger.exception('CM discrepancy audit failed for %s', vendor)
                results[vendor] = {'error': str(exc)}
        _set_state(running=False, vendor='', message='idle', last_result=results)
        return results
    finally:
        _run_lock.release()


def trigger_cm_discrepancy_now(
    vendor: str = '',
    *,
    run_date: str | None = None,
    mo_subset: list[str] | None = None,
) -> dict[str, Any]:
    """Manual trigger (admin UI / testing). Empty vendor means both."""
    vendors = (vendor,) if vendor else ('nokia', 'huawei')
    return run_cm_discrepancy_daily(vendors, run_date=run_date, mo_subset=mo_subset)


def start_cm_discrepancy_async(
    vendor: str = '',
    *,
    run_date: str | None = None,
    mo_subset: list[str] | None = None,
) -> dict[str, Any]:
    """Fire the audit in a daemon thread; returns immediately with run state."""
    state = get_state()
    if state.get('running'):
        return {'started': False, 'reason': 'previous run still in progress', **state}
    thread = threading.Thread(
        target=trigger_cm_discrepancy_now,
        args=(vendor,),
        kwargs={'run_date': run_date, 'mo_subset': mo_subset},
        daemon=True,
        name='cm-discrepancy-audit',
    )
    thread.start()
    return {'started': True}
