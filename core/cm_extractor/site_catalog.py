"""Nokia site lists from PrimeNet metadata database, by CM scope level."""

from __future__ import annotations

import re
import time

from db.runtime import connect_metadata, execute_query

SCOPE_LEVELS = ('MRBTS', 'RNC', 'BSC')
_PASTE_SPLIT_RE = re.compile(r'[\s,;]+')
# NetAct MRBTS instance ids often prefix PrimeNet metadata ids (e.g. 50801 → 801).
_NOKIA_NETACT_MRBTS_PREFIXES = ('50', '51', '52', '53', '54', '55')

_KNOWN_METADATA_IDS_CACHE: set[str] | None = None
_METADATA_TO_NETACT_MAP: dict[str, str] | None = None
_METADATA_TO_NETACT_BUILT_AT: float = 0.0


def normalize_scope_level(scope_level: str) -> str:
    level = (scope_level or 'MRBTS').strip().upper()
    if level not in SCOPE_LEVELS:
        raise ValueError(f'Scope must be one of: {", ".join(SCOPE_LEVELS)}')
    return level


def resolve_scope_instance_id(
    site_id: str,
    scope_level: str,
    *,
    site_name: str = '',
    known_metadata_ids: set[str] | None = None,
) -> str:
    """
    Map a metadata site id to the NetAct MO instance() used in distNames.

    PrimeNet 3G RNC ids are often stored as 2012 (RNC12) while NetAct uses 12.
    MRBTS metadata ids (e.g. 5635) often map to prefixed NetAct ids (e.g. 55635).
    """
    level = normalize_scope_level(scope_level)
    token = str(site_id or '').strip()
    if not token:
        return ''
    if level == 'MRBTS':
        return resolve_nokia_netact_site_id(token, known_metadata_ids=known_metadata_ids) or token

    if level == 'RNC':
        name = (site_name or '').strip().upper()
        if name.startswith('RNC') and name[3:].isdigit():
            return name[3:]
        if token.isdigit() and len(token) == 4 and token.startswith('20'):
            suffix = str(int(token) - 2000)
            if suffix.isdigit():
                return suffix
        return token

    return token


def _rnc_dn_needles(token: str, resolved: str) -> tuple[str, ...]:
    """
    RNC distNames vary by MO class on NetAct (e.g. PLMN/RNC-2012 vs NOKRNC:RNC/RNC-12).

    Include PrimeNet ids and the short CM instance form so filtering matches both.
    """
    needles: list[str] = []
    seen: set[str] = set()
    for value in (token, resolved):
        value = str(value or '').strip()
        if not value:
            continue
        candidates = [value]
        if value.isdigit():
            if len(value) == 4 and value.startswith('20'):
                candidates.append(str(int(value) - 2000))
            elif len(value) <= 3:
                candidates.append(f'20{value.zfill(2)}')
        for candidate in candidates:
            needle = f'/RNC-{candidate}'
            if needle not in seen:
                seen.add(needle)
                needles.append(needle)
    return tuple(needles)


def scope_dn_needles(
    site_id: str,
    scope_level: str,
    *,
    site_name: str = '',
) -> tuple[str, ...]:
    """DistName substrings used to keep MOs for one scope element."""
    level = normalize_scope_level(scope_level)
    token = str(site_id or '').strip()
    if not token:
        return ()

    resolved = resolve_scope_instance_id(token, level, site_name=site_name)

    if level == 'MRBTS':
        tokens = {token, resolved}
        if resolved and resolved != token:
            tokens.add(resolved)
        netact = resolve_nokia_netact_site_id(token)
        if netact:
            tokens.add(netact)
        return tuple(
            f'/{prefix}-{value}'
            for value in tokens
            for prefix in ('MRBTS', 'LNBTS', 'NRBTS')
        )
    if level == 'RNC':
        return _rnc_dn_needles(token, resolved)
    return (f'/BSC-{token}', f'/BSC-{resolved}') if resolved != token else (f'/BSC-{token}',)


def _known_nokia_metadata_site_ids(*, force_refresh: bool = False) -> set[str]:
    global _KNOWN_METADATA_IDS_CACHE
    if not force_refresh and _KNOWN_METADATA_IDS_CACHE is not None:
        return _KNOWN_METADATA_IDS_CACHE
    conn = connect_metadata()
    try:
        rows = execute_query(
            conn,
            "SELECT site_id FROM sites WHERE NULLIF(TRIM(site_id), '') IS NOT NULL",
            [],
        ).fetchall()
        known = {str(row['site_id']).strip() for row in rows if str(row['site_id'] or '').strip()}
    finally:
        conn.close()
    _KNOWN_METADATA_IDS_CACHE = known
    return known


def invalidate_nokia_site_id_caches() -> None:
    """Clear in-memory Nokia site-id mapping caches (e.g. after metadata sync)."""
    global _KNOWN_METADATA_IDS_CACHE, _METADATA_TO_NETACT_MAP, _METADATA_TO_NETACT_BUILT_AT
    _KNOWN_METADATA_IDS_CACHE = None
    _METADATA_TO_NETACT_MAP = None
    _METADATA_TO_NETACT_BUILT_AT = 0.0


def resolve_nokia_metadata_site_id(
    netact_site_id: str,
    *,
    known_metadata_ids: set[str] | None = None,
) -> str:
    """
    Map a NetAct MRBTS instance id to the PrimeNet metadata ``site_id``.

    NetAct NEs often prefix the metadata id (``50801`` → ``801``,
    ``53308`` → ``3308``). When multiple metadata ids are suffixes of the
    NetAct id (``308`` and ``3308`` both suffix ``53308``), prefer the
    **longest** known metadata id so shorter sites are not chosen by
    mistake.

    When ``known_metadata_ids`` is supplied, only returns a mapped id that
    exists in metadata; otherwise returns the legacy two-digit-prefix form.
    """
    token = str(netact_site_id or '').strip()
    if not token:
        return ''
    if known_metadata_ids is not None and token in known_metadata_ids:
        return token

    if known_metadata_ids is not None and token.isdigit() and len(token) >= 4:
        # Prefer longest proper suffix that exists in metadata (min length 2).
        best = ''
        for length in range(len(token) - 1, 1, -1):
            cand = token[-length:]
            variants = [cand]
            stripped = cand.lstrip('0')
            if stripped and stripped not in variants:
                variants.append(stripped)
            for candidate in variants:
                if candidate in known_metadata_ids and len(candidate) > len(best):
                    best = candidate
            if best:
                return best
        return token

    if len(token) == 5 and token.isdigit() and token[:2] in _NOKIA_NETACT_MRBTS_PREFIXES:
        suffix = token[2:]
        candidates: list[str] = []
        if suffix:
            candidates.append(suffix)
            stripped = suffix.lstrip('0')
            if stripped and stripped not in candidates:
                candidates.append(stripped)
        for candidate in candidates:
            if known_metadata_ids is None or candidate in known_metadata_ids:
                return candidate
    return token


def _metadata_to_netact_map(known_metadata_ids: set[str]) -> dict[str, str]:
    """Build metadata site_id → NetAct MRBTS instance map from discovery cache."""
    global _METADATA_TO_NETACT_MAP, _METADATA_TO_NETACT_BUILT_AT
    try:
        from core.cm_extractor import nokia_discovery
        from core.cm_extractor.nokia_discovery import get_cached_nokia_inventory, reload_inventory_from_disk

        reload_inventory_from_disk()
        records = get_cached_nokia_inventory('MRBTS') or []
        fetched_at = float(nokia_discovery._CACHE.get('fetched_at') or time.time())
    except Exception:
        records = []
        fetched_at = time.time()

    if (
        _METADATA_TO_NETACT_MAP is not None
        and _METADATA_TO_NETACT_BUILT_AT >= fetched_at
    ):
        return _METADATA_TO_NETACT_MAP

    mapping: dict[str, str] = {}
    for rec in records:
        netact = str(rec.get('site_id') or '').strip()
        if not netact:
            continue
        metadata_id = resolve_nokia_metadata_site_id(netact, known_metadata_ids=known_metadata_ids)
        if metadata_id and metadata_id not in mapping:
            mapping[metadata_id] = netact

    _METADATA_TO_NETACT_MAP = mapping
    _METADATA_TO_NETACT_BUILT_AT = fetched_at
    return mapping


