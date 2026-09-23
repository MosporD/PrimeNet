"""Nokia RMOD_R inventory — Area → Technology → RRU type Sankey aggregation."""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from core.cm_extractor.nokia_client import NokiaCmClient, NokiaCmError
from core.cm_extractor.nokia_semantics import (
    build_mo_path,
    get_mo_class_catalog,
)
from core.cm_extractor.site_catalog import (
    list_nokia_inventory_sites,
    nokia_mrbts_area_for_site,
)

NOKIA_MO_ABBREV = 'RMOD_R'
NOKIA_MO_CLASS_FALLBACK = 'com.nokia.srbts.eqmr:RMOD_R'

# Tech from non-empty active-cell lists on RMOD_R (user-confirmed).
TECH_LIST_PARAMS: tuple[tuple[str, str], ...] = (
    ('activeGsmCellsList', '2G'),
    ('activeWcdmaCellsList', '3G'),
    ('activeLteCellsList', '4G'),
    ('activeNrCellsList', '5G'),
)

# Coarse RAT order; band labels (4G-L18, 3G-U2100, …) sort after their RAT prefix.
TECH_ORDER: tuple[str, ...] = ('2G', '3G', '4G', '5G', 'Unused')
UNUSED_TECH = 'Unused'
UNKNOWN_PRODUCT = 'Unknown'
UNKNOWN_AREA = 'Unknown'

NOKIA_RMOD_PARAMS: tuple[str, ...] = (
    '$instance',
    'productName',
    'activeGsmCellsList',
    'activeWcdmaCellsList',
    'activeLteCellsList',
    'activeNrCellsList',
    'operationalState',
    'configDN',
)

# Bare @active*CellsList fails NetAct query ("scalar value required") — those are
# StructuredValue / list params and must come from getManagedObjects.
NOKIA_RMOD_LIST_PARAMS: tuple[str, ...] = (
    'activeGsmCellsList',
    'activeWcdmaCellsList',
    'activeLteCellsList',
    'activeNrCellsList',
)

_EMPTY_LIST_TOKENS = frozenset({
    '',
    '[]',
    '{}',
    'null',
    'none',
    'n/a',
    'na',
    '-',
    'list',  # NCM flatten marker with no Item-* children
})


def _score_mo_adaptation(adaptation: str, *, prefer_runtime: bool) -> int:
    adapt = (adaptation or '').strip().lower()
    score = 0
    if prefer_runtime and ('eqmr' in adapt or adapt.endswith('.eqmr')):
        score += 20
    if not prefer_runtime and ('eqm' in adapt and 'eqmr' not in adapt):
        score += 20
    if 'nokia' in adapt or adapt.startswith('com.'):
        score += 1
    if adapt.startswith('com.nokia.srbts.hw'):
        score -= 50
    return score


def resolve_nokia_rmod_mo_class(client: NokiaCmClient | None = None) -> str:
    """Runtime RMOD_R class id from catalog, with eqmr fallback."""
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
                    _score_mo_adaptation(
                        str(item.get('adaptation') or ''),
                        prefer_runtime=True,
                    ),
                    str(item.get('version') or ''),
                ),
                reverse=True,
            )
            return matches[0]['id']
    return NOKIA_MO_CLASS_FALLBACK


def _normalize_list_text(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, (list, tuple, set)):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return ','.join(parts)
    if isinstance(value, dict):
        # StructuredValue-style payloads often nest under common keys.
        for key in ('value', 'values', 'list', 'items', 'cellList', 'cells'):
            if key in value:
                return _normalize_list_text(value[key])
        if not value:
            return ''
        try:
            return json.dumps(value, sort_keys=True, default=str)
        except TypeError:
            return str(value).strip()
    text = str(value).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        text = text[1:-1].strip()
    return text


def is_cells_list_empty(value: Any) -> bool:
    """True when an active*CellsList carries no cells."""
    if value is None:
        return True
    if isinstance(value, (list, tuple, set)):
        return not any(str(item).strip() for item in value)
    if isinstance(value, dict):
        if not value:
            return True
        for key in ('value', 'values', 'list', 'items', 'cellList', 'cells'):
            if key in value:
                return is_cells_list_empty(value[key])
        # Non-empty structured blob without a known list key → treat as present.
        return False

    text = _normalize_list_text(value)
    if not text:
        return True
    lowered = text.lower()
    if lowered in _EMPTY_LIST_TOKENS:
        return True
    # Bracketed empty / whitespace-only collections.
    if re.fullmatch(r'\[\s*\]', text) or re.fullmatch(r'\{\s*\}', text):
        return True
    # Comma / semicolon / pipe separators with no tokens.
    tokens = [t for t in re.split(r'[,;|]', text) if t.strip()]
    if not tokens:
        return True
    return False


