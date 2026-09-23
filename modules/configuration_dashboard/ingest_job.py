"""Daily / manual shared Nokia ingest: RMOD_R + WNCELG for Configuration Dashboard."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_last_result: dict[str, Any] | None = None


def last_ingest_result() -> dict[str, Any] | None:
    return dict(_last_result) if _last_result else None


def _run_rmod_leg(
    client: Any,
    *,
    trigger_source: str,
    started: float,
) -> dict[str, Any]:
    from modules.rru_inventory import logic as rru_logic
    from modules.rru_inventory import store as rru_store

    rows, warnings, mo_class, sankey = rru_logic.fetch_nokia_rmod_inventory(
        client,
        area='',
        conf_id=1,
    )
    elapsed = round(time.monotonic() - started, 2)
    meta = rru_store.replace_snapshot(
        rows,
        mo_class=mo_class,
        warnings=warnings,
        summary=sankey.get('summary') or {},
        build_seconds=elapsed,
        trigger_source=trigger_source,
        status='ok',
    )
    return {
        'success': True,
        'mo_class': mo_class,
        'row_count': len(rows),
        'built_at': meta.get('built_at'),
        'warnings': warnings,
        'summary': sankey.get('summary') or {},
    }


def _run_wncelg_leg(
    client: Any,
    *,
    trigger_source: str,
    started: float,
) -> dict[str, Any]:
    from modules.configuration_dashboard import wncelg_logic
    from modules.configuration_dashboard import wncelg_store

    group_rows, site_rows, warnings, mo_class, summary = wncelg_logic.fetch_nokia_wncelg_inventory(
        client,
        conf_id=1,
    )
    elapsed = round(time.monotonic() - started, 2)
    meta = wncelg_store.replace_snapshot(
        group_rows,
        site_rows,
        mo_class=mo_class,
        warnings=warnings,
        summary=summary,
        build_seconds=elapsed,
        trigger_source=trigger_source,
        status='ok',
    )
    return {
        'success': True,
        'mo_class': mo_class,
        'group_count': len(group_rows),
        'site_count': len(site_rows),
        'built_at': meta.get('built_at'),
        'warnings': warnings,
        'summary': summary,
    }


def run_config_dashboard_ingest(*, trigger_source: str = 'scheduled') -> dict[str, Any]:
    """
    Full-network Nokia pull: RMOD_R then WNCELG, using the shared service account.

    One lock covers both legs so Admin / scheduler never overlap mid-run.
    """
    global _last_result

    if not _LOCK.acquire(blocking=False):
        result = {
            'success': False,
            'error': 'Configuration Dashboard ingest already running.',
            'trigger_source': trigger_source,
        }
        _last_result = result
        return result

    started = time.monotonic()
    rmod_part: dict[str, Any] = {}
    wncelg_part: dict[str, Any] = {}
    try:
        from core.cm_extractor.config import nokia_configured
        from core.cm_extractor.extraction import build_nokia_client

        if not nokia_configured():
            raise RuntimeError('Nokia NetAct CM is not configured.')

        client = build_nokia_client()
        rmod_part = _run_rmod_leg(client, trigger_source=trigger_source, started=started)
        wncelg_part = _run_wncelg_leg(client, trigger_source=trigger_source, started=started)
        elapsed = round(time.monotonic() - started, 2)
        result = {
            'success': True,
            'trigger_source': trigger_source,
            'build_seconds': elapsed,
            'rmod': rmod_part,
            'wncelg': wncelg_part,
            # Backward-compatible fields for callers that expect RMOD shape.
            'mo_class': rmod_part.get('mo_class'),
            'row_count': rmod_part.get('row_count', 0),
            'built_at': rmod_part.get('built_at'),
            'warnings': list(rmod_part.get('warnings') or []) + list(wncelg_part.get('warnings') or []),
            'summary': rmod_part.get('summary') or {},
        }
        _last_result = result
        logger.info(
            'Config dashboard ingest ok trigger=%s rmod_rows=%s wncelg_sites=%s seconds=%s',
            trigger_source,
            rmod_part.get('row_count'),
            wncelg_part.get('site_count'),
            elapsed,
        )
        return result
    except Exception as exc:
        elapsed = round(time.monotonic() - started, 2)
        logger.exception('Configuration Dashboard ingest failed: %s', exc)
        try:
            from modules.rru_inventory import store as rru_store

            if not rmod_part.get('success'):
                rru_store.record_failed_build(
                    trigger_source=trigger_source,
                    error=str(exc),
                    build_seconds=elapsed,
                )
        except Exception:
            logger.exception('Failed to record RMOD ingest error meta')
        try:
            from modules.configuration_dashboard import wncelg_store

            if not wncelg_part.get('success'):
                wncelg_store.record_failed_build(
                    trigger_source=trigger_source,
                    error=str(exc),
                    build_seconds=elapsed,
                )
        except Exception:
            logger.exception('Failed to record WNCELG ingest error meta')
        result = {
            'success': False,
            'trigger_source': trigger_source,
            'error': str(exc),
            'build_seconds': elapsed,
            'rmod': rmod_part,
            'wncelg': wncelg_part,
        }
        _last_result = result
        return result
    finally:
        _LOCK.release()
