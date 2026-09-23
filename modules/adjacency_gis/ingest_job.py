"""Daily / manual Nokia + Huawei 2G adjacency snapshots for Adjacency GIS."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_last_result: dict[str, Any] | None = None
_last_by_vendor: dict[str, dict[str, Any]] = {}


def last_ingest_result(vendor: str | None = None) -> dict[str, Any] | None:
    if vendor:
        row = _last_by_vendor.get(vendor.strip().lower())
        return dict(row) if row else None
    return dict(_last_result) if _last_result else None


def _persist_vendor(
    vendor: str,
    sectors: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    warnings: list[str],
    summary: dict[str, Any],
    build_seconds: float,
    trigger_source: str,
    status: str = 'ok',
    error: str = '',
) -> dict[str, Any]:
    from modules.adjacency_gis import store as adj_store

    return adj_store.replace_vendor_snapshot(
        vendor,
        sectors,
        edges,
        warnings=warnings,
        summary=summary,
        build_seconds=build_seconds,
        trigger_source=trigger_source,
        status=status,
        error=error,
    )


def run_nokia_adjacency_ingest(*, trigger_source: str = 'scheduled') -> dict[str, Any]:
    """Pull Nokia BTS/TRX/ADCE and replace the nokia vendor snapshot."""
    started = time.monotonic()
    try:
        from core.cm_extractor.config import nokia_configured
        from core.cm_extractor.extraction import build_nokia_client
        from modules.adjacency_gis import logic as adj_logic

        if not nokia_configured():
            raise RuntimeError('Nokia NetAct CM is not configured.')

        client = build_nokia_client()
        sectors, edges, warnings, summary = adj_logic.fetch_nokia_adjacency_snapshot(client)
        elapsed = round(time.monotonic() - started, 2)
        meta = _persist_vendor(
            'nokia',
            sectors,
            edges,
            warnings=warnings,
            summary=summary,
            build_seconds=elapsed,
            trigger_source=trigger_source,
        )
        result = {
            'success': True,
            'vendor': 'nokia',
            'trigger_source': trigger_source,
            'sector_count': len(sectors),
            'edge_count': len(edges),
            'build_seconds': elapsed,
            'built_at': meta.get('built_at'),
            'warnings': warnings,
            'summary': summary,
        }
        _last_by_vendor['nokia'] = result
        logger.info(
            'Adjacency GIS Nokia ingest ok trigger=%s sectors=%s edges=%s seconds=%s',
            trigger_source,
            len(sectors),
            len(edges),
            elapsed,
        )
        return result
    except Exception as exc:
        elapsed = round(time.monotonic() - started, 2)
        logger.exception('Adjacency GIS Nokia ingest failed: %s', exc)
        try:
            _persist_vendor(
                'nokia',
                [],
                [],
                warnings=[],
                summary={},
                build_seconds=elapsed,
                trigger_source=trigger_source,
                status='error',
                error=str(exc),
            )
        except Exception:
            logger.exception('Failed to persist Nokia Adjacency GIS error snapshot')
        result = {
            'success': False,
            'vendor': 'nokia',
            'error': str(exc),
            'trigger_source': trigger_source,
            'build_seconds': elapsed,
            'sector_count': 0,
            'edge_count': 0,
        }
        _last_by_vendor['nokia'] = result
        return result


def run_huawei_adjacency_ingest(*, trigger_source: str = 'scheduled') -> dict[str, Any]:
    """Pull Huawei GCELL/GTRX/G2GNCELL and replace the huawei vendor snapshot."""
    started = time.monotonic()
    try:
        from core.cm_extractor.config import huawei_configured
        from core.cm_extractor.extraction import build_huawei_client
        from modules.adjacency_gis import logic as adj_logic

        if not huawei_configured():
            raise RuntimeError('Huawei U2020 CM is not configured.')

        client = build_huawei_client()
        try:
            client.login()
        except Exception:
            pass
        sectors, edges, warnings, summary = adj_logic.fetch_huawei_adjacency_snapshot(client)
        elapsed = round(time.monotonic() - started, 2)
        meta = _persist_vendor(
            'huawei',
            sectors,
            edges,
            warnings=warnings,
            summary=summary,
            build_seconds=elapsed,
            trigger_source=trigger_source,
        )
        result = {
            'success': True,
            'vendor': 'huawei',
            'trigger_source': trigger_source,
            'sector_count': len(sectors),
            'edge_count': len(edges),
            'build_seconds': elapsed,
            'built_at': meta.get('built_at'),
            'warnings': warnings,
            'summary': summary,
        }
        _last_by_vendor['huawei'] = result
        logger.info(
            'Adjacency GIS Huawei ingest ok trigger=%s sectors=%s edges=%s seconds=%s',
            trigger_source,
            len(sectors),
            len(edges),
            elapsed,
        )
        return result
    except Exception as exc:
        elapsed = round(time.monotonic() - started, 2)
        logger.exception('Adjacency GIS Huawei ingest failed: %s', exc)
        try:
            _persist_vendor(
                'huawei',
                [],
                [],
                warnings=[],
                summary={},
                build_seconds=elapsed,
                trigger_source=trigger_source,
                status='error',
                error=str(exc),
            )
        except Exception:
            logger.exception('Failed to persist Huawei Adjacency GIS error snapshot')
        result = {
            'success': False,
            'vendor': 'huawei',
            'error': str(exc),
            'trigger_source': trigger_source,
            'build_seconds': elapsed,
            'sector_count': 0,
            'edge_count': 0,
        }
        _last_by_vendor['huawei'] = result
        return result


def run_adjacency_gis_ingest(
    *,
    trigger_source: str = 'scheduled',
    vendor: str = 'all',
) -> dict[str, Any]:
    """
    Run Nokia and/or Huawei adjacency ingest.

    ``vendor``: ``nokia`` | ``huawei`` | ``all`` (default).
    """
    global _last_result

    want = (vendor or 'all').strip().lower()
    if want not in ('nokia', 'huawei', 'all', '*'):
        result = {
            'success': False,
            'error': f'Unsupported vendor: {vendor}',
            'trigger_source': trigger_source,
        }
        _last_result = result
        return result

    if not _LOCK.acquire(blocking=False):
        result = {
            'success': False,
            'error': 'Adjacency GIS ingest already running.',
            'trigger_source': trigger_source,
            'vendor': want,
        }
        _last_result = result
        return result

    started = time.monotonic()
    try:
        results: dict[str, Any] = {}
        if want in ('nokia', 'all', '*'):
            results['nokia'] = run_nokia_adjacency_ingest(trigger_source=trigger_source)
        if want in ('huawei', 'all', '*'):
            results['huawei'] = run_huawei_adjacency_ingest(trigger_source=trigger_source)

        ok = all(bool(r.get('success')) for r in results.values()) if results else False
        sectors = sum(int(r.get('sector_count') or 0) for r in results.values())
        edges = sum(int(r.get('edge_count') or 0) for r in results.values())
        warnings: list[str] = []
        for r in results.values():
            warnings.extend(r.get('warnings') or [])
            if r.get('error'):
                warnings.append(f"{r.get('vendor')}: {r['error']}")

        result = {
            'success': ok,
            'vendor': want if want not in ('*',) else 'all',
            'trigger_source': trigger_source,
            'sector_count': sectors,
            'edge_count': edges,
            'build_seconds': round(time.monotonic() - started, 2),
            'warnings': warnings,
            'by_vendor': results,
            'error': '' if ok else '; '.join(
                f"{k}: {v.get('error')}" for k, v in results.items() if not v.get('success')
            ),
        }
        _last_result = result
        return result
    finally:
        _LOCK.release()
