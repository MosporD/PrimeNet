"""Nokia WNCELG inventory — site split detection (group_count > 1)."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from core.cm_extractor.nokia_client import NokiaCmClient, NokiaCmError
from core.cm_extractor.nokia_semantics import build_mo_path, get_mo_class_catalog
from core.cm_extractor.site_catalog import (
    list_nokia_inventory_sites,
    nokia_mrbts_area_for_site,
)

NOKIA_MO_ABBREV = 'WNCELG'
NOKIA_MO_CLASS_FALLBACK = 'com.nokia.srbts.wcdma:WNCELG'

UNKNOWN_AREA = 'Unknown'
STATUS_SPLIT = 'split'
STATUS_NO_SPLIT = 'no_split'

STATUS_LABELS: dict[str, str] = {
    STATUS_SPLIT: 'Split',
    STATUS_NO_SPLIT: 'No split',
}

STATUS_ORDER: tuple[str, ...] = ('Split', 'No split')


def group_count_label(count: int) -> str:
    """Leaf Sankey node for WNCELG cardinality (mirrors RRU type aggregation)."""
    n = int(count or 0)
    if n <= 1:
        return '1 group'
    if n == 2:
        return '2 groups'
    return '3+ groups'


def status_label(status: str) -> str:
    raw = (status or '').strip().lower()
    if raw == STATUS_SPLIT:
        return STATUS_LABELS[STATUS_SPLIT]
    return STATUS_LABELS[STATUS_NO_SPLIT]


def build_sankey_payload(
    sites: list[dict[str, Any]],
    *,
    network_view: bool = False,
    show_status: bool = True,
) -> dict[str, Any]:
    """
    Aggregate site rows into Sankey links.

    Default: Area → Status → group-count bucket.
    ``network_view=True`` (All areas): Status → group-count (or Area omitted).
    """
    link_weights: Counter[tuple[str, str]] = Counter()
    node_kinds: dict[str, str] = {}

    def add_node(name: str, kind: str) -> str:
        node_kinds[name] = kind
        return name

    by_status: Counter[str] = Counter()
    by_groups: Counter[str] = Counter()
    split = 0
    no_split = 0

    for site in sites:
        status = status_label(str(site.get('status') or ''))
        groups = group_count_label(int(site.get('group_count') or 0))
        groups_node = add_node(groups, 'groups')
        by_status[status] += 1
        by_groups[groups] += 1
        if status == STATUS_LABELS[STATUS_SPLIT]:
            split += 1
        else:
            no_split += 1

        if network_view:
            if show_status:
                status_node = add_node(status, 'status')
                link_weights[(status_node, groups_node)] += 1
            else:
                total = add_node('Total', 'total')
                link_weights[(total, groups_node)] += 1
        else:
            area = add_node(str(site.get('area') or UNKNOWN_AREA), 'area')
            if show_status:
                status_node = add_node(status, 'status')
                link_weights[(area, status_node)] += 1
                link_weights[(status_node, groups_node)] += 1
            else:
                link_weights[(area, groups_node)] += 1

    areas = sorted(n for n, k in node_kinds.items() if k == 'area')
    statuses = [s for s in STATUS_ORDER if s in node_kinds]
    for name in node_kinds:
        if node_kinds[name] == 'status' and name not in statuses:
            statuses.append(name)
    group_order = ('1 group', '2 groups', '3+ groups')
    groups_nodes = [g for g in group_order if g in node_kinds]
    for name in node_kinds:
        if node_kinds[name] == 'groups' and name not in groups_nodes:
            groups_nodes.append(name)
    totals = [n for n, k in node_kinds.items() if k == 'total']

    ordered_names = totals + ([] if network_view else areas) + (statuses if show_status else []) + groups_nodes
    # De-dupe while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for name in ordered_names:
        if name in seen:
            continue
        seen.add(name)
        ordered.append(name)

    nodes = [{'id': name, 'name': name, 'kind': node_kinds[name]} for name in ordered]
    index = {name: i for i, name in enumerate(ordered)}

    links: list[dict[str, Any]] = []
    for (src, tgt), weight in sorted(link_weights.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1])):
        if src not in index or tgt not in index or weight <= 0:
            continue
        links.append({
            'source': index[src],
            'target': index[tgt],
            'value': weight,
            'source_id': src,
            'target_id': tgt,
        })

    return {
        'nodes': nodes,
        'links': links,
        'network_view': network_view,
        'summary': {
            'total_sites': len(sites),
            'split': split,
            'no_split': no_split,
            'by_status': {k: by_status[k] for k in STATUS_ORDER if k in by_status},
            'by_groups': {k: by_groups[k] for k in group_order if k in by_groups},
            'areas': 0 if network_view else len(areas),
            'group_buckets': len(groups_nodes),
        },
    }


def _score_mo_adaptation(adaptation: str) -> int:
    adapt = (adaptation or '').strip().lower()
    score = 0
    if 'wcdma' in adapt or 'wnbts' in adapt:
        score += 20
    if 'nokia' in adapt or adapt.startswith('com.'):
        score += 1
    if 'eqmr' in adapt or 'eqm' in adapt:
        score -= 10
    return score


def resolve_nokia_wncelg_mo_class(client: NokiaCmClient | None = None) -> str:
    """WNCELG class id from NetAct catalog, with srbts.wcdma fallback."""
    if client is not None:
        try:
            catalog = get_mo_class_catalog(client, ran_only=True, scope_level='MRBTS')
        except Exception:
            catalog = []
        matches = [
            item for item in catalog
            if (item.get('abbreviation') or '').strip().upper() == NOKIA_MO_ABBREV
        ]
        if matches:
            matches.sort(
                key=lambda item: (
                    _score_mo_adaptation(str(item.get('adaptation') or '')),
                    str(item.get('version') or ''),
                ),
                reverse=True,
            )
            return matches[0]['id']
    return NOKIA_MO_CLASS_FALLBACK


def site_id_from_dn(dn: str) -> str:
    text = str(dn or '')
    match = re.search(r'/MRBTS-([^/]+)', text, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ''


def instance_from_dn(dn: str) -> str:
    text = str(dn or '').strip()
    if not text:
        return ''
    tail = text.rsplit('/', 1)[-1]
    if '-' in tail:
        return tail.rsplit('-', 1)[-1].strip()
    return tail


def _area_key(value: str) -> str:
    from core.site_area import canonicalize_area

    raw = str(value or '').strip()
    return (canonicalize_area(raw) or raw).strip().lower()


def _build_site_lookup() -> dict[str, dict[str, Any]]:
    items, _source = list_nokia_inventory_sites('', scope_level='MRBTS', limit=5000)
    lookup: dict[str, dict[str, Any]] = {}
    for item in items:
        for key in ('site_id', 'metadata_site_id', 'netact_instance_id'):
            token = str(item.get(key) or '').strip()
            if token and token not in lookup:
                lookup[token] = item
    return lookup


def enrich_wncelg_row(
    record: dict[str, Any],
    *,
    site_lookup: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Attach site/area fields from DN + inventory lookup."""
    dn = str(record.get('DN') or record.get('dn') or record.get('distName') or '').strip()
    site_id = site_id_from_dn(dn)
    site_lookup = site_lookup if site_lookup is not None else {}
    ne = site_lookup.get(site_id) or {}
    area = str(ne.get('area') or '').strip()
    site_name = str(ne.get('site_name') or '').strip()
    metadata_site_id = str(ne.get('metadata_site_id') or '').strip()
    if not area and site_id:
        _meta, area, _cluster = nokia_mrbts_area_for_site(site_id)
        if _meta and not metadata_site_id:
            metadata_site_id = _meta
    instance = str(record.get('$instance') or record.get('instance') or '').strip()
    if not instance:
        instance = instance_from_dn(dn)

    return {
        'DN': dn,
        '$instance': instance,
        'site_id': site_id,
        'metadata_site_id': metadata_site_id,
        'site_name': site_name or site_id,
        'area': area or UNKNOWN_AREA,
    }