def _lookup_netact_site_id_from_cache(
    metadata_site_id: str,
    known_metadata_ids: set[str],
) -> str:
    """Return the NetAct MRBTS instance id for a metadata site id from discovery cache."""
    token = str(metadata_site_id or '').strip()
    if not token:
        return ''
    return _metadata_to_netact_map(known_metadata_ids).get(token, '')


def _netact_candidates_for_metadata(metadata_site_id: str) -> list[str]:
    """Build likely 5-digit NetAct MRBTS ids from a metadata site id."""
    token = str(metadata_site_id or '').strip()
    if not token or not token.isdigit():
        return []
    suffix = token.zfill(3) if len(token) <= 3 else token[-3:]
    return [f'{prefix}{suffix}' for prefix in _NOKIA_NETACT_MRBTS_PREFIXES if len(f'{prefix}{suffix}') == 5]


def resolve_nokia_netact_site_id(
    metadata_site_id: str,
    *,
    known_metadata_ids: set[str] | None = None,
) -> str:
    """
    Map a PrimeNet metadata ``site_id`` to the NetAct MRBTS instance() in distNames.

    Inverse of :func:`resolve_nokia_metadata_site_id` — e.g. ``5635`` → ``55635``,
    ``801`` → ``50801``. Falls back to the input token when no mapping is found.
    """
    token = str(metadata_site_id or '').strip()
    if not token:
        return ''
    known = known_metadata_ids if known_metadata_ids is not None else _known_nokia_metadata_site_ids()

    # Input may already be a NetAct instance id (e.g. 55635, 50801).
    if resolve_nokia_metadata_site_id(token, known_metadata_ids=known) != token:
        return token

    for candidate in _netact_candidates_for_metadata(token):
        if resolve_nokia_metadata_site_id(candidate, known_metadata_ids=known) == token:
            return candidate

    cached = _lookup_netact_site_id_from_cache(token, known)
    if cached and cached != token:
        return cached

    return token


def _site_area_index() -> dict[str, str]:
    from core.site_area import build_site_area_index

    return build_site_area_index()


def canonical_cm_area(
    site_id: str,
    fallback: str = '',
    *,
    index: dict[str, str] | None = None,
) -> str:
    """Canonical CM area label for a site (North Jordan, not North / Zarqa)."""
    from core.site_area import canonicalize_area, resolve_site_area

    token = str(site_id or '').strip()
    if token:
        resolved = resolve_site_area(token, index=index)
        if resolved:
            return resolved
    return canonicalize_area(fallback) or ''


def areas_from_site_items(items: list[dict[str, Any]]) -> list[dict[str, str | int]]:
    """Distinct areas with site counts from a picker list (canonical names)."""
    counts: dict[str, int] = {}
    for item in items:
        area = str(item.get('area') or '').strip()
        if not area:
            continue
        counts[area] = counts.get(area, 0) + 1
    return [
        {'area': area, 'site_count': counts[area]}
        for area in sorted(counts, key=lambda a: (-counts[a], a.lower()))
    ]


def nokia_mrbts_area_for_site(
    netact_site_id: str,
    *,
    known_metadata_ids: set[str] | None = None,
    clusters: dict[str, str] | None = None,
    cluster_to_area: dict[str, str] | None = None,
    area_map: dict[str, dict[str, str]] | None = None,
    site_area_index: dict[str, str] | None = None,
) -> tuple[str, str, str]:
    """Return ``(metadata_site_id, canonical area, cluster)`` for a NetAct MRBTS id."""
    metadata_site_id = resolve_nokia_metadata_site_id(
        netact_site_id,
        known_metadata_ids=known_metadata_ids,
    )
    lookup_ids = [metadata_site_id]
    if metadata_site_id != netact_site_id:
        lookup_ids.append(str(netact_site_id or '').strip())

    clusters = clusters if clusters is not None else site_cluster_map('nokia', 'MRBTS')
    cluster_to_area = cluster_to_area if cluster_to_area is not None else cluster_area_map()
    area_map = area_map if area_map is not None else nokia_area_map('MRBTS')

    cluster = ''
    for lookup_id in lookup_ids:
        if lookup_id and lookup_id in clusters:
            cluster = clusters[lookup_id]
            break

    raw_area = ''
    for lookup_id in lookup_ids:
        if lookup_id and lookup_id in area_map:
            raw_area = str(area_map[lookup_id].get('area') or '').strip()
            if raw_area:
                break
    if not raw_area and cluster:
        raw_area = str(cluster_to_area.get(cluster) or '').strip()

    area = canonical_cm_area(
        metadata_site_id or str(netact_site_id or '').strip(),
        fallback=raw_area,
        index=site_area_index,
    )
    return metadata_site_id, area, cluster


def parse_site_id_text(text: str) -> list[str]:
    """Split pasted site-id text into a unique ordered list."""
    seen: set[str] = set()
    result: list[str] = []
    for token in _PASTE_SPLIT_RE.split(text or ''):
        site_id = token.strip()
        if site_id and site_id not in seen:
            seen.add(site_id)
            result.append(site_id)
    return result


def list_netact_plmn_controllers(
    client,
    scope_level: str,
    *,
    conf_id: int = 1,
) -> list[dict[str, str]]:
    """
    Return RNC/BSC controllers from NetAct PLMN tree: [{instance, dn}].

    Import_Export uses these DNs (e.g. PLMN-PLMN/RNC-2012), not short CM ids (RNC-12).
    """
    level = normalize_scope_level(scope_level)
    if level == 'RNC':
        mo_segment = 'RNC'
    elif level == 'BSC':
        mo_segment = 'BSC'
    else:
        return []

    rows = client.query(
        f'/NetActCommon:PLMN/{mo_segment} as $c',
        ['dn()', 'instance()'],
        conf_id=conf_id,
    )
    items: list[dict[str, str]] = []
    for row in rows or []:
        if not row:
            continue
        dn = str(row[0] or '').strip()
        instance = str(row[1] if len(row) > 1 else '').strip()
        if not dn:
            continue
        if not instance and '/' in dn:
            instance = dn.rsplit('-', 1)[-1]
        items.append({'instance': instance, 'dn': dn})
    return items


def normalize_controller_mo_dn(
    mo_id: str,
    site_id: str,
    scope_level: str,
) -> str:
    """
    Rewrite short CM controller segments in a distName for getManagedObjects.

    NetAct returns child MOs under ``/RNC-12/`` while parameter reads require
    the PLMN instance form ``/RNC-2012/`` (PrimeNet id 2012 = RNC12).
    """
    level = normalize_scope_level(scope_level)
    mo_id = str(mo_id or '').strip()
    site_id = str(site_id or '').strip()
    if not mo_id or not site_id or level not in ('RNC', 'BSC'):
        return mo_id

    plmn_inst = site_id
    short = resolve_scope_instance_id(site_id, level)
    if not short or short == plmn_inst:
        return mo_id

    segment = level
    old_prefix = f'/{segment}-{short}'
    new_prefix = f'/{segment}-{plmn_inst}'
    if old_prefix in mo_id:
        return mo_id.replace(old_prefix, new_prefix, 1)
    if mo_id.endswith(f'/{segment}-{short}'):
        return mo_id[: -len(f'/{segment}-{short}')] + f'/{segment}-{plmn_inst}'
    return mo_id


