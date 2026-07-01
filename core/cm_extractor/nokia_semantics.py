"""
Nokia CM extraction semantics: MO catalog, parameter metadata, query building, export.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from core.cm_extractor.excel_writer import (
    allocate_sheet_title,
    managed_objects_to_sheet,
    merge_sheet_parts,
    query_rows_to_ncm_sheet,
    write_nokia_multi_sheet_excel,
)
from core.cm_extractor.nokia_client import NokiaCmClient, NokiaCmError
from core.cm_extractor.site_catalog import (
    normalize_controller_mo_ids,
    resolve_bulk_export_dns,
    resolve_scope_instance_id,
    scope_dn_needles,
)

_MO_CLASS_CACHE: dict[str, Any] = {'ts': 0.0, 'items': [], 'by_scope': {}, 'version': 0}
_CACHE_TTL_SEC = 3600

# Compact MO tree (anchors + full class set per scope) bundled with the app.
# Lets us map each NetAct CM adaptation to a scope by the anchor classes it
# exposes, so BTS-side WCDMA/GSM adaptations (e.g. the one carrying
# WNBTS/WNCEL/WNCELG under the MRBTS tree) are discovered automatically instead
# of relying on a hard-coded adaptation allow-list.
_SCOPE_TREE_PATH = Path(__file__).resolve().parent / 'data' / 'nokia_mo_scope_tree.json'
_SCOPE_TREE_CACHE: dict[str, dict[str, frozenset[str]]] | None = None

# MO Path templates — scoped paths filter by PLMN instance variable (:plmn).
_MO_PATH_BY_ADAPTATION: dict[str, str] = {
    'NOKLTE': '/NetActCommon:PLMN[instance()=:plmn]/MRBTS/LNBTS//{adapt}:{abbr}',
    'NOKNR': '/NetActCommon:PLMN[instance()=:plmn]/MRBTS/NRBTS//{adapt}:{abbr}',
    'NOKRNC': '/NetActCommon:PLMN[instance()=:plmn]//{adapt}:{abbr}',
    'NOKBSC': '/NetActCommon:PLMN[instance()=:plmn]//{adapt}:{abbr}',
    'NOKIA': '/NetActCommon:PLMN[instance()=:plmn]//{adapt}:{abbr}',
    'NetActCommon': '/NetActCommon:PLMN[instance()=:plmn]/{adapt}:{abbr}',
}
_MO_PATH_ALL_PLMNS: dict[str, str] = {
    'NOKLTE': '/NetActCommon:PLMN/MRBTS/LNBTS//{adapt}:{abbr}',
    'NOKNR': '/NetActCommon:PLMN/MRBTS/NRBTS//{adapt}:{abbr}',
    'NOKRNC': '/NetActCommon:PLMN//{adapt}:{abbr}',
    'NOKBSC': '/NetActCommon:PLMN//{adapt}:{abbr}',
    'NOKIA': '/NetActCommon:PLMN//{adapt}:{abbr}',
    'NetActCommon': '/NetActCommon:PLMN/{adapt}:{abbr}',
}
_SITE_LEVEL_MO_PATH_ALL_PLMNS: dict[tuple[str, str], str] = {
    ('NOKLTE', 'LNBTS'): '/NetActCommon:PLMN/MRBTS/{adapt}:{abbr}',
    ('NOKLTE', 'MRBTS'): '/NetActCommon:PLMN/MRBTS',
    ('NOKNR', 'NRBTS'): '/NetActCommon:PLMN/MRBTS/{adapt}:{abbr}',
    ('MRBTS', 'MRBTS'): '/NetActCommon:PLMN/MRBTS',
    ('NOKIA', 'MRBTS'): '/NetActCommon:PLMN/MRBTS',
}

_RAN_ADAPTATION_PREFIXES = ('NOKLTE', 'NOKNR', 'NOKRNC', 'NOKBSC', 'NOKIA', 'NetActCommon', 'MRBTS')
# Fallback adaptation set when the full-catalog discovery call fails. The
# preferred path fetches every adaptation and classifies it by anchor class, so
# BTS-side WCDMA/GSM classes (WNCEL/WNCELG, …) are not missed.
RAN_ADAPT_IDS = ['NetActCommon', 'NOKLTE', 'NOKNR', 'NOKRNC', 'NOKBSC', 'NOKIA', 'MRBTS']

# Default MO-path template per scope for adaptations without an explicit entry
# above (used for discovered adaptations such as the WCDMA-on-BTS one). MRBTS
# scope is rooted at the MRBTS tree so instance() scoping and DN filtering work.
_DEFAULT_TREE_PATH_BY_SCOPE: dict[str, str] = {
    'MRBTS': '/NetActCommon:PLMN/MRBTS//{adapt}:{abbr}',
    'RNC': '/NetActCommon:PLMN//{adapt}:{abbr}',
    'BSC': '/NetActCommon:PLMN//{adapt}:{abbr}',
}

_MO_CLASS_CACHE_VERSION = 5

# Structured/list parameters cannot be queried with bare @paramName (needs components).
_NON_QUERYABLE_PARAM_TYPES = frozenset({'StructuredValue'})
# NetAct rejects MO Path queries above ~275 expressions — use full MO export above this.
_QUERY_PARAM_MAX = 250
SCOPE_LEVELS = ('MRBTS', 'RNC', 'BSC')
_ADAPTATIONS_BY_SCOPE: dict[str, frozenset[str]] = {
    'MRBTS': frozenset({'NOKLTE', 'NOKNR', 'MRBTS', 'NOKIA'}),
    'RNC': frozenset({'NOKRNC'}),
    'BSC': frozenset({'NOKBSC'}),
}
# NOKRNC/NOKBSC child MOs are scoped with RNC[instance()]/BSC[instance()] in the MO
# path (short CM id, e.g. 12 for PrimeNet 2012). Root controller MOs (NOKRNC:RNC) are
# read via PLMN-tree DNs (e.g. PLMN-PLMN/RNC-2012) because short ids return no data.
_CONTROLLER_DN_FILTER_ADAPTATIONS = frozenset({'NOKRNC', 'NOKBSC'})
_CONTROLLER_ROOT_ABBREV = {'NOKRNC': 'RNC', 'NOKBSC': 'BSC'}
# Some 3G MO classes are absent or heavily truncated in CM Open API persistency.
_RNC_OPEN_API_EMPTY_HINT_CLASSES = frozenset({'WBTS', 'WCEL', 'WAC'})
_RNC_OPEN_API_INCOMPLETE_HINT_CLASSES = frozenset({'FMCS', 'WBTS', 'WCEL', 'WAC'})
_WORKING_QUERY_PARAMS_CACHE: dict[str, list[str]] = {}


def _load_scope_tree() -> dict[str, dict[str, frozenset[str]]]:
    """Load the bundled anchor/class map used to classify adaptations by scope."""
    global _SCOPE_TREE_CACHE
    if _SCOPE_TREE_CACHE is None:
        anchors: dict[str, frozenset[str]] = {}
        classes: dict[str, frozenset[str]] = {}
        try:
            raw = json.loads(_SCOPE_TREE_PATH.read_text(encoding='utf-8'))
            raw_anchors = raw.get('anchors') or {}
            raw_classes = raw.get('classes') or {}
        except (OSError, json.JSONDecodeError, TypeError):
            raw_anchors, raw_classes = {}, {}
        for level in SCOPE_LEVELS:
            anchors[level] = frozenset(raw_anchors.get(level) or [])
            classes[level] = frozenset(raw_classes.get(level) or [])
        _SCOPE_TREE_CACHE = {'anchors': anchors, 'classes': classes}
    return _SCOPE_TREE_CACHE


def discover_scope_adaptations(items: list[dict[str, str]]) -> dict[str, frozenset[str]]:
    """
    Map each adaptation to a scope by the anchor classes it exposes.

    An adaptation belongs to MRBTS if it carries a BTS-tree anchor (MRBTS,
    LNBTS, NRBTS, GNBTS, WNBTS, …), to RNC/BSC for their respective anchors.
    Anchors never overlap between BTS and controller trees, so the BTS-side
    WCDMA/GSM adaptations land under MRBTS regardless of their exact id string.
    The static ``_ADAPTATIONS_BY_SCOPE`` acts as a floor so nothing regresses.
    """
    anchors = _load_scope_tree()['anchors']
    abbrs_by_adapt: dict[str, set[str]] = {}
    for item in items:
        adapt = item.get('adaptation')
        abbr = item.get('abbreviation')
        if adapt and abbr:
            abbrs_by_adapt.setdefault(adapt, set()).add(abbr)

    result: dict[str, set[str]] = {
        level: set(_ADAPTATIONS_BY_SCOPE[level]) for level in SCOPE_LEVELS
    }
    for adapt, abbrs in abbrs_by_adapt.items():
        for level in SCOPE_LEVELS:
            if abbrs & anchors[level]:
                result[level].add(adapt)
    # Controllers stay in their own scope; never let them leak into MRBTS.
    result['MRBTS'].difference_update(_CONTROLLER_DN_FILTER_ADAPTATIONS)
    return {level: frozenset(adapts) for level, adapts in result.items()}


def _allowed_adaptations_for_scope(scope_level: str) -> frozenset[str]:
    """Discovered adaptations for a scope, falling back to the static floor."""
    level = normalize_scope_level(scope_level)
    by_scope = _MO_CLASS_CACHE.get('by_scope') or {}
    return by_scope.get(level) or _ADAPTATIONS_BY_SCOPE[level]


def flatten_mo_classes(raw: dict[str, Any] | list[Any] | None) -> list[dict[str, str]]:
    """Turn meta/classes API payload into a sorted pick-list."""
    if not raw:
        return []

    data = raw
    if isinstance(raw, dict):
        data = raw.get('result') or raw.get('classes') or raw

    if not isinstance(data, dict):
        return []

    items: list[dict[str, str]] = []
    for adapt_id, versions in data.items():
        if not isinstance(versions, dict):
            continue
        for version, abbrevs in versions.items():
            if not isinstance(abbrevs, list):
                continue
            for abbr in abbrevs:
                if not abbr or not isinstance(abbr, str):
                    continue
                mo_id = f'{adapt_id}:{abbr}'
                items.append({
                    'id': mo_id,
                    'adaptation': adapt_id,
                    'abbreviation': abbr,
                    'version': version,
                    'label': f'{abbr}',
                    'group': adapt_id,
                })

    return dedupe_mo_classes(items)


def dedupe_mo_classes(items: list[dict[str, str]]) -> list[dict[str, str]]:
    """
    NetAct returns the same MO abbreviation once per adaptation version
    (e.g. dozens of LNCEL rows). Keep a single entry per class id.
    """
    best: dict[str, dict[str, str]] = {}
    for item in items:
        mo_id = item['id']
        current = best.get(mo_id)
        if not current or item['version'] > current['version']:
            best[mo_id] = item
    return sorted(best.values(), key=lambda x: (x['group'], x['abbreviation']))


def filter_ran_mo_classes(items: list[dict[str, str]]) -> list[dict[str, str]]:
    """Keep RAN-related adaptations only."""
    return [
        item for item in items
        if any(item['adaptation'].startswith(prefix) for prefix in _RAN_ADAPTATION_PREFIXES)
    ]


def normalize_scope_level(scope_level: str) -> str:
    level = (scope_level or 'MRBTS').strip().upper()
    if level not in SCOPE_LEVELS:
        raise ValueError(f'Scope must be one of: {", ".join(SCOPE_LEVELS)}')
    return level


def filter_mo_classes_by_scope(
    items: list[dict[str, str]],
    scope_level: str,
) -> list[dict[str, str]]:
    allowed = _allowed_adaptations_for_scope(scope_level)
    return [item for item in items if item.get('adaptation') in allowed]


def _fetch_and_classify_mo_classes(
    client: NokiaCmClient,
    *,
    ran_only: bool = True,
) -> tuple[list[dict[str, str]], dict[str, frozenset[str]]]:
    """
    Fetch the MO-class catalog and classify adaptations by scope.

    The full adaptation catalog is fetched so BTS-side WCDMA/GSM adaptations are
    discovered. If that call fails (large payloads can time out on some NetActs),
    fall back to the historical curated adaptation set.
    """
    try:
        items = flatten_mo_classes(client.get_mo_classes(None))
    except NokiaCmError:
        items = []
    if not items:
        items = flatten_mo_classes(client.get_mo_classes(RAN_ADAPT_IDS))

    by_scope = discover_scope_adaptations(items)
    if ran_only:
        ran_adaptations: set[str] = set()
        for adapts in by_scope.values():
            ran_adaptations |= adapts
        items = [item for item in items if item.get('adaptation') in ran_adaptations]
    return items, by_scope


def get_mo_class_catalog(
    client: NokiaCmClient,
    *,
    ran_only: bool = True,
    scope_level: str | None = None,
) -> list[dict[str, str]]:
    now = time.time()
    cache_ok = (
        _MO_CLASS_CACHE['items']
        and _MO_CLASS_CACHE.get('version') == _MO_CLASS_CACHE_VERSION
        and (now - _MO_CLASS_CACHE['ts']) < _CACHE_TTL_SEC
    )
    if not cache_ok:
        items, by_scope = _fetch_and_classify_mo_classes(client, ran_only=ran_only)
        _MO_CLASS_CACHE['ts'] = now
        _MO_CLASS_CACHE['items'] = items
        _MO_CLASS_CACHE['by_scope'] = by_scope
        _MO_CLASS_CACHE['version'] = _MO_CLASS_CACHE_VERSION

    items = list(_MO_CLASS_CACHE['items'])
    if scope_level:
        items = filter_mo_classes_by_scope(items, scope_level)
    return items


def normalize_plmn_scope(plmn: str) -> tuple[bool, str]:
    """
    Map UI PLMN input to NetAct MO Path :plmn variable.

    NetAct distinguishes DN (e.g. ``PLMN-PLMN``) from the instance id used in
  ``[instance()=:plmn]`` (e.g. ``PLMN``). Passing ``PLMN-PLMN`` returns 0 rows.
    """
    raw = (plmn or '').strip()
    if not raw or raw.lower() in {'*', 'all', 'any'}:
        return False, ''
    if raw.startswith('PLMN-'):
        return True, raw.split('-', 1)[1]
    return True, raw


def build_query_variables(plmn: str) -> dict[str, str] | None:
    scoped, instance = normalize_plmn_scope(plmn)
    if not scoped:
        return None
    return {'plmn': instance}


def adaptation_supports_path_scope(adaptation: str, scope_level: str) -> bool:
    return adaptation in _allowed_adaptations_for_scope(scope_level)


def _is_controller_root_mo(adaptation: str, abbreviation: str) -> bool:
    return _CONTROLLER_ROOT_ABBREV.get(adaptation) == abbreviation


def _fetch_controller_root_mo_sheet(
    client: NokiaCmClient,
    site_id: str,
    scope_level: str,
    *,
    conf_id: int = 1,
) -> dict[str, Any] | None:
    """Load NOKRNC:RNC / NOKBSC:BSC via PLMN-tree DN (20xx form, not short CM id)."""
    dns = resolve_bulk_export_dns(client, [site_id], scope_level=scope_level)
    if not dns:
        return None
    managed_objects = client.get_managed_objects(dns, conf_id=conf_id)
    if not managed_objects:
        return None
    sheet = managed_objects_to_sheet(managed_objects)
    sheet['mo_count'] = len(managed_objects)
    return sheet


def _filter_sheet_to_parameters(
    sheet: dict[str, Any],
    parameters: list[str],
) -> dict[str, Any]:
    """Keep hierarchy columns plus the requested parameter ids (and list columns)."""
    headers = list(sheet.get('headers') or [])
    rows = sheet.get('rows') or []
    hierarchy_col_count = int(sheet.get('hierarchy_col_count') or 0)
    if not parameters:
        return sheet

    wanted = {p.lstrip('@') for p in parameters}
    keep: list[str] = []

    if hierarchy_col_count:
        keep.extend(headers[:hierarchy_col_count])
    else:
        for col in headers:
            if col in ('RNC', 'BSC', 'FMCS', 'WBTS', 'WCEL', 'MRBTS', 'LNBTS', 'NRBTS', 'LNCEL'):
                keep.append(col)

    for col in ('$instance',):
        if col in headers and col not in keep:
            keep.append(col)

    for header in headers:
        if header in keep:
            continue
        if header in wanted:
            keep.append(header)
            continue
        if header.startswith('Item-'):
            for param in wanted:
                if header.endswith(f'-{param}'):
                    keep.append(header)
                    list_name = header.split('-', 2)[1]
                    if list_name in headers and list_name not in keep:
                        keep.append(list_name)
                    break

    if not keep:
        keep = headers

    out_rows = [
        [row[headers.index(col)] if col in headers else '' for col in keep]
        for row in rows
    ]
    new_hierarchy_count = (
        sum(1 for col in keep if col in set(headers[:hierarchy_col_count]))
        if hierarchy_col_count
        else 0
    )
    return {
        'headers': keep,
        'rows': out_rows,
        'hierarchy_col_count': new_hierarchy_count,
        'mo_count': len(out_rows),
    }


def discover_controller_mo_ids(
    client: NokiaCmClient,
    adaptation: str,
    abbreviation: str,
    site_id: str,
    scope_level: str,
    *,
    site_name: str = '',
    conf_id: int = 1,
) -> list[str]:
    """
    Find MO distNames for one RNC/BSC element.

    NetAct may expose child MOs only under ``RNC[instance()=12]`` (short CM id)
    or only via all-PLMN ``//NOKRNC:WCEL`` paths — try both and filter by DN.
    """
    level = normalize_scope_level(scope_level)
    if _is_controller_root_mo(adaptation, abbreviation):
        return resolve_bulk_export_dns(client, [site_id], scope_level=level)

    found: list[str] = []
    seen: set[str] = set()

    def _add(mo_id: str) -> None:
        mo_id = str(mo_id or '').strip()
        if not mo_id or mo_id in seen:
            return
        if not filter_mo_ids_for_site(
            [mo_id],
            site_id,
            scope_level=level,
            site_name=site_name,
        ):
            return
        seen.add(mo_id)
        found.append(mo_id)

    path_element_id = resolve_scope_instance_id(site_id, level, site_name=site_name)
    mo_paths: list[str] = []
    if path_element_id:
        mo_paths.append(
            build_mo_path(
                adaptation,
                abbreviation,
                scope_level=level,
                element_id=path_element_id,
            )
        )
    mo_paths.append(
        build_mo_path(
            adaptation,
            abbreviation,
            scope_level=level,
            element_id=None,
        )
    )

    for mo_path in mo_paths:
        bare = mo_path.split(' as ', 1)[0]
        try:
            for lite in client.query_mo_lites(bare, conf_id=conf_id):
                if isinstance(lite, dict) and lite.get('moId'):
                    _add(str(lite['moId']))
        except NokiaCmError:
            pass
        try:
            for row in client.query(mo_path, ['dn()'], conf_id=conf_id):
                if row:
                    _add(str(row[0]))
        except NokiaCmError:
            pass

    return normalize_controller_mo_ids(found, site_id, level)


def extract_controller_mo_sheet(
    client: NokiaCmClient,
    adaptation: str,
    abbreviation: str,
    site_id: str,
    scope_level: str,
    *,
    parameters: list[str] | None = None,
    site_name: str = '',
    conf_id: int = 1,
) -> dict[str, Any]:
    """
    Export one NOKRNC/NOKBSC MO class for a controller via getManagedObjects.

    CM Open API ``query @param`` on controller DNs returns empty values; this
    path always reads parameters through getManagedObjects with PLMN DNs.
    """
    level = normalize_scope_level(scope_level)

    if _is_controller_root_mo(adaptation, abbreviation):
        sheet = _fetch_controller_root_mo_sheet(client, site_id, level, conf_id=conf_id)
        if not sheet or not sheet.get('rows'):
            return {'headers': ['moId'], 'rows': [], 'mo_count': 0}
        if parameters:
            filtered = _filter_sheet_to_parameters(sheet, parameters)
            return filtered
        return sheet

    mo_ids = discover_controller_mo_ids(
        client,
        adaptation,
        abbreviation,
        site_id,
        level,
        site_name=site_name,
        conf_id=conf_id,
    )
    if not mo_ids:
        return {'headers': ['moId'], 'rows': [], 'mo_count': 0}

    managed_objects = client.get_managed_objects(mo_ids, conf_id=conf_id)
    if not managed_objects:
        return {'headers': ['moId'], 'rows': [], 'mo_count': 0}

    sheet = managed_objects_to_sheet(managed_objects)
    sheet['mo_count'] = len(managed_objects)
    if parameters:
        return _filter_sheet_to_parameters(sheet, parameters)
    return sheet


def query_controller_selected_parameters(
    client: NokiaCmClient,
    adaptation: str,
    abbreviation: str,
    parameters: list[str],
    *,
    site_id: str,
    scope_level: str,
    site_name: str = '',
    conf_id: int = 1,
) -> tuple[list[str], list[list[Any]]]:
    """Selected-parameter export for NOKRNC/NOKBSC via getManagedObjects."""
    sheet = extract_controller_mo_sheet(
        client,
        adaptation,
        abbreviation,
        site_id,
        scope_level,
        parameters=parameters,
        site_name=site_name,
        conf_id=conf_id,
    )
    return sheet.get('headers') or ['moId'], sheet.get('rows') or []


def filter_mo_ids_for_site(
    mo_ids: list[str],
    site_id: str,
    *,
    scope_level: str = 'MRBTS',
    site_name: str = '',
) -> list[str]:
    """Keep MOs whose distName belongs to the selected scope element."""
    needles = scope_dn_needles(site_id, scope_level, site_name=site_name)
    if not needles:
        return mo_ids
    return [mo_id for mo_id in mo_ids if any(needle in mo_id for needle in needles)]


def _inject_scope_element(template: str, scope_level: str, element_id: str) -> str:
    level = normalize_scope_level(scope_level)
    token = str(element_id or '').strip()
    if not token:
        return template

    if level == 'MRBTS' and '/MRBTS/' in template:
        return template.replace('/MRBTS/', f'/MRBTS[instance()={token}]/', 1)
    if level == 'MRBTS' and template.endswith('/MRBTS'):
        return f'{template}[instance()={token}]'

    segment = {
        'RNC': f'RNC[instance()={token}]',
        'BSC': f'BSC[instance()={token}]',
    }.get(level)
    if not segment:
        return template

    plmn_close = template.find(']/')
    if plmn_close != -1:
        insert_at = plmn_close + 2
        return f'{template[:insert_at]}{segment}/{template[insert_at:]}'

    marker = 'PLMN/'
    if marker in template:
        return template.replace(marker, f'{marker}{segment}/', 1)
    return template


def build_mo_path(
    adaptation: str,
    abbreviation: str,
    *,
    scope_level: str = 'MRBTS',
    element_id: str | None = None,
) -> str:
    """Build an all-PLMN MO path (no PLMN instance filter)."""
    default_template = _MO_PATH_ALL_PLMNS.get(adaptation)
    if default_template is None:
        level = normalize_scope_level(scope_level)
        default_template = _DEFAULT_TREE_PATH_BY_SCOPE.get(
            level,
            '/NetActCommon:PLMN//{adapt}:{abbr}',
        )
    template = _SITE_LEVEL_MO_PATH_ALL_PLMNS.get(
        (adaptation, abbreviation),
        default_template,
    )
    if element_id:
        template = _inject_scope_element(template, scope_level, element_id)
    path = template.format(adapt=adaptation, abbr=abbreviation)
    alias = abbreviation.lower().replace('-', '_')[:20] or 'mo'
    return f'{path} as ${alias}'


def list_plmn_instances(client: NokiaCmClient, *, conf_id: int = 1) -> list[dict[str, str]]:
    """Return PLMN objects from NetAct for the UI picker."""
    rows = client.query('/NetActCommon:PLMN', ['dn()', 'instance()'], conf_id=conf_id)
    items: list[dict[str, str]] = []
    for row in rows:
        if not row:
            continue
        dn = str(row[0]) if len(row) > 0 else ''
        instance = str(row[1]) if len(row) > 1 else ''
        if not dn and not instance:
            continue
        items.append({
            'dn': dn,
            'instance': instance,
            'label': f'{instance} ({dn})' if dn and instance else (dn or instance),
        })
    return items


def is_queryable_parameter(param: dict[str, str]) -> bool:
    """Scalar parameters only — StructuredValue needs component paths."""
    if (param.get('id') or '').strip() in ('$instance',):
        return True
    return (param.get('type') or '').strip() not in _NON_QUERYABLE_PARAM_TYPES


def filter_queryable_parameters(
    parameters: list[str],
    meta_parameters: list[dict[str, str]] | None = None,
) -> tuple[list[str], list[str]]:
    """
    Drop parameters that cannot be used in a simple CM query expression.

    Returns (queryable, skipped_ids).
    """
    if not meta_parameters:
        return list(parameters), []

    meta_by_id = {p['id']: p for p in meta_parameters if p.get('id')}
    queryable: list[str] = []
    skipped: list[str] = []
    for param_id in parameters:
        meta = meta_by_id.get(param_id)
        if meta and not is_queryable_parameter(meta):
            skipped.append(param_id)
            continue
        queryable.append(param_id)
    return queryable, skipped


def parameter_to_query_expression(param: str) -> str | None:
    """
    Map a CM meta parameter id to a valid MO Path query expression.

    NetAct metadata uses ``$instance`` for the MO instance id, but the query
    API expects ``instance()`` — ``@$instance`` is a syntax error.
    """
    name = (param or '').strip().lstrip('@')
    if not name:
        return None
    if name in ('$instance', 'instance'):
        return 'instance()'
    if name.startswith('$'):
        name = name[1:]
    if not name:
        return None
    return f'@{name}'


def build_query_expressions(parameters: list[str]) -> list[str]:
    exprs = ['dn()']
    seen = {'dn()'}
    for param in parameters:
        expr = parameter_to_query_expression(param)
        if expr and expr not in seen:
            exprs.append(expr)
            seen.add(expr)
    return exprs


def _uses_individual_param_queries(adaptation: str) -> bool:
    return adaptation in _CONTROLLER_DN_FILTER_ADAPTATIONS


def discover_working_query_parameters(
    client: NokiaCmClient,
    mo_path: str,
    parameters: list[str],
    *,
    mo_class_id: str = '',
    conf_id: int = 1,
) -> list[str]:
    """Find scalar parameters that return rows for this MO path (RNC needs per-param probe)."""
    if not parameters:
        return []

    adaptation = (mo_class_id.split(':', 1)[0] if ':' in mo_class_id else '')
    if not _uses_individual_param_queries(adaptation) and len(parameters) <= 40:
        try:
            rows = client.query(
                mo_path,
                build_query_expressions(parameters),
                conf_id=conf_id,
            )
            if rows:
                return list(parameters)
        except NokiaCmError:
            pass

    working: list[str] = []
    for param_id in parameters:
        try:
            rows = client.query(
                mo_path,
                build_query_expressions([param_id]),
                conf_id=conf_id,
            )
        except NokiaCmError:
            continue
        if rows:
            working.append(param_id)
    return working


def _column_label_for_parameter(param_id: str) -> str:
    labels = expression_column_labels(build_query_expressions([param_id]))
    return labels[-1] if len(labels) > 1 else param_id.lstrip('@')


def _filter_rows_for_site(
    rows: list[list[Any]],
    site_id: str | None,
    *,
    scope_level: str = 'MRBTS',
    site_name: str = '',
) -> list[list[Any]]:
    if not site_id or not rows:
        return rows
    return [
        row for row in rows
        if filter_mo_ids_for_site(
            [str(row[0])],
            site_id,
            scope_level=scope_level,
            site_name=site_name,
        )
    ]


def query_parameters_individually(
    client: NokiaCmClient,
    mo_path: str,
    parameters: list[str],
    *,
    conf_id: int = 1,
    site_id: str | None = None,
    scope_level: str = 'MRBTS',
    site_name: str = '',
    include_all_columns: bool = True,
) -> tuple[list[str], list[list[Any]]]:
    """
    Query one parameter per request and merge by DN.

    When include_all_columns is True, every requested parameter becomes a column
    even if NetAct returns no rows for that parameter (empty cells).
    """
    param_ids = [p for p in parameters if p]
    base_rows = _filter_rows_for_site(
        client.query(mo_path, ['dn()', 'instance()'], conf_id=conf_id),
        site_id,
        scope_level=scope_level,
        site_name=site_name,
    )
    if not base_rows:
        base_rows = _filter_rows_for_site(
            client.query(mo_path, ['dn()'], conf_id=conf_id),
            site_id,
            scope_level=scope_level,
            site_name=site_name,
        )

    rows_by_dn: dict[str, dict[str, Any]] = {}
    for row in base_rows:
        dn = str(row[0])
        entry = rows_by_dn.setdefault(dn, {'DN': dn})
        if len(row) > 1 and '$instance' not in entry:
            entry['$instance'] = row[1]

    headers = ['DN']
    if any('$instance' in entry for entry in rows_by_dn.values()):
        headers.append('$instance')

    for param_id in param_ids:
        if param_id in ('$instance', 'instance'):
            continue
        col = _column_label_for_parameter(param_id)
        if col not in headers:
            headers.append(col)

        values_by_dn: dict[str, Any] = {}
        try:
            param_rows = _filter_rows_for_site(
                client.query(
                    mo_path,
                    build_query_expressions([param_id]),
                    conf_id=conf_id,
                ),
                site_id,
                scope_level=scope_level,
                site_name=site_name,
            )
            for row in param_rows:
                dn = str(row[0])
                values_by_dn[dn] = row[1] if len(row) > 1 else ''
        except NokiaCmError:
            param_rows = []

        targets = rows_by_dn if rows_by_dn else {f'__missing_{col}': {'DN': ''}}
        if include_all_columns or values_by_dn:
            for dn, entry in targets.items():
                if dn.startswith('__missing_'):
                    continue
                entry[col] = values_by_dn.get(dn, '')

    if not rows_by_dn:
        return headers, []

    out_rows = [[entry.get(header, '') for header in headers] for entry in rows_by_dn.values()]
    return headers, out_rows


def query_rows_to_sheet(
    headers: list[str],
    rows: list[list[Any]],
) -> dict[str, Any]:
    return query_rows_to_ncm_sheet(headers, rows)


def merge_query_result_parts(
    parts: list[tuple[list[str], list[list[Any]]]],
) -> dict[str, Any]:
    """Merge chunked CM query results on DN, then apply NCM hierarchy layout."""
    if not parts:
        return {'headers': ['DN'], 'rows': [], 'mo_count': 0, 'hierarchy_col_count': 0}

    headers: list[str] = []
    seen_headers: set[str] = set()
    rows_by_dn: dict[str, dict[str, Any]] = {}

    for part_headers, part_rows in parts:
        for header in part_headers:
            if header not in seen_headers:
                headers.append(header)
                seen_headers.add(header)
        dn_index = part_headers.index('DN') if 'DN' in part_headers else 0
        for row in part_rows:
            dn = str(row[dn_index]) if dn_index < len(row) else ''
            row_map = rows_by_dn.setdefault(dn, {'DN': dn})
            for idx, header in enumerate(part_headers):
                if idx < len(row):
                    row_map[header] = row[idx]

    if 'DN' not in seen_headers:
        headers.insert(0, 'DN')
    merged_rows = [
        [row_map.get(header, '') for header in headers]
        for row_map in rows_by_dn.values()
    ]
    sheet = query_rows_to_ncm_sheet(headers, merged_rows)
    sheet['mo_count'] = len(sheet.get('rows') or [])
    return sheet


def extract_full_mo_via_query(
    client: NokiaCmClient,
    mo_path: str,
    *,
    parameters: list[str],
    mo_class_id: str = '',
    conf_id: int = 1,
    site_id: str | None = None,
    scope_level: str = 'MRBTS',
    site_name: str = '',
    chunk_size: int = 25,
) -> dict[str, Any]:
    """
    Full MO export using the query API when queryMOLites/getManagedObjects are unavailable.

    Used for NOKRNC on NetAct: only a subset of scalar parameters may be queryable.
    """
    adaptation = (mo_class_id.split(':', 1)[0] if ':' in mo_class_id else '')
    level = normalize_scope_level(scope_level)
    if (
        adaptation in _CONTROLLER_DN_FILTER_ADAPTATIONS
        and level in ('RNC', 'BSC')
        and site_id
    ):
        abbr = mo_class_id.split(':', 1)[-1] if ':' in mo_class_id else ''
        if abbr:
            sheet = extract_controller_mo_sheet(
                client,
                adaptation,
                abbr,
                site_id,
                level,
                parameters=parameters or None,
                site_name=site_name,
                conf_id=conf_id,
            )
            if sheet.get('rows'):
                return sheet

    individual_only = _uses_individual_param_queries(adaptation)

    if individual_only or not parameters:
        headers, rows = query_parameters_individually(
            client,
            mo_path,
            parameters or ['$instance'],
            conf_id=conf_id,
            site_id=site_id,
            scope_level=scope_level,
            site_name=site_name,
            include_all_columns=True,
        )
        return query_rows_to_sheet(headers, rows)

    working = parameters
    if len(parameters) > 40:
        cache_key = f'{mo_class_id}|{mo_path}'
        working = _WORKING_QUERY_PARAMS_CACHE.get(cache_key)
        if working is None:
            working = discover_working_query_parameters(
                client,
                mo_path,
                parameters,
                mo_class_id=mo_class_id,
                conf_id=conf_id,
            )
            _WORKING_QUERY_PARAMS_CACHE[cache_key] = working

    parts: list[tuple[list[str], list[list[Any]]]] = []
    for start in range(0, len(working), chunk_size):
        chunk = working[start:start + chunk_size]
        expressions = build_query_expressions(chunk)
        headers = expression_column_labels(expressions)
        rows = client.query(mo_path, expressions, conf_id=conf_id)
        if site_id and rows:
            dn_index = headers.index('DN') if 'DN' in headers else 0
            rows = [
                row for row in rows
                if filter_mo_ids_for_site(
                    [str(row[dn_index])],
                    site_id,
                    scope_level=scope_level,
                    site_name=site_name,
                )
            ]
        parts.append((headers, rows))

    sheet = merge_query_result_parts(parts)
    return sheet


def should_export_full_mo(
    *,
    export_mode: str = '',
    parameters: list[str],
    queryable: list[str],
    skipped: list[str],
    meta_parameters: list[dict[str, str]],
) -> bool:
    """Use queryMOLites + getManagedObjects when query expressions would be too large."""
    if (export_mode or '').strip().lower() == 'full':
        return True
    if skipped:
        return True
    if len(queryable) > _QUERY_PARAM_MAX:
        return True
    if meta_parameters and len(parameters) >= len(meta_parameters):
        return True
    return False


def extract_full_mo_class(
    client: NokiaCmClient,
    adaptation: str,
    abbreviation: str,
    *,
    conf_id: int = 1,
    site_id: str | None = None,
    scope_level: str = 'MRBTS',
    site_name: str = '',
    meta_parameters: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Export every MO instance and all parameters for one MO class (optionally one site)."""
    level = normalize_scope_level(scope_level)
    use_path_scope = site_id and adaptation_supports_path_scope(adaptation, level)
    path_element_id = None
    if use_path_scope and site_id:
        path_element_id = resolve_scope_instance_id(site_id, level, site_name=site_name)
    mo_path = build_mo_path(
        adaptation,
        abbreviation,
        scope_level=level,
        element_id=path_element_id,
    )

    mo_path_bare = mo_path.split(' as ', 1)[0]

    if adaptation in _CONTROLLER_DN_FILTER_ADAPTATIONS and level in ('RNC', 'BSC'):
        if site_id:
            return extract_controller_mo_sheet(
                client,
                adaptation,
                abbreviation,
                site_id,
                level,
                site_name=site_name,
                conf_id=conf_id,
            )
        mo_class_id = f'{adaptation}:{abbreviation}'
        param_ids = [p['id'] for p in (meta_parameters or []) if p.get('id')]
        queryable, _ = filter_queryable_parameters(param_ids, meta_parameters)
        return extract_full_mo_via_query(
            client,
            mo_path,
            parameters=queryable or ['$instance'],
            mo_class_id=mo_class_id,
            conf_id=conf_id,
            site_id=site_id,
            scope_level=level,
            site_name=site_name,
        )

    lites = client.query_mo_lites(mo_path_bare, conf_id=conf_id)
    mo_ids = [lite['moId'] for lite in lites if isinstance(lite, dict) and lite.get('moId')]
    if site_id and use_path_scope and not mo_ids:
        # Some NetAct builds return no queryMOLites rows for instance-scoped
        # MRBTS/LNBTS/NRBTS paths. Fall back to all-PLMN and filter by DN.
        fallback_path = build_mo_path(
            adaptation,
            abbreviation,
            scope_level=level,
            element_id=None,
        ).split(' as ', 1)[0]
        lites = client.query_mo_lites(fallback_path, conf_id=conf_id)
        mo_ids = [lite['moId'] for lite in lites if isinstance(lite, dict) and lite.get('moId')]
        mo_ids = filter_mo_ids_for_site(
            mo_ids,
            site_id,
            scope_level=level,
            site_name=site_name,
        )
    elif site_id and not use_path_scope:
        mo_ids = filter_mo_ids_for_site(
            mo_ids,
            site_id,
            scope_level=level,
            site_name=site_name,
        )
    if not mo_ids:
        return {'headers': ['moId'], 'rows': [], 'mo_count': 0}

    managed_objects = client.get_managed_objects(mo_ids, conf_id=conf_id)
    sheet = managed_objects_to_sheet(managed_objects)
    sheet['mo_count'] = len(mo_ids)
    return sheet