def techs_for_rmod(
    row: dict[str, Any],
    *,
    band_index: Any = None,
    with_bands: bool = False,
) -> list[str]:
    """
    Technologies carried by one physical RMOD (multi-RAT → multiple entries).

    When ``with_bands`` is True (or a ``band_index`` is supplied), 3G/4G fan out
    to band labels via local metadata (``4G-L18``, ``3G-U2100``, …).
    """
    if with_bands or band_index is not None:
        from modules.rru_inventory.band_map import band_techs_for_rmod

        return band_techs_for_rmod(row, band_index=band_index)

    techs: list[str] = []
    for param, tech in TECH_LIST_PARAMS:
        raw = row.get(param)
        if raw is None:
            # Case-insensitive header fallback from NetAct column labels.
            for key, value in row.items():
                if str(key).lower() == param.lower():
                    raw = value
                    break
        if not is_cells_list_empty(raw):
            techs.append(tech)
    return techs or [UNUSED_TECH]


def product_name_for_row(row: dict[str, Any]) -> str:
    raw = row.get('productName')
    if raw is None:
        for key, value in row.items():
            if str(key).lower() == 'productname':
                raw = value
                break
    name = str(raw or '').strip()
    return name or UNKNOWN_PRODUCT


def site_id_from_dn(dn: str) -> str:
    text = str(dn or '')
    match = re.search(r'/MRBTS-([^/]+)', text, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ''


def _area_key(value: str) -> str:
    from core.site_area import canonicalize_area

    raw = str(value or '').strip()
    return (canonicalize_area(raw) or raw).strip().lower()


def list_areas() -> list[dict[str, str | int]]:
    """Areas present in the local RMOD snapshot (never touches NetAct)."""
    from modules.rru_inventory import store as rru_store

    return rru_store.list_snapshot_areas()


def _build_site_lookup() -> dict[str, dict[str, Any]]:
    """Map NetAct / metadata site ids → inventory item (area, names)."""
    items, _source = list_nokia_inventory_sites('', scope_level='MRBTS', limit=5000)
    lookup: dict[str, dict[str, Any]] = {}
    for item in items:
        for key in (
            'site_id',
            'metadata_site_id',
            'netact_instance_id',
        ):
            token = str(item.get(key) or '').strip()
            if token and token not in lookup:
                lookup[token] = item
    return lookup


def enrich_rmod_row(
    record: dict[str, Any],
    *,
    site_lookup: dict[str, dict[str, Any]] | None = None,
    band_index: Any = None,
) -> dict[str, Any]:
    """Attach site/area/tech/product fields used by Sankey + table."""
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
    area = area or UNKNOWN_AREA

    lists: dict[str, str] = {}
    for param, _tech in TECH_LIST_PARAMS:
        lists[param] = _normalize_list_text(record.get(param))

    # Prefer band-aware techs when an index is available (ingest path).
    enriched_for_tech = {**record, **lists, 'site_id': site_id, 'metadata_site_id': metadata_site_id}
    techs = techs_for_rmod(
        enriched_for_tech,
        band_index=band_index,
        with_bands=band_index is not None,
    )
    product = product_name_for_row(record)
    rat_roots = {_tech_root(t) for t in techs if t != UNUSED_TECH}

    return {
        'DN': dn,
        '$instance': str(record.get('$instance') or record.get('instance') or '').strip(),
        'site_id': site_id,
        'metadata_site_id': metadata_site_id,
        'site_name': site_name or site_id,
        'area': area,
        'productName': product,
        'operationalState': str(record.get('operationalState') or '').strip(),
        'configDN': str(record.get('configDN') or record.get('configDn') or '').strip(),
        'techs': techs,
        'unused': techs == [UNUSED_TECH],
        'multi_rat': len(rat_roots) > 1,
        **lists,
    }


def _tech_root(label: str) -> str:
    text = str(label or '').strip()
    if text.startswith('4G'):
        return '4G'
    if text.startswith('3G'):
        return '3G'
    if text.startswith('2G'):
        return '2G'
    if text.startswith('5G'):
        return '5G'
    return text


def _ordered_tech_nodes(names: set[str]) -> list[str]:
    """Stable tech node order: coarse RAT family, then band label alpha."""
    def sort_key(name: str) -> tuple[int, str]:
        root = _tech_root(name)
        try:
            family = TECH_ORDER.index(root if root in TECH_ORDER else name)
        except ValueError:
            family = len(TECH_ORDER)
        return (family, name.lower())

    return sorted(names, key=sort_key)


def filter_rows_by_area(
    rows: list[dict[str, Any]],
    area: str,
) -> list[dict[str, Any]]:
    want = (area or '').strip()
    if not want or want.lower() in ('all', '*'):
        return list(rows)
    key = _area_key(want)
    return [row for row in rows if _area_key(str(row.get('area') or '')) == key]


def build_sankey_payload(
    rows: list[dict[str, Any]],
    *,
    network_view: bool = False,
) -> dict[str, Any]:
    """
    Aggregate physical RMOD rows into Sankey links.

    Default: Area → Tech → productName.
    ``network_view=True`` (All areas): Tech → productName only.
    Multi-RAT / multi-band RRUs contribute one count to each active tech label.
    """
    link_weights: Counter[tuple[str, str]] = Counter()
    node_kinds: dict[str, str] = {}

    def add_node(name: str, kind: str) -> str:
        node_kinds[name] = kind
        return name

    physical = len(rows)
    unused = sum(1 for row in rows if row.get('unused'))
    multi_rat = sum(1 for row in rows if row.get('multi_rat'))
    by_tech: Counter[str] = Counter()

    for row in rows:
        product = add_node(str(row.get('productName') or UNKNOWN_PRODUCT), 'rru')
        techs = list(row.get('techs') or [UNUSED_TECH])
        area = ''
        if not network_view:
            area = add_node(str(row.get('area') or UNKNOWN_AREA), 'area')
        for tech in techs:
            tech_node = add_node(tech, 'tech')
            if not network_view:
                link_weights[(area, tech_node)] += 1
            link_weights[(tech_node, product)] += 1
            by_tech[tech] += 1

    areas = sorted(n for n, k in node_kinds.items() if k == 'area')
    techs = _ordered_tech_nodes({n for n, k in node_kinds.items() if k == 'tech'})
    rru_totals: Counter[str] = Counter()
    for (src, tgt), weight in link_weights.items():
        if node_kinds.get(tgt) == 'rru':
            rru_totals[tgt] += weight
    rrus = [name for name, _ in sorted(rru_totals.items(), key=lambda kv: (-kv[1], kv[0].lower()))]
    for name, kind in node_kinds.items():
        if kind == 'rru' and name not in rrus:
            rrus.append(name)

    ordered_names = ([] if network_view else areas) + techs + rrus
    nodes = [{'id': name, 'name': name, 'kind': node_kinds[name]} for name in ordered_names]
    index = {name: i for i, name in enumerate(ordered_names)}

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
            'physical_rrus': physical,
            'unused': unused,
            'multi_rat': multi_rat,
            'by_tech': {k: by_tech[k] for k in _ordered_tech_nodes(set(by_tech))},
            'areas': 0 if network_view else len(areas),
            'rru_types': len(rrus),
        },
    }