def normalize_controller_mo_ids(
    mo_ids: list[str],
    site_id: str,
    scope_level: str,
) -> list[str]:
    """Deduped distNames with PLMN-instance controller segments."""
    seen: set[str] = set()
    out: list[str] = []
    for mo_id in mo_ids:
        normalized = normalize_controller_mo_dn(mo_id, site_id, scope_level)
        if normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    return out


def resolve_bulk_export_dns(
    client,
    site_ids: list[str],
    *,
    scope_level: str,
    plmn_prefix: str = 'PLMN-PLMN',
) -> list[str]:
    """
    Map PrimeNet site ids to Import_Export DN scope strings.

    CM Operations actualExport expects PLMN-tree DNs like PLMN-PLMN/RNC-2012
    or PLMN-PLMN/MRBTS-1201.
    """
    level = normalize_scope_level(scope_level)
    if level == 'MRBTS':
        resolved: list[str] = []
        seen: set[str] = set()
        for raw_id in site_ids:
            token = str(raw_id or '').strip()
            if not token:
                continue
            instance = resolve_nokia_netact_site_id(token) or token
            dn = f'{plmn_prefix}/MRBTS-{instance}'
            if dn not in seen:
                seen.add(dn)
                resolved.append(dn)
        return resolved

    if level not in ('RNC', 'BSC'):
        raise ValueError('Bulk export DN resolution supports MRBTS, RNC, and BSC')

    controllers = list_netact_plmn_controllers(client, level)
    by_instance = {c['instance']: c['dn'] for c in controllers if c.get('instance')}
    by_dn_suffix: dict[str, str] = {}
    segment = 'RNC' if level == 'RNC' else 'BSC'
    for ctrl in controllers:
        dn = ctrl.get('dn') or ''
        suffix = dn.rsplit('/', 1)[-1]
        if suffix.startswith(f'{segment}-'):
            by_dn_suffix[suffix.split('-', 1)[1]] = dn

    resolved: list[str] = []
    seen: set[str] = set()
    for raw_id in site_ids:
        token = str(raw_id or '').strip()
        if not token:
            continue

        candidates = [token]
        if level == 'RNC' and token.isdigit():
            if len(token) == 4 and token.startswith('20'):
                short = str(int(token) - 2000)
                candidates = [token, short]
            elif len(token) <= 3:
                # Prefer PLMN instance 20xx (e.g. RNC-2012); short id RNC-12 exports 0 MOs.
                candidates = [f'20{token.zfill(2)}', token]

        dn = ''
        for candidate in candidates:
            if candidate in by_instance:
                dn = by_instance[candidate]
                break
            if candidate in by_dn_suffix:
                dn = by_dn_suffix[candidate]
                break

        if not dn:
            fallback_id = token
            if level == 'RNC' and token.isdigit():
                if len(token) == 4 and token.startswith('20'):
                    fallback_id = token
                elif len(token) <= 3:
                    fallback_id = f'20{token.zfill(2)}'
            dn = f'{plmn_prefix}/{segment}-{fallback_id}'

        if dn not in seen:
            seen.add(dn)
            resolved.append(dn)
    return resolved


def list_nokia_db_sites(
    query: str = '',
    *,
    scope_level: str = 'MRBTS',
    limit: int = 2000,
) -> list[dict[str, str | int | float | None]]:
    """
    Return Nokia sites/elements for CM extraction scope.

    - MRBTS: LTE/NR eNB/gNB ids (maps to NetAct MRBTS instance)
    - RNC: 3G RNC ids from cells_3g.rnc
    - BSC: 2G BSC ids from cells_2g.bsc
    """
    level = normalize_scope_level(scope_level)
    conn = connect_metadata()
    try:
        params: list[object] = []
        term = (query or '').strip()
        limit = max(1, min(int(limit), 5000))

        if level == 'MRBTS':
            where = [
                "LOWER(COALESCE(s.vendor, '')) LIKE '%nokia%'",
                "COALESCE(s.status, 'Active') = 'Active'",
                "NULLIF(TRIM(s.site_id), '') IS NOT NULL",
            ]
            if term:
                where.append('(s.site_id LIKE ? OR s.site_name LIKE ?)')
                like = f'%{term}%'
                params.extend([like, like])
            sql = f'''
                SELECT
                    s.site_id,
                    s.site_name,
                    s.latitude,
                    s.longitude,
                    (
                        SELECT COUNT(*)
                        FROM cells c
                        WHERE c.site_id = s.site_id
                          AND COALESCE(c.status, 'Active') = 'Active'
                    ) AS cell_count
                FROM sites s
                WHERE {' AND '.join(where)}
                ORDER BY s.site_name COLLATE NOCASE
                LIMIT ?
            '''
        elif level == 'RNC':
            where = [
                "LOWER(COALESCE(vendor, '')) LIKE '%nokia%'",
                "NULLIF(TRIM(rnc), '') IS NOT NULL",
            ]
            if term:
                where.append('(rnc LIKE ? OR rnc_name LIKE ?)')
                like = f'%{term}%'
                params.extend([like, like])
            sql = f'''
                SELECT
                    rnc AS site_id,
                    MAX(COALESCE(NULLIF(TRIM(rnc_name), ''), rnc)) AS site_name,
                    MAX(CAST(lat AS REAL)) AS latitude,
                    MAX(CAST("long" AS REAL)) AS longitude,
                    COUNT(DISTINCT cell_name) AS cell_count
                FROM cells_3g
                WHERE {' AND '.join(where)}
                GROUP BY rnc
                ORDER BY site_name COLLATE NOCASE
                LIMIT ?
            '''
        else:
            where = [
                "LOWER(COALESCE(vendor, '')) LIKE '%nokia%'",
                "NULLIF(TRIM(bsc), '') IS NOT NULL",
            ]
            if term:
                where.append('(bsc LIKE ? OR bsc_name LIKE ?)')
                like = f'%{term}%'
                params.extend([like, like])
            sql = f'''
                SELECT
                    bsc AS site_id,
                    MAX(COALESCE(NULLIF(TRIM(bsc_name), ''), bsc)) AS site_name,
                    MAX(CAST(lat AS REAL)) AS latitude,
                    MAX(CAST("long" AS REAL)) AS longitude,
                    COUNT(DISTINCT cell_name) AS cell_count
                FROM cells_2g
                WHERE {' AND '.join(where)}
                GROUP BY bsc
                ORDER BY site_name COLLATE NOCASE
                LIMIT ?
            '''

        params.append(limit)
        rows = execute_query(conn, sql, params).fetchall()
        area_map = nokia_area_map(level) if level == 'MRBTS' else {}
        site_area_index = _site_area_index() if level == 'MRBTS' else {}
        items = []
        for row in rows:
            site_id = str(row['site_id'])
            site_name = row['site_name'] or site_id
            netact_id = resolve_scope_instance_id(site_id, level, site_name=site_name)
            area_info = area_map.get(site_id) or {}
            label = f'{site_name} ({site_id})'
            if level == 'RNC' and netact_id != site_id:
                label = f'{site_name} ({site_id} → NetAct {netact_id})'
            area = ''
            if level == 'MRBTS':
                area = canonical_cm_area(
                    site_id,
                    fallback=str(area_info.get('area') or ''),
                    index=site_area_index,
                )
            items.append({
                'site_id': site_id,
                'metadata_site_id': site_id,
                'site_name': site_name,
                'netact_instance_id': netact_id,
                'area': area,
                'cluster': area_info.get('cluster', ''),
                'latitude': row['latitude'],
                'longitude': row['longitude'],
                'cell_count': row['cell_count'] or 0,
                'scope_level': level,
                'label': label,
            })
        return items
    finally:
        conn.close()