def query_selected_parameters(
    client: NokiaCmClient,
    mo_path: str,
    parameters: list[str],
    *,
    adaptation: str = '',
    abbreviation: str = '',
    conf_id: int = 1,
    site_id: str | None = None,
    scope_level: str = 'MRBTS',
    site_name: str = '',
) -> tuple[list[str], list[list[Any]]]:
    """Run CM query for a parameter selection."""
    level = normalize_scope_level(scope_level)
    if (
        adaptation in _CONTROLLER_DN_FILTER_ADAPTATIONS
        and level in ('RNC', 'BSC')
        and site_id
        and abbreviation
    ):
        return query_controller_selected_parameters(
            client,
            adaptation,
            abbreviation,
            parameters,
            site_id=site_id,
            scope_level=level,
            site_name=site_name,
            conf_id=conf_id,
        )

    if _uses_individual_param_queries(adaptation):
        return query_parameters_individually(
            client,
            mo_path,
            parameters,
            conf_id=conf_id,
            site_id=site_id,
            scope_level=scope_level,
            site_name=site_name,
            include_all_columns=True,
        )

    expressions = build_query_expressions(parameters)
    rows = client.query(mo_path, expressions, conf_id=conf_id)
    if not rows and len(parameters) > 1:
        return query_parameters_individually(
            client,
            mo_path,
            parameters,
            conf_id=conf_id,
            site_id=site_id,
            scope_level=scope_level,
            site_name=site_name,
            include_all_columns=True,
        )
    headers = expression_column_labels(expressions)
    return headers, rows


