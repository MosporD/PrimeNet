"""
Discover the Nokia NetAct inventory (NEs) directly from the CM Open API.

Instead of listing sites from the PrimeNet metadata DB, the picker can be filled
from what actually exists in NetAct (the PLMN tree). The discovered inventory is
then enriched with cluster/area by joining each site_id to the metadata
``cluster -> area`` mapping. Results are cached in memory and persisted to disk so
the UI is instant and resilient across restarts; a background job refreshes it.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from core.cm_extractor.nokia_client import NokiaCmClient, NokiaCmError
from core.cm_extractor.site_catalog import (
    canonical_controller_site_id,
    cluster_area_map,
    list_netact_plmn_controllers,
    nokia_area_map,
    nokia_mrbts_area_for_site,
    normalize_scope_level,
    site_cluster_map,
    _known_nokia_metadata_site_ids,
)

_CATALOG_PATH = Path(__file__).resolve().parents[2] / 'data' / 'nokia_netact_inventory.json'
_CACHE_TTL_SEC = 6 * 3600
# Bump when metadata enrichment rules change (e.g. NetAct 50801 -> metadata 801,
# or longest-suffix mapping 53308 -> 3308 instead of 308).
_METADATA_ENRICHMENT_VERSION = 3

# MO paths that enumerate site-level NEs per scope (all PLMNs).
_MRBTS_MO_PATH = '/NetActCommon:PLMN/MRBTS as $m'

_CACHE: dict[str, Any] = {
    'scopes': {},        # {scope_level: [ {site_id, dn, ne_name, cluster, area}, ... ]}
    'fetched_at': 0.0,
}
_CACHE_LOCK = threading.Lock()


def _dn_suffix_id(dn: str, segment: str) -> str:
    """Extract the instance id from a DN suffix like ``.../MRBTS-101`` -> ``101``."""
    tail = (dn or '').rsplit('/', 1)[-1]
    marker = f'{segment}-'
    if marker in tail:
        return tail.split(marker, 1)[1]
    if '-' in tail:
        return tail.rsplit('-', 1)[-1]
    return tail


def discover_mrbts(client: NokiaCmClient, *, conf_id: int = 1) -> list[dict[str, str]]:
    """List all MRBTS NEs (LTE/NR sites) from the NetAct PLMN tree."""
    rows = client.query(_MRBTS_MO_PATH, ['dn()', 'instance()'], conf_id=conf_id)
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows or []:
        if not row:
            continue
        dn = str(row[0] or '').strip()
        instance = str(row[1] if len(row) > 1 else '').strip()
        site_id = instance or _dn_suffix_id(dn, 'MRBTS')
        if not site_id or site_id in seen:
            continue
        seen.add(site_id)
        items.append({'site_id': site_id, 'dn': dn, 'ne_name': ''})
    items.sort(key=lambda r: (len(r['site_id']), r['site_id']))
    return items


def discover_controllers(client: NokiaCmClient, scope_level: str) -> list[dict[str, str]]:
    """List RNC or BSC controller NEs from the NetAct PLMN tree."""
    controllers = list_netact_plmn_controllers(client, scope_level)
    by_id: dict[str, dict[str, str]] = {}
    for ctrl in controllers:
        instance = str(ctrl.get('instance') or '').strip()
        dn = str(ctrl.get('dn') or '').strip()
        if not instance and dn:
            instance = _dn_suffix_id(dn, scope_level)
        if not dn and not instance:
            continue
        site_id = canonical_controller_site_id(instance, dn, scope_level)
        if not site_id:
            continue
        by_id[site_id] = {'site_id': site_id, 'dn': dn, 'ne_name': ''}
    items = list(by_id.values())
    items.sort(key=lambda r: (len(r['site_id']), r['site_id']))
    return items


def _enrich_with_area(records: list[dict[str, str]], scope_level: str) -> None:
    """Attach cluster + area to MRBTS records via metadata cluster->area mapping."""
    if scope_level != 'MRBTS' or not records:
        return
    known_metadata_ids = _known_nokia_metadata_site_ids()
    clusters = site_cluster_map('nokia', 'MRBTS')
    cluster_to_area = cluster_area_map()
    area_map = nokia_area_map('MRBTS')
    for rec in records:
        _meta_id, area, cluster = nokia_mrbts_area_for_site(
            str(rec.get('site_id') or ''),
            known_metadata_ids=known_metadata_ids,
            clusters=clusters,
            cluster_to_area=cluster_to_area,
            area_map=area_map,
        )
        rec['cluster'] = cluster
        rec['area'] = area


def ensure_nokia_inventory_enriched(*, persist: bool = True) -> bool:
    """
    Re-apply metadata cluster/area mapping to cached MRBTS inventory.

    NetAct ids like ``50801`` must map to metadata ``801`` before area counts
    and area bulk-select are correct. Returns True when records were updated.
    """
    reload_inventory_from_disk()
    with _CACHE_LOCK:
        scopes = _CACHE.get('scopes') or {}
        records = scopes.get('MRBTS') or []
        if not records:
            return False
        if int(_CACHE.get('metadata_enrichment') or 0) >= _METADATA_ENRICHMENT_VERSION:
            return False

        before = [
            (rec.get('site_id'), rec.get('cluster', ''), rec.get('area', ''))
            for rec in records
        ]
        _enrich_with_area(records, 'MRBTS')
        after = [
            (rec.get('site_id'), rec.get('cluster', ''), rec.get('area', ''))
            for rec in records
        ]
        changed = before != after
        _CACHE['metadata_enrichment'] = _METADATA_ENRICHMENT_VERSION
        payload = {
            'scopes': scopes,
            'fetched_at': _CACHE.get('fetched_at') or time.time(),
            'metadata_enrichment': _METADATA_ENRICHMENT_VERSION,
        }

    if persist:
        save_inventory_to_disk(payload)
    return changed


def discover_nokia_inventory(
    client: NokiaCmClient,
    *,
    scopes: tuple[str, ...] = ('MRBTS', 'RNC', 'BSC'),
) -> dict[str, Any]:
    """Discover NEs per scope from NetAct and enrich MRBTS with cluster/area."""
    by_scope: dict[str, list[dict[str, str]]] = {}
    errors: dict[str, str] = {}
    for scope in scopes:
        level = normalize_scope_level(scope)
        try:
            if level == 'MRBTS':
                records = discover_mrbts(client)
            else:
                records = discover_controllers(client, level)
            _enrich_with_area(records, level)
            by_scope[level] = records
        except (NokiaCmError, ConnectionError) as exc:
            errors[level] = str(exc)

    return {
        'scopes': by_scope,
        'errors': errors,
        'counts': {scope: len(items) for scope, items in by_scope.items()},
        'fetched_at': time.time(),
    }


def _apply_cache(payload: dict[str, Any]) -> None:
    with _CACHE_LOCK:
        _CACHE['scopes'] = payload.get('scopes') or {}
        _CACHE['fetched_at'] = float(payload.get('fetched_at') or time.time())
        _CACHE['metadata_enrichment'] = int(payload.get('metadata_enrichment') or 0)
        try:
            _CACHE['disk_mtime'] = _CATALOG_PATH.stat().st_mtime
        except OSError:
            _CACHE['disk_mtime'] = 0.0


def save_inventory_to_disk(payload: dict[str, Any] | None = None) -> Path:
    data = payload or {
        'scopes': _CACHE.get('scopes') or {},
        'fetched_at': _CACHE.get('fetched_at') or time.time(),
        'metadata_enrichment': int(_CACHE.get('metadata_enrichment') or _METADATA_ENRICHMENT_VERSION),
    }
    if 'metadata_enrichment' not in data:
        data['metadata_enrichment'] = int(_CACHE.get('metadata_enrichment') or _METADATA_ENRICHMENT_VERSION)
    _CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CATALOG_PATH.write_text(json.dumps(data, indent=2), encoding='utf-8')
    try:
        with _CACHE_LOCK:
            _CACHE['disk_mtime'] = _CATALOG_PATH.stat().st_mtime
    except OSError:
        pass
    return _CATALOG_PATH


def reload_inventory_from_disk(*, force: bool = False) -> bool:
    """Load or refresh in-memory inventory from disk when the file changes."""
    if not _CATALOG_PATH.is_file():
        return False
    try:
        disk_mtime = _CATALOG_PATH.stat().st_mtime
    except OSError:
        return False
    with _CACHE_LOCK:
        if (
            not force
            and _CACHE.get('scopes')
            and float(_CACHE.get('disk_mtime') or 0) >= disk_mtime
        ):
            return True
    try:
        payload = json.loads(_CATALOG_PATH.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return False
    if not payload.get('scopes'):
        return False
    _apply_cache(payload)
    return True


def load_inventory_from_disk() -> bool:
    if _CACHE.get('scopes'):
        return reload_inventory_from_disk()
    return reload_inventory_from_disk(force=True)


def get_cached_nokia_inventory(
    scope_level: str,
    *,
    max_age_sec: int = 10 ** 9,
) -> list[dict[str, str]] | None:
    """Return cached NEs for a scope, or None when nothing is cached/fresh."""
    level = normalize_scope_level(scope_level)
    reload_inventory_from_disk()
    ensure_nokia_inventory_enriched(persist=True)
    scopes = _CACHE.get('scopes') or {}
    if level not in scopes:
        return None
    if max_age_sec > 0 and time.time() - float(_CACHE.get('fetched_at') or 0) > max_age_sec:
        return None
    return scopes.get(level) or []


def refresh_nokia_inventory_cache(
    client: NokiaCmClient,
    *,
    scopes: tuple[str, ...] = ('MRBTS', 'RNC', 'BSC'),
) -> dict[str, Any]:
    result = discover_nokia_inventory(client, scopes=scopes)
    # Keep previously discovered scopes if a scope failed this run.
    if result.get('scopes'):
        merged = dict(_CACHE.get('scopes') or {})
        merged.update(result['scopes'])
        result['scopes'] = merged
    _apply_cache(result)
    result['metadata_enrichment'] = _METADATA_ENRICHMENT_VERSION
    save_inventory_to_disk({
        'scopes': _CACHE['scopes'],
        'fetched_at': _CACHE['fetched_at'],
        'metadata_enrichment': _METADATA_ENRICHMENT_VERSION,
    })
    try:
        from core.cm_extractor.site_catalog import invalidate_nokia_site_id_caches

        invalidate_nokia_site_id_caches()
    except Exception:
        pass
    return result