def canonical_controller_site_id(instance: str, dn: str, scope_level: str) -> str:
    """
    Normalize RNC/BSC ids for the picker and bulk export.

    NetAct returns both short CM instances (``12``) and PLMN instances (``2012``).
    PrimeNet metadata uses the 20xx form (RNC12 → ``2012``).
    """
    level = normalize_scope_level(scope_level)
    token = str(instance or '').strip()
    dn = str(dn or '').strip()
    if dn:
        suffix = dn.rsplit('/', 1)[-1]
        marker = f'{level}-'
        if suffix.startswith(marker):
            from_dn = suffix[len(marker):].strip()
            if from_dn:
                token = from_dn
    if level == 'RNC' and token.isdigit() and len(token) <= 3:
        return f'20{token.zfill(2)}'
    return token


def controller_dn_lookup(
    api_records: list[dict[str, str]],
    scope_level: str,
) -> dict[str, str]:
    """Map PrimeNet controller id (e.g. ``2012``) to NetAct PLMN DN from discovery."""
    level = normalize_scope_level(scope_level)
    out: dict[str, str] = {}
    for rec in api_records or []:
        dn = str(rec.get('dn') or '').strip()
        if not dn:
            continue
        cid = canonical_controller_site_id(str(rec.get('site_id') or ''), dn, level)
        if cid:
            out[cid] = dn
    return out