def expression_column_labels(expressions: list[str], param_labels: dict[str, str] | None = None) -> list[str]:
    result = []
    for expr in expressions:
        if expr == 'dn()':
            result.append('DN')
            continue
        if expr == 'instance()':
            result.append('$instance')
            continue
        result.append(expr.lstrip('@'))
    return result


def parse_meta_parameters(raw: dict[str, Any] | None) -> dict[str, list[dict[str, str]]]:
    """Return {mo_class_id: [{id, name, description}, ...]}."""
    if not raw:
        return {}

    definitions = raw.get('moClassDefinitions') or raw.get('result') or []
    if isinstance(definitions, dict):
        definitions = definitions.get('moClassDefinitions') or []

    by_class: dict[str, list[dict[str, str]]] = {}
    for mo_def in definitions:
        if not isinstance(mo_def, dict):
            continue
        mo_class = mo_def.get('moClass') or {}
        class_id = mo_class.get('id') or ''
        if not class_id:
            continue
        params = []
        for param in mo_def.get('parameters') or []:
            if not isinstance(param, dict):
                continue
            pid = (param.get('id') or '').strip()
            if not pid:
                continue
            param_info = {
                'id': pid,
                'name': (param.get('name') or pid).strip(),
                'description': (param.get('description') or '').strip(),
                'type': (param.get('type') or '').strip(),
            }
            param_info['queryable'] = is_queryable_parameter(param_info)
            params.append(param_info)
        params.sort(key=lambda p: p['id'].lower())
        by_class[class_id] = params
    return by_class