def apply_band_techs(
    rows: list[dict[str, Any]],
    *,
    band_index: Any = None,
) -> list[dict[str, Any]]:
    """Recompute techs from stored cell lists + local metadata (snapshot read path)."""
    from modules.rru_inventory.band_map import load_band_index

    if band_index is not None:
        index = band_index
    else:
        try:
            index = load_band_index()
        except Exception:
            # Metadata DB missing — keep coarse techs already on the row.
            return list(rows)

    out: list[dict[str, Any]] = []
    for row in rows:
        techs = techs_for_rmod(row, band_index=index, with_bands=True)
        rat_roots = {_tech_root(t) for t in techs if t != UNUSED_TECH}
        updated = dict(row)
        updated['techs'] = techs
        updated['unused'] = techs == [UNUSED_TECH]
        updated['multi_rat'] = len(rat_roots) > 1
        out.append(updated)
    return out


def snapshot_sankey_payload(*, area: str = '') -> dict[str, Any]:
    """Build Sankey payload from the persisted network-wide snapshot (DB only)."""
    from modules.rru_inventory import store as rru_store

    meta = rru_store.get_build_meta()
    want = (area or '').strip()
    network_view = (not want) or want.lower() in ('all', '*')
    rows = apply_band_techs(rru_store.load_rows(area=area))
    sankey = build_sankey_payload(rows, network_view=network_view)
    return {
        'rows': rows,
        'sankey': sankey,
        'meta': meta,
        'mo_class': str((meta or {}).get('mo_class') or ''),
        'warnings': list((meta or {}).get('warnings') or []),
        'network_view': network_view,
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


def managed_list_to_cells_value(value: Any) -> Any:
    """
    Normalize getManagedObjects list/StructuredValue payloads for emptiness checks.

    NetAct returns list params as ``[]``, ``[{...}, ...]``, or
    ``{'items': [...]}`` — never as a scalar query expression.
    """
    if value is None:
        return ''
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        items = value.get('items')
        if isinstance(items, list):
            return items
        # Common single-field wrappers / cell-ref objects.
        for key in ('value', 'values', 'list', 'cellList', 'cells', 'dn', 'distName'):
            if key in value:
                return managed_list_to_cells_value(value[key])
        if not value:
            return ''
        return value
    return value


def record_from_managed_object(mo: dict[str, Any]) -> dict[str, Any]:
    """Map one getManagedObjects entry to a flat RMOD record."""
    dn = str(mo.get('moId') or mo.get('distName') or '').strip()
    parameters = mo.get('parameters') if isinstance(mo.get('parameters'), dict) else {}
    record: dict[str, Any] = {'DN': dn}

    instance = _param_lookup(parameters, '$instance')
    if instance is None:
        # Last path segment instance id (RMOD_R-3 → 3).
        tail = dn.rsplit('/', 1)[-1]
        if '-' in tail:
            instance = tail.rsplit('-', 1)[-1]
    if instance is not None:
        record['$instance'] = instance

    for param in NOKIA_RMOD_PARAMS:
        if param in ('$instance',):
            continue
        raw = _param_lookup(parameters, param)
        if raw is None:
            continue
        if param in NOKIA_RMOD_LIST_PARAMS:
            record[param] = managed_list_to_cells_value(raw)
        else:
            record[param] = raw
    return record


def list_rmod_mo_ids(
    client: NokiaCmClient,
    adaptation: str,
    abbreviation: str,
    *,
    conf_id: int = 1,
) -> list[str]:
    """Network-wide RMOD_R distinguished names (scalar dn() / queryMOLites only)."""
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


def fetch_nokia_rmod_inventory(
    client: NokiaCmClient,
    *,
    area: str = '',
    conf_id: int = 1,
) -> tuple[list[dict[str, Any]], list[str], str, dict[str, Any]]:
    """
    Live network-wide RMOD_R read, enriched and optionally filtered by area.

    Uses ``getManagedObjects`` because ``active*CellsList`` are non-scalar and
    cannot be read with ``@param`` query expressions.

    Returns (rows, warnings, mo_class, sankey_payload).
    """
    mo_class = resolve_nokia_rmod_mo_class(client)
    if ':' not in mo_class:
        raise ValueError(f'Invalid RMOD_R MO class id: {mo_class}')
    adaptation, abbreviation = mo_class.split(':', 1)
    warnings: list[str] = []

    mo_ids = list_rmod_mo_ids(
        client,
        adaptation,
        abbreviation,
        conf_id=conf_id,
    )
    if not mo_ids:
        warnings.append('No RMOD_R instances returned from NetAct.')
        empty = build_sankey_payload([])
        return [], warnings, mo_class, empty

    managed_objects = client.get_managed_objects(mo_ids, conf_id=conf_id)
    if not managed_objects:
        warnings.append(
            f'Listed {len(mo_ids)} RMOD_R DN(s) but getManagedObjects returned none.'
        )
        empty = build_sankey_payload([])
        return [], warnings, mo_class, empty

    records = [record_from_managed_object(mo) for mo in managed_objects if mo]
    site_lookup = _build_site_lookup()
    try:
        from modules.rru_inventory.band_map import load_band_index

        band_index = load_band_index()
    except Exception as exc:
        band_index = None
        warnings.append(f'Band metadata unavailable during ingest: {exc}')

    enriched = [
        enrich_rmod_row(rec, site_lookup=site_lookup, band_index=band_index)
        for rec in records
    ]
    filtered = filter_rows_by_area(enriched, area)
    if enriched and not filtered and (area or '').strip() and (area or '').strip().lower() not in ('all', '*'):
        warnings.append(
            f'No RMOD_R rows matched area "{area.strip()}". '
            'Check canonical area names from the areas API.'
        )

    network_view = (not (area or '').strip()) or (area or '').strip().lower() in ('all', '*')
    sankey = build_sankey_payload(filtered, network_view=network_view)
    return filtered, warnings, mo_class, sankey
