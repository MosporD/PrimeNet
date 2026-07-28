"""
Discover Huawei U2020 network elements and MML object columns via northbound APIs.

U2020 MML ``neNames`` must be OSS ``meName`` values (e.g. ``1006-ULT_Zawahrah_End_PD_Fiber_TASC``),
not PrimeNet metadata ``site_name`` strings. FM alarms are the practical discovery source.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

_DISCOVERY_RETRY_STATUSES = {429, 500, 502, 503, 504}
_CATALOG_PATH = Path(__file__).resolve().parents[2] / 'data' / 'huawei_u2020_ne_catalog.json'

from core.cm_extractor.huawei_client import HuaweiCmClient, HuaweiCmError
from core.cm_extractor.huawei_mml_discovery import discover_commands_by_product
from core.cm_extractor.http_util import request_json

_SITE_ID_RE = re.compile(r'^(\d+)-')
_CACHE: dict[str, Any] = {
    'nes': [],
    'nes_by_site_id': {},
    'mo_columns': {},
    'mo_catalog': [],
    'commands_by_product': {},
    'product_samples': {},
    'fetched_at': 0.0,
}
_CACHE_TTL_SEC = 3600


def parse_site_id_from_ne_name(ne_name: str) -> str:
    match = _SITE_ID_RE.match((ne_name or '').strip())
    return match.group(1) if match else ''


def _index_nes(nes: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_site: dict[str, list[dict[str, Any]]] = {}
    for item in nes:
        site_id = str(item.get('site_id') or '').strip()
        if not site_id:
            continue
        by_site.setdefault(site_id, []).append(item)
    return by_site


def discover_nes_from_alarms(
    client: HuaweiCmClient,
    *,
    data_types: tuple[str, ...] = ('CURRENT', 'HISTORY'),
    max_pages_per_type: int = 200,
    page_limit: int = 1000,
) -> list[dict[str, Any]]:
    """Collect unique NE names from FM current/historical alarms."""
    merged: dict[str, dict[str, Any]] = {}

    for data_type in data_types:
        marker = ''
        pages = 0
        while pages < max_pages_per_type:
            path = (
                f'/api/rest/faultSupervisonManagement/v1/alarms'
                f'?dataType={data_type}&limit={page_limit}'
            )
            if marker:
                path += f'&marker={marker}'

            try:
                status, payload = request_json(
                    'GET',
                    client._url(path),
                    headers=client._auth_headers(content_type=''),
                    timeout=120,
                    verify_ssl=client.verify_ssl,
                )
                if status in _DISCOVERY_RETRY_STATUSES:
                    time.sleep(2.0)
                    status, payload = request_json(
                        'GET',
                        client._url(path),
                        headers=client._auth_headers(content_type=''),
                        timeout=120,
                        verify_ssl=client.verify_ssl,
                    )
            except ConnectionError:
                if merged:
                    break
                raise
            if status != 200 or not isinstance(payload, dict):
                if pages > 0 and merged:
                    break
                raise HuaweiCmError(
                    f'FM alarm discovery failed ({data_type}, HTTP {status})',
                    status=status,
                    payload=payload,
                )

            batch = payload.get('alarmInformationList') or []
            for alarm in batch:
                ne_name = str(alarm.get('meName') or '').strip()
                if not ne_name or ne_name.upper() == 'OSS':
                    continue
                site_id = parse_site_id_from_ne_name(ne_name)
                existing = merged.get(ne_name)
                if existing:
                    existing['sources'].add(data_type)
                    continue
                merged[ne_name] = {
                    'ne_name': ne_name,
                    'site_id': site_id,
                    'product_name': str(alarm.get('productName') or '').strip(),
                    'sources': {data_type},
                }

            marker = str(payload.get('marker') or '').strip()
            pages += 1
            if not marker or not batch:
                break

    items = []
    for item in merged.values():
        item['sources'] = sorted(item.pop('sources'))
        items.append(item)
    items.sort(key=lambda row: row['ne_name'].lower())
    return items


def _alarm_value(alarm: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = alarm.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ''


def _normalize_alarm(alarm: dict[str, Any]) -> dict[str, Any]:
    me_name = _alarm_value(alarm, 'meName', 'neName', 'devName')
    return {
        'alarm_id': _alarm_value(alarm, 'alarmId', 'alarmID', 'eventId', 'faultId', 'serialNo'),
        'me_name': me_name,
        'site_id': parse_site_id_from_ne_name(me_name),
        'alarm_name': _alarm_value(alarm, 'alarmName', 'name', 'eventName', 'faultName'),
        'severity': _alarm_value(alarm, 'severity', 'perceivedSeverity', 'alarmSeverity'),
        'occur_time': _alarm_value(alarm, 'occurTime', 'firstOccurTime', 'eventTime', 'raisedTime'),
        'product_name': _alarm_value(alarm, 'productName', 'product'),
        'location_info': _alarm_value(alarm, 'locationInfo', 'location', 'position'),
        'probable_cause': _alarm_value(alarm, 'probableCause', 'reason', 'cause'),
        'raw': alarm,
    }


def fetch_fm_alarms(
    client: HuaweiCmClient,
    *,
    data_type: str = 'CURRENT',
    limit: int = 200,
    marker: str = '',
) -> dict[str, Any]:
    """Fetch one page of Huawei FM alarms and normalize fields for display."""
    data_type = (data_type or 'CURRENT').strip().upper()
    if data_type not in ('CURRENT', 'HISTORY'):
        data_type = 'CURRENT'
    limit = max(1, min(int(limit or 200), 1000))
    path = f'/api/rest/faultSupervisonManagement/v1/alarms?dataType={data_type}&limit={limit}'
    if marker:
        path += f'&marker={marker}'

    status, payload = request_json(
        'GET',
        client._url(path),
        headers=client._auth_headers(content_type=''),
        timeout=120,
        verify_ssl=client.verify_ssl,
    )
    if status != 200 or not isinstance(payload, dict):
        raise HuaweiCmError(
            f'FM alarm fetch failed ({data_type}, HTTP {status})',
            status=status,
            payload=payload,
        )

    alarms = payload.get('alarmInformationList') or []
    if not isinstance(alarms, list):
        alarms = []
    return {
        'alarms': [_normalize_alarm(alarm) for alarm in alarms if isinstance(alarm, dict)],
        'count': len(alarms),
        'marker': str(payload.get('marker') or '').strip(),
        'data_type': data_type,
    }


def discover_u2020_inventory(
    client: HuaweiCmClient,
    *,
    include_history: bool = True,
    sample_ne_for_mo: str = '',
    discover_mos: bool = True,
    max_pages_per_type: int = 200,
) -> dict[str, Any]:
    """Full discovery: NE catalog from FM + optional MO column headers from a sample NE."""
    data_types: tuple[str, ...] = ('CURRENT', 'HISTORY') if include_history else ('CURRENT',)
    nes = discover_nes_from_alarms(
        client,
        data_types=data_types,
        max_pages_per_type=max_pages_per_type,
    )
    by_site_id = _index_nes(nes)

    mo_columns: dict[str, list[str]] = {}
    mo_catalog: list[dict[str, Any]] = []
    commands_by_product: dict[str, list[dict[str, Any]]] = {}
    product_samples: dict[str, str] = {}
    sample_ne = (sample_ne_for_mo or '').strip()

    if discover_mos and nes:
        cmd_result = discover_commands_by_product(client, nes)
        commands_by_product = cmd_result.get('commands_by_product') or {}
        mo_catalog = cmd_result.get('mo_catalog') or []
        product_samples = cmd_result.get('product_samples') or {}
        for item in mo_catalog:
            mo_columns[item['id']] = list(item.get('columns') or [])
        if not sample_ne and product_samples:
            sample_ne = next(iter(product_samples.values()), '')

    return {
        'nes': nes,
        'nes_by_site_id': by_site_id,
        'mo_columns': mo_columns,
        'mo_catalog': mo_catalog,
        'commands_by_product': commands_by_product,
        'product_samples': product_samples,
        'sample_ne': sample_ne,
        'ne_count': len(nes),
        'site_id_count': len(by_site_id),
        'mo_type_count': len(mo_catalog),
    }


def _name_similarity(a: str, b: str) -> int:
    """Rough token overlap score for picking among multiple NE candidates."""
    def tokens(value: str) -> set[str]:
        return {t for t in re.split(r'[^A-Za-z0-9]+', (value or '').upper()) if len(t) > 2}

    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0
    return len(ta & tb)


def resolve_ne_name_from_catalog(
    site_id: str,
    site_name: str = '',
    catalog: list[dict[str, Any]] | None = None,
    *,
    by_site_id: dict[str, list[dict[str, Any]]] | None = None,
) -> str | None:
    """
    Map PrimeNet **site_id** (e.g. ``1005``) to a U2020 MML neName from FM discovery.

    Metadata site_name is only used to disambiguate when multiple OSS NEs share one id.
    """
    ne_name, _source = resolve_u2020_ne_name(
        site_id,
        site_name,
        catalog,
        by_site_id=by_site_id,
        allow_metadata_fallback=False,
    )
    return ne_name


def metadata_site_name_as_ne_name(site_id: str, site_name: str = '') -> str | None:
    """
    Use PrimeNet ``sites.site_name`` when it is already an OSS meName.

    FM alarm discovery misses many IBS / indoor sites with no active alarms; metadata
    often stores the full meName (e.g. ``1641-UL_National_Center_Diabetes_IBS_M``).
    """
    token = str(site_id or '').strip()
    name = str(site_name or '').strip()
    if not token or not name or not name.startswith(f'{token}-'):
        return None
    if not _SITE_ID_RE.match(name):
        return None
    suffix = name[len(token) + 1 :].strip()
    if len(suffix) < 2:
        return None
    return name


def resolve_u2020_ne_name(
    site_id: str,
    site_name: str = '',
    catalog: list[dict[str, Any]] | None = None,
    *,
    by_site_id: dict[str, list[dict[str, Any]]] | None = None,
    allow_metadata_fallback: bool = True,
    metadata_candidates: list[str] | None = None,
) -> tuple[str | None, str]:
    """
    Resolve site_id to U2020 MML neName.

    Returns ``(ne_name, source)`` where source is ``fm``, ``metadata``, or ``''``.
    """
    token = str(site_id or '').strip()
    if not token:
        return None, ''

    if allow_metadata_fallback:
        meta_list = [str(name).strip() for name in (metadata_candidates or []) if str(name).strip()]
        if not meta_list and site_name:
            fallback = metadata_site_name_as_ne_name(token, site_name)
            if fallback:
                meta_list = [fallback]
        if meta_list:
            hint = site_name or (metadata_candidates[0] if metadata_candidates else '')
            if len(meta_list) == 1:
                return meta_list[0], 'metadata'
            best = max(meta_list, key=lambda name: _name_similarity(hint, name))
            return best, 'metadata'

    if by_site_id is None:
        by_site_id = _index_nes(catalog or [])

    candidates = list(by_site_id.get(token) or [])
    if not candidates and catalog:
        prefix = f'{token}-'
        candidates = [row for row in catalog if str(row.get('ne_name', '')).startswith(prefix)]

    if candidates:
        hint = site_name
        if metadata_candidates:
            hint = metadata_candidates[0]
        if len(candidates) == 1:
            return str(candidates[0]['ne_name']), 'fm'
        best = max(
            candidates,
            key=lambda row: _name_similarity(hint, str(row.get('ne_name', ''))),
        )
        return str(best['ne_name']), 'fm'

    return None, ''


def _apply_cache_payload(payload: dict[str, Any]) -> None:
    nes = payload.get('nes') or []
    by_site_id = payload.get('nes_by_site_id') or _index_nes(nes)
    _CACHE['nes'] = nes
    _CACHE['nes_by_site_id'] = by_site_id
    _CACHE['mo_columns'] = payload.get('mo_columns') or {}
    _CACHE['mo_catalog'] = payload.get('mo_catalog') or []
    _CACHE['commands_by_product'] = payload.get('commands_by_product') or {}
    _CACHE['product_samples'] = payload.get('product_samples') or {}
    _CACHE['sample_ne'] = payload.get('sample_ne', '')
    _CACHE['fetched_at'] = float(payload.get('fetched_at') or time.time())


def save_discovery_to_disk(result: dict[str, Any] | None = None) -> Path:
    """Persist site_id → U2020 meName catalog for reuse across app restarts."""
    payload = result or {
        'nes': _CACHE.get('nes') or [],
        'nes_by_site_id': _CACHE.get('nes_by_site_id') or {},
        'mo_columns': _CACHE.get('mo_columns') or {},
        'sample_ne': _CACHE.get('sample_ne', ''),
        'fetched_at': _CACHE.get('fetched_at') or time.time(),
        'ne_count': len(_CACHE.get('nes') or []),
    }
    _CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CATALOG_PATH.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    return _CATALOG_PATH


def load_discovery_from_disk() -> bool:
    """Load persisted catalog if memory cache is empty."""
    if _CACHE.get('nes'):
        return True

    candidates = [_CATALOG_PATH, Path('reports/huawei_u2020_discovery.json')]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        if not payload.get('nes'):
            continue
        _apply_cache_payload(payload)
        return True
    return False


def get_cached_discovery(*, max_age_sec: int = _CACHE_TTL_SEC) -> dict[str, Any] | None:
    if not _CACHE.get('nes'):
        load_discovery_from_disk()
    if not _CACHE.get('nes'):
        return None
    if max_age_sec > 0 and time.time() - float(_CACHE.get('fetched_at') or 0) > max_age_sec:
        return None
    return _CACHE


def refresh_discovery_cache(
    client: HuaweiCmClient,
    *,
    include_history: bool = True,
    discover_mos: bool = True,
    sample_ne_for_mo: str = '',
    max_pages_per_type: int = 200,
) -> dict[str, Any]:
    result = discover_u2020_inventory(
        client,
        include_history=include_history,
        sample_ne_for_mo=sample_ne_for_mo,
        discover_mos=discover_mos,
        max_pages_per_type=max_pages_per_type,
    )
    _apply_cache_payload({
        **result,
        'fetched_at': time.time(),
    })
    save_discovery_to_disk(_CACHE)
    return result


def resolve_ne_names_with_cache(
    site_ids: list[str],
    site_names_by_id: dict[str, str] | None = None,
) -> tuple[list[str], list[str]]:
    """
    Resolve site ids to U2020 neNames using cached discovery.

    Returns (resolved_names, unresolved_site_ids).
    """
    site_names_by_id = dict(site_names_by_id or {})
    missing = [sid for sid in site_ids if not str(site_names_by_id.get(sid) or '').strip()]
    if missing:
        from core.cm_extractor.site_catalog import _lookup_huawei_site_names

        site_names_by_id.update(_lookup_huawei_site_names(missing))

    from core.cm_extractor.site_catalog import lookup_huawei_metadata_ne_candidates

    metadata_by_id, _metadata_alts = lookup_huawei_metadata_ne_candidates(site_ids)

    cache = get_cached_discovery(max_age_sec=10**9) or _CACHE
    catalog = cache.get('nes') or []
    by_site_id = cache.get('nes_by_site_id') or _index_nes(catalog)

    resolved: list[str] = []
    unresolved: list[str] = []
    for site_id in site_ids:
        ne_name, _source = resolve_u2020_ne_name(
            site_id,
            site_names_by_id.get(site_id, ''),
            catalog,
            by_site_id=by_site_id,
            allow_metadata_fallback=True,
            metadata_candidates=metadata_by_id.get(site_id) or [],
        )
        if ne_name:
            resolved.append(ne_name)
        else:
            unresolved.append(site_id)
    return resolved, unresolved