def fetch_parameters_for_classes(
    client: NokiaCmClient,
    selections: list[dict[str, str]],
) -> dict[str, list[dict[str, str]]]:
    if not selections:
        return {}

    mo_classes = []
    for sel in selections:
        mo_id = sel.get('mo_class_id') or sel.get('id') or ''
        version = sel.get('version') or ''
        if mo_id and version:
            mo_classes.append({'id': mo_id, 'version': version})

    if not mo_classes:
        return {}

    raw = client.get_meta_parameters(
        mo_classes,
        fragments=['type', 'name', 'description'],
    )
    return parse_meta_parameters(raw)


def extract_nokia_selection(
    client: NokiaCmClient,
    *,
    selections: list[dict[str, Any]],
    site_ids: list[str],
    scope_level: str = 'MRBTS',
    conf_id: int = 1,
) -> tuple[dict[str, dict[str, Any]], int, list[str], list[str]]:
    """
    Run CM queries for each MO class + parameter set.

    Returns (sheets_data, total_rows, sheet_names, warnings) where sheets_data is:
      {sheet_name: {'headers': [...], 'rows': [[...], ...]}}
    """
    if not selections:
        raise ValueError('Select at least one managed object class')
    sites = [str(site_id).strip() for site_id in (site_ids or []) if str(site_id).strip()]
    if not sites:
        raise ValueError('Select at least one site id for the chosen scope')
    level = normalize_scope_level(scope_level)

    sheets: dict[str, dict[str, Any]] = {}
    used_sheet_titles: set[str] = set()
    total_rows = 0
    warnings: list[str] = []
    skipped_selections = 0
    if level in ('RNC', 'BSC'):
        warnings.append(
            'RNC/BSC preview uses CM Open API persistency, which lists only a small subset '
            'of child MO instances on this NetAct (e.g. a few FMCS, often zero WCEL). '
            'Run Extract for the full CM Operations Import_Export dump.'
        )

    meta_requests = []
    for sel in selections:
        mo_class_id = (sel.get('mo_class_id') or sel.get('id') or '').strip()
        version = (sel.get('version') or '').strip()
        if mo_class_id and version:
            meta_requests.append({'id': mo_class_id, 'version': version})
    meta_by_class = fetch_parameters_for_classes(client, [
        {'mo_class_id': item['id'], 'version': item['version']} for item in meta_requests
    ]) if meta_requests else {}

    for sel in selections:
        mo_class_id = (sel.get('mo_class_id') or sel.get('id') or '').strip()
        if not mo_class_id or ':' not in mo_class_id:
            skipped_selections += 1
            warnings.append(f'Skipped invalid MO class id: {mo_class_id or "(empty)"}')
            continue

        adaptation, abbreviation = mo_class_id.split(':', 1)
        export_mode = (sel.get('export_mode') or '').strip()
        parameters = [p for p in (sel.get('parameters') or []) if p]
        is_full_mo = export_mode.lower() == 'full'

        if not is_full_mo and not parameters:
            raise ValueError(f'Select at least one parameter for {abbreviation}')

        meta_parameters = meta_by_class.get(mo_class_id) or []
        queryable, skipped = filter_queryable_parameters(parameters, meta_parameters or None)
        if is_full_mo:
            queryable = []

        use_full_mo = should_export_full_mo(
            export_mode=export_mode,
            parameters=parameters,
            queryable=queryable,
            skipped=skipped,
            meta_parameters=meta_parameters,
        )

        sheet_name = allocate_sheet_title(mo_class_id, used_sheet_titles)
        sheet_parts: list[dict[str, Any]] = []
        mo_count = 0

        for site_id in sites:
            if use_full_mo:
                part = extract_full_mo_class(
                    client,
                    adaptation,
                    abbreviation,
                    conf_id=conf_id,
                    site_id=site_id,
                    scope_level=level,
                    meta_parameters=meta_parameters,
                )
                mo_count += int(part.pop('mo_count', len(part.get('rows') or [])))
                sheet_parts.append(part)
            else:
                use_path_scope = adaptation_supports_path_scope(adaptation, level)
                path_element_id = None
                if use_path_scope and site_id:
                    path_element_id = resolve_scope_instance_id(site_id, level)
                mo_path = build_mo_path(
                    adaptation,
                    abbreviation,
                    scope_level=level,
                    element_id=path_element_id,
                )
                used_unscoped_fallback = False
                headers, rows = query_selected_parameters(
                    client,
                    mo_path,
                    queryable,
                    adaptation=adaptation,
                    abbreviation=abbreviation,
                    conf_id=conf_id,
                    site_id=site_id,
                    scope_level=level,
                )
                if use_path_scope and site_id and not rows:
                    fallback_mo_path = build_mo_path(
                        adaptation,
                        abbreviation,
                        scope_level=level,
                        element_id=None,
                    )
                    headers, rows = query_selected_parameters(
                        client,
                        fallback_mo_path,
                        queryable,
                        adaptation=adaptation,
                        abbreviation=abbreviation,
                        conf_id=conf_id,
                        site_id=site_id,
                        scope_level=level,
                    )
                    used_unscoped_fallback = True
                if site_id and rows and (not use_path_scope or used_unscoped_fallback):
                    dn_index = headers.index('DN') if 'DN' in headers else 0
                    filtered = filter_mo_ids_for_site(
                        [str(row[dn_index]) for row in rows],
                        site_id,
                        scope_level=level,
                    )
                    filtered_set = set(filtered)
                    rows = [row for row in rows if str(row[dn_index]) in filtered_set]
                mo_count += len(rows)
                sheet_parts.append({'headers': headers, 'rows': rows})

        sheet_data = merge_sheet_parts(sheet_parts)
        if use_full_mo:
            note = (
                f'{abbreviation}: exported full MO(s) with all parameters '
                f'({mo_count} instance(s) across {len(sites)} site(s))'
            )
            if adaptation in _CONTROLLER_DN_FILTER_ADAPTATIONS and level in ('RNC', 'BSC'):
                headers_list = sheet_data.get('headers') or []
                param_cols = [
                    header for header in headers_list
                    if header not in {'DN', '$instance', 'moId'}
                ]
                filled_cells = 0
                for header in param_cols:
                    col_idx = headers_list.index(header)
                    filled_cells += sum(
                        1 for row in (sheet_data.get('rows') or [])
                        if col_idx < len(row) and row[col_idx] not in (None, '')
                    )
                note += (
                    f' — {level} export: {len(param_cols)} parameter column(s), '
                    f'{filled_cells} cell(s) with values from NetAct. '
                    'Controller MOs use all-PLMN MO paths with DN filtering per CM Open API.'
                )
            warnings.append(note)
            if mo_count > 500:
                warnings.append(
                    f'{abbreviation}: large export ({mo_count} MOs) — NetAct may rate-limit; '
                    'retry after a minute if you see error 429.'
                )

        sheets[sheet_name] = sheet_data
        total_rows += len(sheet_data['rows'])

    if not sheets:
        raise ValueError('No data extracted — check MO class and parameter selection')

    expected_sheets = len(selections) - skipped_selections
    if expected_sheets > len(sheets):
        warnings.append(
            f'Expected {expected_sheets} sheet(s) but produced {len(sheets)}. '
            'Check for duplicate MO class abbreviations or invalid selections.'
        )

    if total_rows == 0:
        if level == 'RNC':
            rnc_hint = (
                'No 3G RNC MO instances matched the selected id(s). '
                'PrimeNet RNC ids like 2012 map to CM distNames such as /RNC-12 or /RNC-2012. '
            )
            empty_classes = [
                (sel.get('mo_class_id') or '').split(':')[-1]
                for sel in selections
                if (sel.get('mo_class_id') or '').split(':')[-1] in _RNC_OPEN_API_EMPTY_HINT_CLASSES
            ]
            incomplete_classes = [
                (sel.get('mo_class_id') or '').split(':')[-1]
                for sel in selections
                if (sel.get('mo_class_id') or '').split(':')[-1] in _RNC_OPEN_API_INCOMPLETE_HINT_CLASSES
            ]
            if empty_classes:
                rnc_hint += (
                    f'On this NetAct, CM Open API persistency returns no '
                    f'{", ".join(dict.fromkeys(empty_classes))} instances '
                    f'(common on SRAN — radio config lives under WBTS/WCEL in CM Operations, not Open API). '
                )
            elif incomplete_classes:
                rnc_hint += (
                    f'CM Open API lists only a few {", ".join(dict.fromkeys(incomplete_classes))} '
                    f'instances per RNC — not the full set visible in CM Operations Manager. '
                )
            else:
                rnc_hint += (
                    'Not all MO classes exist under every RNC in CM Open API — try NOKRNC:RNC, FMCS, or WCEL. '
                )
            rnc_hint += (
                'For a full 3G dump use Bulk export (CM Operations Import_Export) on the Nokia tab.'
            )
            warnings.append(rnc_hint)
        elif level == 'BSC':
            warnings.append(
                'No 2G BSC MO instances matched the selected id(s) for this MO class. '
                'Open API exposes GSM MOs (BTS, BCF, ADJW, …) only on BSCs that still '
                'have CM objects in NetAct — some BSC ids have an empty persistency tree. '
                'Try NOKBSC:BSC (root), BTS, or BCF. '
                'For a full dump use Bulk export (CM Operations Import_Export).'
            )
        else:
            warnings.append(
                'No MO instances found for the selected MO class, scope, and site id(s).'
            )

    return sheets, total_rows, list(sheets.keys()), warnings