def _nokia_metadata_names(site_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Look up site_name + lat/long for discovered ids (for nicer picker labels)."""
    ids = [s for s in dict.fromkeys(site_ids) if s]
    if not ids:
        return {}
    out: dict[str, dict[str, Any]] = {}
    conn = connect_metadata()
    try:
        chunk = 900
        for start in range(0, len(ids), chunk):
            part = ids[start:start + chunk]
            placeholders = ','.join('?' for _ in part)
            rows = execute_query(
                conn,
                f'SELECT site_id, site_name, latitude, longitude FROM sites '
                f'WHERE site_id IN ({placeholders})',
                part,
            ).fetchall()
            for row in rows:
                out[str(row['site_id'])] = {
                    'site_name': row['site_name'] or '',
                    'latitude': row['latitude'],
                    'longitude': row['longitude'],
                }
        return out
    finally:
        conn.close()


def list_nokia_inventory_sites(
    query: str = '',
    *,
    scope_level: str = 'MRBTS',
    limit: int = 2000,
) -> tuple[list[dict[str, Any]], str]:
    """
    Build the Nokia picker list from the API-discovered NetAct inventory.

    MRBTS uses API discovery (site-level NEs). RNC/BSC use metadata controller
    ids from ``cells_3g`` / ``cells_2g`` (e.g. ``2012`` for RNC12) because NetAct
    also exposes short CM instances (``12``) that are not PrimeNet site ids.

    Returns ``(items, source)`` where source is ``'api'`` when served from the
    discovery cache or ``'metadata'`` when it falls back to the local DB
    (e.g. before the first discovery has run).
    """
    level = normalize_scope_level(scope_level)
    records: list[dict[str, str]] | None = None
    try:
        from core.cm_extractor.nokia_discovery import ensure_nokia_inventory_enriched, get_cached_nokia_inventory

        ensure_nokia_inventory_enriched(persist=True)
        records = get_cached_nokia_inventory(level)
    except Exception:
        records = None

    if level in ('RNC', 'BSC'):
        items = list_nokia_db_sites(query, scope_level=level, limit=limit)
        dn_map = controller_dn_lookup(records or [], level)
        for item in items:
            dn = dn_map.get(str(item['site_id']))
            if dn:
                item['dn'] = dn
                item['source'] = 'metadata+api'
            else:
                item['source'] = 'metadata'
        return items, 'metadata'

    if not records:
        return list_nokia_db_sites(query, scope_level=level, limit=limit), 'metadata'

    known_metadata_ids = _known_nokia_metadata_site_ids()
    metadata_ids = [
        resolve_nokia_metadata_site_id(str(rec.get('site_id') or ''), known_metadata_ids=known_metadata_ids)
        for rec in records
    ]
    names = _nokia_metadata_names([mid for mid in metadata_ids if mid])
    clusters = site_cluster_map('nokia', 'MRBTS')
    cluster_to_area = cluster_area_map()
    area_map = nokia_area_map('MRBTS')
    site_area_index = _site_area_index()
    term = (query or '').strip().lower()
    cap = max(1, min(int(limit), 5000))

    items: list[dict[str, Any]] = []
    for rec, metadata_site_id in zip(records, metadata_ids):
        site_id = str(rec.get('site_id') or '').strip()
        if not site_id:
            continue
        meta = names.get(metadata_site_id) or names.get(site_id) or {}
        site_name = meta.get('site_name') or rec.get('ne_name') or site_id
        _meta_id, area, cluster = nokia_mrbts_area_for_site(
            site_id,
            known_metadata_ids=known_metadata_ids,
            clusters=clusters,
            cluster_to_area=cluster_to_area,
            area_map=area_map,
            site_area_index=site_area_index,
        )
        if _meta_id:
            metadata_site_id = _meta_id
        netact_id = resolve_scope_instance_id(
            site_id,
            level,
            site_name=site_name,
            known_metadata_ids=known_metadata_ids,
        )
        label = f'{site_name} ({site_id})'
        if metadata_site_id and metadata_site_id != site_id:
            label = f'{site_name} ({metadata_site_id} → NetAct {site_id})'
        elif level == 'RNC' and netact_id != site_id:
            label = f'{site_name} ({site_id} → NetAct {netact_id})'
        if term:
            hay = (
                f'{site_id} {metadata_site_id} {site_name} {area} {cluster} '
                f'{rec.get("dn", "")}'
            ).lower()
            if term not in hay:
                continue
        items.append({
            'site_id': site_id,
            'metadata_site_id': metadata_site_id,
            'site_name': site_name,
            'netact_instance_id': netact_id,
            'area': area,
            'cluster': cluster,
            'latitude': meta.get('latitude'),
            'longitude': meta.get('longitude'),
            'cell_count': 0,
            'scope_level': level,
            'label': label,
            'source': 'api',
        })

    items.sort(key=lambda it: str(it['site_name']).lower())
    return items[:cap], 'api'


def list_nokia_inventory_areas(scope_level: str = 'MRBTS') -> list[dict[str, str | int]]:
    """Area list (with counts) from the same Nokia picker population as sites."""
    level = normalize_scope_level(scope_level)
    if level != 'MRBTS':
        return []
    items, _source = list_nokia_inventory_sites('', scope_level=level, limit=5000)
    return areas_from_site_items(items)


HUAWEI_SCOPE_LEVELS = ('ENODEB', 'RNC', 'BSC')

HUAWEI_RNC_PRODUCTS = frozenset({
    'BSC6900 UMTS', 'BSC6910 UMTS', 'BSC6900 GU', 'BSC6910 GU', 'RNC',
})
HUAWEI_BSC_PRODUCTS = frozenset({
    'BSC6900 GSM', 'BSC6910 GSM', 'BSC6900 GU', 'BSC6910 GU', 'BSC',
})


def normalize_huawei_scope_level(scope_level: str) -> str:
    level = (scope_level or 'ENODEB').strip().upper()
    if level not in HUAWEI_SCOPE_LEVELS:
        raise ValueError(f'Huawei scope must be one of: {", ".join(HUAWEI_SCOPE_LEVELS)}')
    return level


def _controller_numeric_token(value: str) -> str:
    digits = re.sub(r'\D+', '', value or '')
    return digits.lstrip('0')


def match_huawei_controller_ne_name(
    controller_id: str,
    controller_name: str = '',
    catalog: list[dict] | None = None,
    *,
    scope_level: str = 'RNC',
) -> str:
    """Map a PrimeNet RNC/BSC id to a U2020 controller meName (e.g. RNC01, BSC_HQ_01)."""
    level = normalize_huawei_scope_level(scope_level)
    if level not in ('RNC', 'BSC'):
        return ''

    wanted = [
        str(token).strip()
        for token in (controller_name, controller_id)
        if str(token or '').strip()
    ]
    if not wanted:
        return ''

    products = HUAWEI_RNC_PRODUCTS if level == 'RNC' else HUAWEI_BSC_PRODUCTS
    product_ok = {item.upper() for item in products}
    prefix = 'RNC' if level == 'RNC' else 'BSC'
    nes = []
    for row in catalog or []:
        name = str(row.get('ne_name') or '').strip()
        if not name:
            continue
        product = str(row.get('product_name') or '').strip().upper()
        if product in product_ok or (not product and name.upper().startswith(prefix)):
            nes.append(name)
    by_upper = {name.upper(): name for name in nes}

    for token in wanted:
        hit = by_upper.get(token.upper())
        if hit:
            return hit

    if level == 'RNC':
        for token in wanted:
            digits = _controller_numeric_token(token)
            if not digits:
                continue
            for name in nes:
                upper = name.upper().replace(' ', '')
                if upper.startswith('RNC') and _controller_numeric_token(upper[3:]) == digits:
                    return name

    if level == 'BSC':
        for token in wanted:
            needle = token.upper().replace(' ', '_')
            if len(needle) < 3 or needle.isdigit():
                continue
            for name in nes:
                hay = name.upper().replace(' ', '_')
                if needle in hay or hay.endswith(needle):
                    return name

    for token in wanted:
        upper = token.upper().replace(' ', '_')
        if upper.startswith('RNC') or upper.startswith('BSC'):
            return token.strip()
    return ''


def resolve_huawei_ne_name(site_id: str, site_name: str = '') -> str:
    """
    Legacy fallback when no U2020 catalog is loaded.

    Prefer ``resolve_huawei_ne_names()`` which maps by site_id via FM discovery.
    """
    names, _alts = lookup_huawei_metadata_ne_candidates([str(site_id or '').strip()])
    candidates = names.get(str(site_id or '').strip()) or []
    if candidates:
        return candidates[0]
    return str(site_id or '').strip()


_HUAWEI_METADATA_NE_SOURCES = (
    ('cells_5g', 'gnb_id_actual', 'gnb_name', 50),
    ('cells_4g_fdd', 'enb_id_actual', 'enb_name', 40),
    ('cells_4g_tdd', 'enb_id_actual', 'enb_name', 40),
    ('cells_3g', 'nodeb_id', 'nodeb_name', 30),
    ('cells_2g', 'site_id', 'site_name', 20),
    ('sites', 'site_id', 'site_name', 10),
)


def _metadata_name_score(site_id: str, name: str, source_score: int) -> int:
    """Score metadata names by technology source only — never invent UL_/U_ variants."""
    token = str(site_id or '').strip()
    text = str(name or '').strip()
    if not token or not text.startswith(f'{token}-'):
        return 0
    if len(text) <= len(token) + 2:
        return 0
    return source_score


_HUAWEI_SCOPE_MIN_METADATA_SCORE = {
    'ENODEB': 40,
}

_HUAWEI_LTE_CELL_TABLES = (
    ('cells_4g_fdd', 'enb_id_actual'),
    ('cells_4g_tdd', 'enb_id_actual'),
)
_HUAWEI_NR_CELL_TABLES = (
    ('cells_5g', 'gnb_id_actual'),
)


def _huawei_site_ids_with_cell_tables(
    site_ids: list[str],
    tables: tuple[tuple[str, str], ...],
) -> set[str]:
    """Return site ids that have at least one Huawei row in the given cell tables."""
    ids = [str(site_id).strip() for site_id in (site_ids or []) if str(site_id).strip()]
    if not ids:
        return set()

    found: set[str] = set()
    conn = connect_metadata()
    try:
        chunk_size = 900
        for table, id_col in tables:
            for start in range(0, len(ids), chunk_size):
                part = ids[start:start + chunk_size]
                placeholders = ','.join('?' for _ in part)
                try:
                    rows = execute_query(
                        conn,
                        f'''
                            SELECT DISTINCT CAST({id_col} AS TEXT) AS site_id
                            FROM {table}
                            WHERE CAST({id_col} AS TEXT) IN ({placeholders})
                              AND LOWER(COALESCE(vendor, '')) LIKE '%huawei%'
                        ''',
                        part,
                    ).fetchall()
                except Exception:
                    continue
                for row in rows:
                    sid = str(row['site_id'] or '').strip()
                    if sid:
                        found.add(sid)
    finally:
        conn.close()
    return found


def huawei_site_ids_with_lte(site_ids: list[str]) -> set[str]:
    """Site ids with Huawei 4G cells in PrimeNet metadata."""
    return _huawei_site_ids_with_cell_tables(site_ids, _HUAWEI_LTE_CELL_TABLES)


def huawei_site_ids_with_nr(site_ids: list[str]) -> set[str]:
    """Site ids with Huawei 5G cells in PrimeNet metadata."""
    return _huawei_site_ids_with_cell_tables(site_ids, _HUAWEI_NR_CELL_TABLES)


def lookup_huawei_metadata_ne_candidates(
    site_ids: list[str],
    *,
    min_source_score: int = 0,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """
    Collect meName candidates from PrimeNet metadata (all cell tables + sites).

    Names are used exactly as stored in metadata — no UL_/U_ prefix synthesis.
    ``min_source_score`` excludes low-confidence sources (e.g. ``sites`` = 10) when > 0.
    Returns ``(best_first_by_site_id, alternates_by_primary_name)``.
    """
    ids = [str(site_id).strip() for site_id in (site_ids or []) if str(site_id).strip()]
    if not ids:
        return {}, {}

    raw: dict[str, dict[str, int]] = {site_id: {} for site_id in ids}
    conn = connect_metadata()
    try:
        chunk_size = 900
        for table, id_col, name_col, source_score in _HUAWEI_METADATA_NE_SOURCES:
            if source_score < min_source_score:
                continue
            for start in range(0, len(ids), chunk_size):
                part = ids[start:start + chunk_size]
                placeholders = ','.join('?' for _ in part)
                if table == 'sites':
                    sql = f'''
                        SELECT site_id, site_name
                        FROM sites
                        WHERE site_id IN ({placeholders})
                          AND NULLIF(TRIM(site_name), '') IS NOT NULL
                    '''
                else:
                    sql = f'''
                        SELECT
                            CAST({id_col} AS TEXT) AS site_id,
                            TRIM({name_col}) AS site_name
                        FROM {table}
                        WHERE CAST({id_col} AS TEXT) IN ({placeholders})
                          AND NULLIF(TRIM({name_col}), '') IS NOT NULL
                    '''
                try:
                    rows = execute_query(conn, sql, part).fetchall()
                except Exception:
                    continue
                for row in rows:
                    sid = str(row['site_id'] or '').strip()
                    name = str(row['site_name'] or '').strip()
                    if sid not in raw or not name:
                        continue
                    score = _metadata_name_score(sid, name, source_score)
                    if score <= 0:
                        continue
                    prev = raw[sid].get(name, 0)
                    if score >= prev:
                        raw[sid][name] = score
    finally:
        conn.close()

    best_first: dict[str, list[str]] = {}
    alternates: dict[str, list[str]] = {}
    for site_id in ids:
        ordered = [
            name for name, _score in sorted(
                raw.get(site_id, {}).items(),
                key=lambda item: (-item[1], -len(item[0]), item[0].lower()),
            )
        ]
        if ordered:
            best_first[site_id] = ordered
            alternates[ordered[0]] = ordered[1:]
    return best_first, alternates


def _lookup_huawei_site_names(site_ids: list[str], *, scope_level: str = 'ENODEB') -> dict[str, str]:
    """Return the best metadata meName candidate per site id."""
    candidates, _alts = lookup_huawei_metadata_ne_candidates(site_ids)
    return {
        site_id: names[0]
        for site_id, names in candidates.items()
        if names
    }


def _lookup_huawei_controller_names(ids: list[str], scope_level: str) -> dict[str, str]:
    """Map RNC/BSC ids from the cell tables to their metadata display names."""
    wanted = [str(item).strip() for item in ids if str(item).strip()]
    if not wanted:
        return {}
    level = normalize_huawei_scope_level(scope_level)
    if level == 'RNC':
        table, id_col, name_col = 'cells_3g', 'rnc', 'rnc_name'
    elif level == 'BSC':
        table, id_col, name_col = 'cells_2g', 'bsc', 'bsc_name'
    else:
        return {}

    out: dict[str, str] = {}
    conn = connect_metadata()
    try:
        chunk = 900
        for start in range(0, len(wanted), chunk):
            part = wanted[start:start + chunk]
            placeholders = ','.join('?' for _ in part)
            rows = execute_query(
                conn,
                f'''
                SELECT CAST({id_col} AS TEXT) AS cid,
                       MAX(COALESCE(NULLIF(TRIM({name_col}), ''), {id_col})) AS cname
                FROM {table}
                WHERE LOWER(COALESCE(vendor, '')) LIKE '%huawei%'
                  AND CAST({id_col} AS TEXT) IN ({placeholders})
                GROUP BY {id_col}
                ''',
                part,
            ).fetchall()
            for row in rows:
                cid = str(row['cid'] or '').strip()
                if cid:
                    out[cid] = str(row['cname'] or cid).strip() or cid
        return out
    finally:
        conn.close()


def _resolve_huawei_controller_names(
    ids: list[str],
    scope_level: str,
) -> tuple[list[str], list[str], dict[str, list[str]], list[dict[str, str]]]:
    from core.cm_extractor.huawei_discovery import get_cached_discovery, load_discovery_from_disk

    load_discovery_from_disk()
    catalog = (get_cached_discovery(max_age_sec=10**9) or {}).get('nes') or []
    names = _lookup_huawei_controller_names(ids, scope_level)
    resolved: list[str] = []
    unresolved: list[str] = []
    for controller_id in ids:
        ne_name = match_huawei_controller_ne_name(
            controller_id,
            names.get(controller_id, ''),
            catalog,
            scope_level=scope_level,
        )
        if ne_name:
            resolved.append(ne_name)
        else:
            unresolved.append(controller_id)
    return list(dict.fromkeys(resolved)), unresolved, {}, []


def resolve_huawei_ne_names(
    site_ids: list[str],
    *,
    scope_level: str = 'ENODEB',
    site_names_by_id: dict[str, str] | None = None,
) -> tuple[list[str], list[str], dict[str, list[str]], list[dict[str, str]]]:
    """Resolve site ids to U2020 MML meNames.

    Returns ``(resolved_ne_names, unresolved_site_ids, alternates_by_primary_name, skipped)``.
    Sites in ENODEB scope without Huawei 4G inventory are returned in ``skipped`` (not unresolved).
    """
    ids = [str(site_id).strip() for site_id in (site_ids or []) if str(site_id).strip()]
    if not ids:
        return [], [], {}, []

    level = normalize_huawei_scope_level(scope_level)
    if level in ('RNC', 'BSC'):
        return _resolve_huawei_controller_names(ids, level)

    min_score = _HUAWEI_SCOPE_MIN_METADATA_SCORE.get(level, 0)
    lte_site_ids = huawei_site_ids_with_lte(ids) if level == 'ENODEB' else set()

    display_names, _display_alts = lookup_huawei_metadata_ne_candidates(ids)
    skipped: list[dict[str, str]] = []
    eligible_ids: list[str] = []
    for site_id in ids:
        if level == 'ENODEB' and site_id not in lte_site_ids:
            display = (display_names.get(site_id) or [site_id])[0]
            skipped.append({
                'NE name': display,
                'Site ID': site_id,
                'Reason': 'No Huawei 4G in inventory',
            })
            continue
        eligible_ids.append(site_id)

    metadata_by_id, metadata_alts = lookup_huawei_metadata_ne_candidates(
        eligible_ids,
        min_source_score=min_score,
    )
    names = dict(site_names_by_id or {})
    for site_id, candidates in metadata_by_id.items():
        if candidates and not str(names.get(site_id) or '').strip():
            names[site_id] = candidates[0]

    from core.cm_extractor.huawei_discovery import (
        get_cached_discovery,
        load_discovery_from_disk,
        resolve_u2020_ne_name,
    )

    load_discovery_from_disk()
    cache = get_cached_discovery(max_age_sec=10**9) or {}
    catalog = cache.get('nes') or []
    by_site_id = cache.get('nes_by_site_id') or {}

    resolved: list[str] = []
    unresolved: list[str] = []
    alternates: dict[str, list[str]] = {}
    for site_id in eligible_ids:
        meta_candidates = metadata_by_id.get(site_id) or []
        ne_name, _source = resolve_u2020_ne_name(
            site_id,
            names.get(site_id, ''),
            catalog if catalog else None,
            by_site_id=by_site_id if catalog else None,
            allow_metadata_fallback=True,
            metadata_candidates=meta_candidates,
        )
        if ne_name:
            resolved.append(ne_name)
            alt_list = list(metadata_alts.get(ne_name) or [])
            for candidate in meta_candidates:
                if candidate != ne_name and candidate not in alt_list:
                    alt_list.append(candidate)
            if alt_list:
                alternates[ne_name] = alt_list
        else:
            unresolved.append(site_id)
    return resolved, unresolved, alternates, skipped


def merge_huawei_ne_names(
    site_ids: list[str],
    ne_names: list[str] | None = None,
    *,
    scope_level: str = 'ENODEB',
) -> tuple[list[str], list[str], dict[str, list[str]], list[dict[str, str]]]:
    """
    Resolve NE names from FM catalog + metadata when site ids are known.

    Explicit ``ne_names`` from the UI are ignored for mapping when ``site_ids`` are
    provided — metadata/FM resolution is authoritative (no synthetic UL_ prefixes).
    """
    ids = [str(site_id).strip() for site_id in (site_ids or []) if str(site_id).strip()]
    explicit = [str(name).strip() for name in (ne_names or []) if str(name).strip()]

    if ids:
        return resolve_huawei_ne_names(ids, scope_level=scope_level)

    if explicit:
        return explicit, [], {}, []

    return [], [], {}, {}


def _clean_cluster(value: object) -> str:
    """Normalize cluster labels (PrimeNet stores them as floats like ``10.0``)."""
    text = str(value or '').strip()
    if not text:
        return ''
    if text.endswith('.0') and text[:-2].isdigit():
        return text[:-2]
    return text


def _vendor_area_map(
    vendor_like: str,
    sources: tuple[tuple[str, str], ...],
) -> dict[str, dict[str, str]]:
    """
    Map site/NE id -> {area, cluster} from the cell inventory tables.

    The ``sites`` table has no area column, so area/cluster come from cells_*.
    First non-empty value per id wins (order ``sources`` by preference).
    """
    out: dict[str, dict[str, str]] = {}
    if not sources:
        return out

    conn = connect_metadata()
    try:
        for table, key in sources:
            sql = f'''
                SELECT
                    CAST({key} AS TEXT) AS sid,
                    COALESCE(NULLIF(TRIM(area), ''), '') AS area,
                    COALESCE(NULLIF(TRIM(cluster), ''), '') AS cluster
                FROM {table}
                WHERE LOWER(COALESCE(vendor, '')) LIKE ?
                  AND NULLIF(TRIM({key}), '') IS NOT NULL
                  AND NULLIF(TRIM(area), '') IS NOT NULL
            '''
            try:
                rows = execute_query(conn, sql, [vendor_like]).fetchall()
            except Exception:
                continue
            for row in rows:
                sid = str(row['sid'] or '').strip()
                if not sid or sid in out:
                    continue
                out[sid] = {
                    'area': str(row['area'] or '').strip(),
                    'cluster': _clean_cluster(row['cluster']),
                }
        return out
    finally:
        conn.close()


def _areas_from_map(area_map: dict[str, dict[str, str]]) -> list[dict[str, str | int]]:
    counts: dict[str, int] = {}
    for info in area_map.values():
        area = info.get('area') or ''
        if not area:
            continue
        counts[area] = counts.get(area, 0) + 1
    return [
        {'area': area, 'site_count': counts[area]}
        for area in sorted(counts, key=lambda a: (-counts[a], a.lower()))
    ]


# (table, id column) sources for area/cluster grouping, by scope level.
# cells_3g is included last as a fallback: many sites only have 3G cells
# (e.g. fiber-node / pico sites), so they would otherwise have no area.
_HUAWEI_AREA_SOURCES: dict[str, tuple[tuple[str, str], ...]] = {
    'ENODEB': (
        ('cells_4g_fdd', 'enb_id_actual'),
        ('cells_4g_tdd', 'enb_id_actual'),
    ),
}

# Nokia area selection is meaningful at site (MRBTS) level only; RNC/BSC
# controllers span multiple areas, so they are intentionally omitted.
_NOKIA_AREA_SOURCES: dict[str, tuple[tuple[str, str], ...]] = {
    'MRBTS': (
        ('cells_4g_fdd', 'enb_id_actual'),
        ('cells_4g_tdd', 'enb_id_actual'),
        ('cells_5g', 'gnb_id_actual'),
        ('cells_2g', 'site_id'),
        ('cells_3g', 'nodeb_id'),
    ),
}


def huawei_area_map(scope_level: str = 'ENODEB') -> dict[str, dict[str, str]]:
    level = normalize_huawei_scope_level(scope_level)
    return _vendor_area_map('%huawei%', _HUAWEI_AREA_SOURCES.get(level, ()))


def list_huawei_areas(scope_level: str = 'ENODEB') -> list[dict[str, str | int]]:
    """Return distinct areas with site counts matching the Huawei picker list."""
    level = normalize_huawei_scope_level(scope_level)
    if level in ('RNC', 'BSC'):
        return []
    rows = _huawei_picker_rows('', scope_level=level, limit=5000)
    area_map = huawei_area_map(level)
    index = _site_area_index()
    items = []
    for row in rows:
        site_id = str(row['site_id'])
        area_info = area_map.get(site_id) or {}
        items.append({
            'area': canonical_cm_area(
                site_id,
                fallback=str(area_info.get('area') or ''),
                index=index,
            ),
        })
    return areas_from_site_items(items)


_ALL_CELL_AREA_SOURCES: tuple[tuple[str, str], ...] = (
    ('cells_2g', 'site_id'),
    ('cells_3g', 'nodeb_id'),
    ('cells_4g_fdd', 'enb_id_actual'),
    ('cells_4g_tdd', 'enb_id_actual'),
    ('cells_5g', 'gnb_id_actual'),
)


def cluster_area_map() -> dict[str, str]:
    """
    Deterministic ``cluster -> area`` lookup built from all cell tables.

    Clusters map 1:1 to areas in the metadata, so this is the authoritative
    way to assign an area once a site's cluster is known. When a cluster ever
    appears under more than one area, the most frequent area wins.
    """
    counts: dict[str, dict[str, int]] = {}
    conn = connect_metadata()
    try:
        for table, _key in _ALL_CELL_AREA_SOURCES:
            sql = f'''
                SELECT
                    COALESCE(NULLIF(TRIM(cluster), ''), '') AS cluster,
                    COALESCE(NULLIF(TRIM(area), ''), '') AS area,
                    COUNT(*) AS n
                FROM {table}
                WHERE NULLIF(TRIM(cluster), '') IS NOT NULL
                  AND NULLIF(TRIM(area), '') IS NOT NULL
                GROUP BY cluster, area
            '''
            try:
                rows = execute_query(conn, sql, []).fetchall()
            except Exception:
                continue
            for row in rows:
                cluster = _clean_cluster(row['cluster'])
                area = str(row['area'] or '').strip()
                if not cluster or not area:
                    continue
                bucket = counts.setdefault(cluster, {})
                bucket[area] = bucket.get(area, 0) + int(row['n'] or 0)
    finally:
        conn.close()

    return {
        cluster: max(areas, key=areas.get)
        for cluster, areas in counts.items()
        if areas
    }


def nokia_area_map(scope_level: str = 'MRBTS') -> dict[str, dict[str, str]]:
    level = normalize_scope_level(scope_level)
    return _vendor_area_map('%nokia%', _NOKIA_AREA_SOURCES.get(level, ()))


def site_cluster_map(vendor: str, scope_level: str) -> dict[str, str]:
    """Return ``site_id -> cluster`` for a vendor/scope from the cell tables."""
    vendor_like = f'%{(vendor or "").strip().lower()}%'
    if vendor_like == '%%':
        vendor_like = '%'
    if (vendor or '').strip().lower() == 'nokia':
        sources = _NOKIA_AREA_SOURCES.get(normalize_scope_level(scope_level), ())
    else:
        sources = _HUAWEI_AREA_SOURCES.get(normalize_huawei_scope_level(scope_level), ())
    area_map = _vendor_area_map(vendor_like, sources)
    return {sid: info.get('cluster', '') for sid, info in area_map.items()}


def list_nokia_areas(scope_level: str = 'MRBTS') -> list[dict[str, str | int]]:
    """Return distinct areas with site counts (same population as the Nokia picker)."""
    return list_nokia_inventory_areas(scope_level)


def _huawei_controller_picker_rows(
    query: str = '',
    *,
    scope_level: str,
    limit: int = 2000,
) -> list:
    """Distinct Huawei RNC or BSC controllers from 3G/2G cell inventory."""
    level = normalize_huawei_scope_level(scope_level)
    conn = connect_metadata()
    try:
        params: list[object] = []
        term = (query or '').strip()
        limit = max(1, min(int(limit), 5000))
        if level == 'RNC':
            where = [
                "LOWER(COALESCE(vendor, '')) LIKE '%huawei%'",
                "NULLIF(TRIM(rnc), '') IS NOT NULL",
            ]
            if term:
                where.append('(rnc LIKE ? OR rnc_name LIKE ?)')
                like = f'%{term}%'
                params.extend([like, like])
            sql = f'''
                SELECT
                    CAST(rnc AS TEXT) AS site_id,
                    MAX(COALESCE(NULLIF(TRIM(rnc_name), ''), rnc)) AS site_name,
                    MAX(CAST(lat AS REAL)) AS latitude,
                    MAX(CAST("long" AS REAL)) AS longitude,
                    COUNT(DISTINCT cell_name) AS cell_count
                FROM cells_3g
                WHERE {' AND '.join(where)}
                GROUP BY rnc
                ORDER BY site_name COLLATE NOCASE
                LIMIT ?
            '''
        else:
            where = [
                "LOWER(COALESCE(vendor, '')) LIKE '%huawei%'",
                "NULLIF(TRIM(bsc), '') IS NOT NULL",
            ]
            if term:
                where.append('(bsc LIKE ? OR bsc_name LIKE ?)')
                like = f'%{term}%'
                params.extend([like, like])
            sql = f'''
                SELECT
                    CAST(bsc AS TEXT) AS site_id,
                    MAX(COALESCE(NULLIF(TRIM(bsc_name), ''), bsc)) AS site_name,
                    MAX(CAST(lat AS REAL)) AS latitude,
                    MAX(CAST("long" AS REAL)) AS longitude,
                    COUNT(DISTINCT cell_name) AS cell_count
                FROM cells_2g
                WHERE {' AND '.join(where)}
                GROUP BY bsc
                ORDER BY site_name COLLATE NOCASE
                LIMIT ?
            '''
        params.append(limit)
        return execute_query(conn, sql, params).fetchall()
    finally:
        conn.close()


def _huawei_controller_site_items(rows: list, scope_level: str) -> list[dict[str, str | int | float | None]]:
    from core.cm_extractor.huawei_discovery import get_cached_discovery, load_discovery_from_disk

    load_discovery_from_disk()
    catalog = (get_cached_discovery(max_age_sec=10**9) or {}).get('nes') or []
    items: list[dict[str, str | int | float | None]] = []
    for row in rows:
        site_id = str(row['site_id'])
        site_name = row['site_name'] or site_id
        ne_name = match_huawei_controller_ne_name(
            site_id,
            site_name,
            catalog,
            scope_level=scope_level,
        )
        label = f'{site_name} ({site_id})'
        if ne_name and ne_name != site_name:
            label = f'{site_name} ({site_id} → {ne_name})'
        items.append({
            'site_id': site_id,
            'metadata_site_id': site_id,
            'site_name': site_name,
            'ne_name': ne_name or site_name,
            'u2020_ne_name': ne_name or '',
            'u2020_resolved': bool(ne_name),
            'u2020_source': 'fm' if ne_name else None,
            'area': '',
            'cluster': '',
            'latitude': row['latitude'],
            'longitude': row['longitude'],
            'cell_count': row['cell_count'] or 0,
            'scope_level': scope_level,
            'label': label,
        })
    return items


def _huawei_picker_rows(
    query: str = '',
    *,
    scope_level: str = 'ENODEB',
    limit: int = 2000,
) -> list:
    """Active Huawei rows used by the CM picker (no U2020 lookup)."""
    level = normalize_huawei_scope_level(scope_level)
    if level in ('RNC', 'BSC'):
        return _huawei_controller_picker_rows(query, scope_level=level, limit=limit)
    conn = connect_metadata()
    try:
        params: list[object] = []
        term = (query or '').strip()
        limit = max(1, min(int(limit), 5000))
        where = [
            "LOWER(COALESCE(s.vendor, '')) LIKE '%huawei%'",
            "COALESCE(s.status, 'Active') = 'Active'",
            "NULLIF(TRIM(s.site_id), '') IS NOT NULL",
        ]
        if term:
            where.append('(s.site_id LIKE ? OR s.site_name LIKE ?)')
            like = f'%{term}%'
            params.extend([like, like])
        sql = f'''
            WITH huawei_lte_sites AS (
                SELECT CAST(enb_id_actual AS TEXT) AS site_id
                FROM cells_4g_fdd
                WHERE LOWER(COALESCE(vendor, '')) LIKE '%huawei%'
                  AND NULLIF(TRIM(CAST(enb_id_actual AS TEXT)), '') IS NOT NULL
                UNION
                SELECT CAST(enb_id_actual AS TEXT) AS site_id
                FROM cells_4g_tdd
                WHERE LOWER(COALESCE(vendor, '')) LIKE '%huawei%'
                  AND NULLIF(TRIM(CAST(enb_id_actual AS TEXT)), '') IS NOT NULL
            ),
            active_cell_counts AS (
                SELECT site_id, COUNT(*) AS cell_count
                FROM cells
                WHERE COALESCE(status, 'Active') = 'Active'
                GROUP BY site_id
            )
            SELECT
                s.site_id,
                s.site_name,
                s.latitude,
                s.longitude,
                COALESCE(cc.cell_count, 0) AS cell_count
            FROM sites s
            INNER JOIN huawei_lte_sites lte ON lte.site_id = s.site_id
            LEFT JOIN active_cell_counts cc ON cc.site_id = s.site_id
            WHERE {' AND '.join(where)}
            ORDER BY s.site_name COLLATE NOCASE
            LIMIT ?
        '''
        params.append(limit)
        return execute_query(conn, sql, params).fetchall()
    finally:
        conn.close()


def list_huawei_db_sites(
    query: str = '',
    *,
    scope_level: str = 'ENODEB',
    limit: int = 2000,
) -> list[dict[str, str | int | float | None]]:
    """
    Return Huawei NEs for CM MML extraction.

    - ENODEB: sites with Huawei LTE (FDD/TDD) cell inventory
    - RNC: Huawei 3G controllers from cells_3g.rnc
    - BSC: Huawei 2G controllers from cells_2g.bsc
    """
    level = normalize_huawei_scope_level(scope_level)
    rows = _huawei_picker_rows(query, scope_level=level, limit=limit)
    if level in ('RNC', 'BSC'):
        return _huawei_controller_site_items(rows, level)
    area_map = huawei_area_map(level)
    site_area_index = _site_area_index()
    metadata_by_id, _metadata_alts = lookup_huawei_metadata_ne_candidates(
        [str(row['site_id']) for row in rows],
        min_source_score=_HUAWEI_SCOPE_MIN_METADATA_SCORE.get(level, 0),
    )

    from core.cm_extractor.huawei_discovery import (
        get_cached_discovery,
        load_discovery_from_disk,
        resolve_u2020_ne_name,
    )

    load_discovery_from_disk()
    discovery_cache = get_cached_discovery(max_age_sec=10**9) or {}
    catalog = discovery_cache.get('nes') or []
    by_site_id = discovery_cache.get('nes_by_site_id') or {}

    items = []
    for row in rows:
        site_id = str(row['site_id'])
        site_name = row['site_name'] or site_id
        meta_candidates = metadata_by_id.get(site_id) or []
        hint = meta_candidates[0] if meta_candidates else site_name
        ne_name = hint
        area_info = area_map.get(site_id) or {}
        u2020_ne_name = ''
        u2020_resolved = None
        u2020_source = ''
        try:
            u2020_ne_name, u2020_source = resolve_u2020_ne_name(
                site_id,
                hint,
                catalog if catalog else None,
                by_site_id=by_site_id if catalog else None,
                allow_metadata_fallback=True,
                metadata_candidates=meta_candidates,
            )
            u2020_ne_name = u2020_ne_name or ''
            u2020_resolved = bool(u2020_ne_name)
        except Exception:
            u2020_ne_name = ''
            u2020_source = ''

        if u2020_ne_name:
            ne_name = u2020_ne_name
        label = f'{site_name} ({site_id})'
        if u2020_ne_name and u2020_ne_name != site_name:
            label = f'{site_name} ({site_id} → {u2020_ne_name})'
        items.append({
            'site_id': site_id,
            'metadata_site_id': site_id,
            'site_name': site_name,
            'ne_name': ne_name,
            'u2020_ne_name': u2020_ne_name or ne_name,
            'u2020_resolved': u2020_resolved,
            'u2020_source': u2020_source or None,
            'area': canonical_cm_area(
                site_id,
                fallback=str(area_info.get('area') or ''),
                index=site_area_index,
            ),
            'cluster': area_info.get('cluster', ''),
            'latitude': row['latitude'],
            'longitude': row['longitude'],
            'cell_count': row['cell_count'] or 0,
            'scope_level': level,
            'label': label,
        })
    return items