def aggregate_site_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Collapse WNCELG rows to one record per site.

    Split rule (2A): group_count > 1 → split, else no_split.
    """
    by_site: dict[str, dict[str, Any]] = {}
    for row in rows:
        site_id = str(row.get('site_id') or '').strip()
        if not site_id:
            continue
        bucket = by_site.get(site_id)
        if bucket is None:
            bucket = {
                'site_id': site_id,
                'metadata_site_id': str(row.get('metadata_site_id') or ''),
                'site_name': str(row.get('site_name') or site_id),
                'area': str(row.get('area') or UNKNOWN_AREA),
                'instances': [],
                'dns': [],
            }
            by_site[site_id] = bucket
        instance = str(row.get('$instance') or row.get('instance') or '').strip()
        dn = str(row.get('DN') or row.get('dn') or '').strip()
        if instance and instance not in bucket['instances']:
            bucket['instances'].append(instance)
        if dn and dn not in bucket['dns']:
            bucket['dns'].append(dn)

    sites: list[dict[str, Any]] = []
    for site_id, bucket in by_site.items():
        group_count = len(bucket['dns']) or len(bucket['instances'])
        status = STATUS_SPLIT if group_count > 1 else STATUS_NO_SPLIT
        sites.append({
            'site_id': site_id,
            'metadata_site_id': bucket['metadata_site_id'],
            'site_name': bucket['site_name'],
            'area': bucket['area'],
            'group_count': group_count,
            'status': status,
            'instances': list(bucket['instances']),
            'dns': list(bucket['dns']),
            'instances_csv': ','.join(bucket['instances']),
            'dns_csv': ' | '.join(bucket['dns']),
        })

    sites.sort(key=lambda item: (
        0 if item['status'] == STATUS_SPLIT else 1,
        str(item.get('area') or '').lower(),
        str(item.get('site_name') or '').lower(),
        str(item.get('site_id') or ''),
    ))
    return sites


def build_summary(sites: list[dict[str, Any]]) -> dict[str, Any]:
    split = sum(1 for s in sites if s.get('status') == STATUS_SPLIT)
    no_split = sum(1 for s in sites if s.get('status') == STATUS_NO_SPLIT)
    areas = {str(s.get('area') or '') for s in sites if str(s.get('area') or '').strip()}
    return {
        'total_sites': len(sites),
        'split': split,
        'no_split': no_split,
        'areas': len(areas),
        'total_groups': sum(int(s.get('group_count') or 0) for s in sites),
    }


def filter_sites_by_area(
    sites: list[dict[str, Any]],
    area: str,
) -> list[dict[str, Any]]:
    want = (area or '').strip()
    if not want or want.lower() in ('all', '*'):
        return list(sites)
    key = _area_key(want)
    return [s for s in sites if _area_key(str(s.get('area') or '')) == key]


def filter_sites_by_status(
    sites: list[dict[str, Any]],
    status: str,
) -> list[dict[str, Any]]:
    want = (status or '').strip().lower()
    if not want or want in ('all', '*'):
        return list(sites)
    if want in ('split', STATUS_SPLIT):
        return [s for s in sites if s.get('status') == STATUS_SPLIT]
    if want in ('no_split', 'nosplit', 'no-split', STATUS_NO_SPLIT):
        return [s for s in sites if s.get('status') == STATUS_NO_SPLIT]
    return list(sites)


def list_areas() -> list[dict[str, str | int]]:
    """Areas present in the local WNCELG site snapshot (never touches NetAct)."""
    from modules.configuration_dashboard import wncelg_store

    return wncelg_store.list_snapshot_areas()


def snapshot_sites_payload(
    *,
    area: str = '',
    status: str = '',
) -> dict[str, Any]:
    """Load site summary from snapshot DB (optional filters)."""
    from modules.configuration_dashboard import wncelg_store

    meta = wncelg_store.get_build_meta()
    sites = wncelg_store.load_sites()
    filtered = filter_sites_by_status(filter_sites_by_area(sites, area), status)
    return {
        'sites': filtered,
        'summary': build_summary(filtered),
        'network_summary': build_summary(sites),
        'meta': meta,
        'mo_class': str((meta or {}).get('mo_class') or ''),
        'warnings': list((meta or {}).get('warnings') or []),
    }


def _mo_ids_from_lites(lites: list[Any]) -> list[str]:
    return [
        str(lite['moId'])
        for lite in lites
        if isinstance(lite, dict) and lite.get('moId')
    ]


def _mo_ids_from_dn_rows(rows: list[list[Any]]) -> list[str]:
    return [str(row[0]) for row in rows if row and str(row[0]).strip()]


def _param_lookup(parameters: dict[str, Any], name: str) -> Any:
    if name in parameters:
        return parameters[name]
    lowered = name.lower()
    for key, value in parameters.items():
        if str(key).lower() == lowered:
            return value
    return None


def record_from_managed_object(mo: dict[str, Any]) -> dict[str, Any]:
    dn = str(mo.get('moId') or mo.get('distName') or '').strip()
    parameters = mo.get('parameters') if isinstance(mo.get('parameters'), dict) else {}
    record: dict[str, Any] = {'DN': dn}
    instance = _param_lookup(parameters, '$instance')
    if instance is None:
        instance = instance_from_dn(dn)
    if instance is not None:
        record['$instance'] = instance
    return record


def list_wncelg_mo_ids(
    client: NokiaCmClient,
    adaptation: str,
    abbreviation: str,
    *,
    conf_id: int = 1,
) -> list[str]:
    """Network-wide WNCELG distinguished names."""
    mo_path = build_mo_path(
        adaptation,
        abbreviation,
        scope_level='MRBTS',
        element_id=None,
    )
    bare = mo_path.split(' as ', 1)[0]
    try:
        mo_ids = _mo_ids_from_lites(client.query_mo_lites(bare, conf_id=conf_id))
        if mo_ids:
            return mo_ids
    except NokiaCmError:
        pass

    rows = client.query(mo_path, ['dn()'], conf_id=conf_id)
    return _mo_ids_from_dn_rows(rows)


def fetch_nokia_wncelg_inventory(
    client: NokiaCmClient,
    *,
    conf_id: int = 1,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], str, dict[str, Any]]:
    """
    Live network-wide WNCELG read, enriched and aggregated by site.

    Returns (group_rows, site_rows, warnings, mo_class, summary).
    """
    mo_class = resolve_nokia_wncelg_mo_class(client)
    if ':' not in mo_class:
        raise ValueError(f'Invalid WNCELG MO class id: {mo_class}')
    adaptation, abbreviation = mo_class.split(':', 1)
    warnings: list[str] = []

    mo_ids = list_wncelg_mo_ids(client, adaptation, abbreviation, conf_id=conf_id)
    if not mo_ids:
        warnings.append('No WNCELG instances returned from NetAct.')
        empty_summary = build_summary([])
        return [], [], warnings, mo_class, empty_summary

    managed_objects = client.get_managed_objects(mo_ids, conf_id=conf_id)
    if not managed_objects:
        warnings.append(
            f'Listed {len(mo_ids)} WNCELG DN(s) but getManagedObjects returned none.'
        )
        empty_summary = build_summary([])
        return [], [], warnings, mo_class, empty_summary

    records = [record_from_managed_object(mo) for mo in managed_objects if mo]
    site_lookup = _build_site_lookup()
    group_rows = [enrich_wncelg_row(rec, site_lookup=site_lookup) for rec in records]
    # Drop rows without a parseable MRBTS site id.
    group_rows = [r for r in group_rows if str(r.get('site_id') or '').strip()]
    if len(group_rows) < len(records):
        skipped = len(records) - len(group_rows)
        warnings.append(f'Skipped {skipped} WNCELG row(s) without MRBTS site id in DN.')

    site_rows = aggregate_site_groups(group_rows)
    summary = build_summary(site_rows)
    return group_rows, site_rows, warnings, mo_class, summary