def preview_nokia_selection(
    client: NokiaCmClient,
    *,
    selections: list[dict[str, Any]],
    site_ids: list[str],
    scope_level: str = 'MRBTS',
    conf_id: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    sheets, total_rows, sheet_names, warnings = extract_nokia_selection(
        client,
        selections=selections,
        site_ids=site_ids,
        scope_level=scope_level,
        conf_id=conf_id,
    )

    preview_sheets = {}
    for name, data in sheets.items():
        preview_sheets[name] = {
            'columns': data['headers'],
            'rows': data['rows'][:limit],
            'count': len(data['rows']),
        }

    return {
        'count': total_rows,
        'sheet_names': sheet_names,
        'sheets': preview_sheets,
        'warnings': warnings,
    }


def export_nokia_selection_to_excel(
    client: NokiaCmClient,
    output_path: str,
    *,
    selections: list[dict[str, Any]],
    site_ids: list[str],
    scope_level: str = 'MRBTS',
    conf_id: int = 1,
) -> tuple[int, list[str], str]:
    level = normalize_scope_level(scope_level)

    if level in ('RNC', 'BSC'):
        from core.cm_extractor.config import build_nokia_operations_client, nokia_export_ssh_settings
        from core.cm_extractor.nokia_bulk_export import (
            NokiaBulkExportError,
            export_controller_selection_to_excel,
        )

        if nokia_export_ssh_settings().get('configured'):
            try:
                ops_client = build_nokia_operations_client()
                return export_controller_selection_to_excel(
                    client,
                    ops_client,
                    output_path,
                    scope_level=level,
                    site_ids=site_ids,
                    selections=selections,
                )
            except NokiaBulkExportError as exc:
                raise NokiaCmError(str(exc)) from exc

    sheets, total_rows, sheet_names, warnings = extract_nokia_selection(
        client,
        selections=selections,
        site_ids=site_ids,
        scope_level=scope_level,
        conf_id=conf_id,
    )
    if level in ('RNC', 'BSC'):
        warnings.insert(
            0,
            'SFTP is not configured — RNC/BSC extract used CM Open API, which returns '
            'only a subset of MO instances on this NetAct. Set NOKIA_CM_SSH_* or '
            'NOKIA_PM_* (OMC ftpuser) for complete CM Operations export.',
        )
    write_nokia_multi_sheet_excel(output_path, sheets)

    param_summary = []
    for sel in selections:
        abbr = (sel.get('mo_class_id') or '').split(':')[-1]
        params = sel.get('parameters') or []
        if abbr and params:
            param_summary.append(f'{abbr} ({len(params)} params)')

    summary = (
        f'{total_rows} row(s) across {len(sheet_names)} sheet(s): '
        f'{", ".join(sheet_names)}. '
        f'MO classes: {"; ".join(param_summary)}.'
    )
    if warnings:
        summary += ' Note: ' + ' '.join(warnings)
    return total_rows, sheet_names, summary
