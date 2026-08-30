"""
Huawei U2020 CM extraction semantics — MML object catalog, command build, export orchestration.

Huawei RAN CM is MML-based (no Nokia-style MO meta API). Users pick NEs, object types
(LST commands), and output columns; PrimeNet runs MML and filters parsed report columns.
"""

from __future__ import annotations

import re
from typing import Any

from core.cm_extractor.excel_writer import allocate_sheet_title, write_huawei_sheets_excel
from core.cm_extractor.huawei_client import HuaweiCmClient, HuaweiCmError
from core.cm_extractor.mml_parser import normalize_mml_command, repair_mml_rows
from core.cm_extractor.site_catalog import (
    huawei_site_ids_with_lte,
    huawei_site_ids_with_nr,
    resolve_huawei_ne_names,
)

# MML object types validated on BTS3900 (typical Zain Jo eNodeB).
# ``LST ENODEB`` / ``LST GNB`` etc. are not executable on BTS3900 — use ENODEBFUNCTION.
HUAWEI_MO_CATALOG: list[dict[str, Any]] = [
    {
        'id': 'CELL',
        'label': 'LTE Cell',
        'technology': '4G',
        'command': 'LST CELL',
        'group': 'LTE',
        'recommended': True,
        'products': ['BTS3900', 'BTS5900'],
        'parameters': [
            {'id': 'Local Cell ID', 'name': 'Local Cell ID'},
            {'id': 'Cell Name', 'name': 'Cell Name'},
            {'id': 'Cell ID', 'name': 'Cell ID'},
            {'id': 'Physical Cell ID', 'name': 'Physical Cell ID'},
            {'id': 'Root Sequence Index', 'name': 'Root Sequence Index'},
            {'id': 'DL Bandwidth', 'name': 'DL Bandwidth'},
            {'id': 'UL Bandwidth', 'name': 'UL Bandwidth'},
            {'id': 'DL EARFCN', 'name': 'DL EARFCN'},
            {'id': 'UL EARFCN', 'name': 'UL EARFCN'},
            {'id': 'Cell Active State', 'name': 'Cell Active State'},
            {'id': 'Cell Admin State', 'name': 'Cell Admin State'},
            {'id': 'Cell Tx Power', 'name': 'Cell Tx Power'},
            {'id': 'Maximum Transmission Power', 'name': 'Maximum Transmission Power'},
            {'id': 'Cell Radius', 'name': 'Cell Radius'},
            {'id': 'Tracking Area ID', 'name': 'Tracking Area ID'},
        ],
    },
    {
        'id': 'NRCELL',
        'label': 'NR Cell',
        'technology': '5G',
        'command': 'LST NRCELL',
        'group': 'NR',
        'recommended': False,
        'products': ['BTS5900', 'BTS3900 5G'],
        'parameters': [
            {'id': 'Nr Cell ID', 'name': 'Nr Cell ID'},
            {'id': 'Cell Name', 'name': 'Cell Name'},
            {'id': 'Physical Cell ID', 'name': 'Physical Cell ID'},
            {'id': 'DL NARFCN', 'name': 'DL NARFCN'},
            {'id': 'UL NARFCN', 'name': 'UL NARFCN'},
            {'id': 'DL Bandwidth', 'name': 'DL Bandwidth'},
            {'id': 'UL Bandwidth', 'name': 'UL Bandwidth'},
            {'id': 'Cell Active State', 'name': 'Cell Active State'},
            {'id': 'Cell Admin State', 'name': 'Cell Admin State'},
            {'id': 'Tracking Area ID', 'name': 'Tracking Area ID'},
        ],
    },
    {
        'id': 'ENODEBFUNCTION',
        'label': 'eNodeB Function',
        'technology': '4G',
        'command': 'LST ENODEBFUNCTION',
        'group': 'LTE',
        'recommended': True,
        'products': ['BTS3900', 'BTS5900'],
        'parameters': [
            {'id': 'eNodeB Function Name', 'name': 'eNodeB Function Name'},
            {'id': 'eNodeB ID', 'name': 'eNodeB ID'},
            {'id': 'Application Ref', 'name': 'Application Ref'},
            {'id': 'Product Version', 'name': 'Product Version'},
        ],
    },
    {
        'id': 'CNOPERATOR',
        'label': 'CN Operator',
        'technology': '4G',
        'command': 'LST CNOPERATOR',
        'group': 'LTE',
        'recommended': False,
        'products': ['BTS3900', 'BTS5900'],
        'parameters': [
            {'id': 'Operator ID', 'name': 'Operator ID'},
            {'id': 'Operator Name', 'name': 'Operator Name'},
            {'id': 'MCC', 'name': 'MCC'},
            {'id': 'MNC', 'name': 'MNC'},
        ],
    },
    {
        'id': 'UCELL',
        'label': 'UMTS Cell',
        'technology': '3G',
        'command': 'LST UCELL',
        'group': '3G',
        'recommended': True,
        'products': ['BSC6900 UMTS', 'BSC6910 UMTS'],
        'parameters': [
            {'id': 'Cell Name', 'name': 'Cell Name'},
            {'id': 'Cell ID', 'name': 'Cell ID'},
            {'id': 'NodeB Name', 'name': 'NodeB Name'},
            {'id': 'Local Cell ID', 'name': 'Local Cell ID'},
            {'id': 'LAC', 'name': 'LAC'},
            {'id': 'SAC', 'name': 'SAC'},
            {'id': 'PSC', 'name': 'PSC'},
            {'id': 'UARFCN Downlink', 'name': 'UARFCN Downlink'},
        ],
    },
    {
        'id': 'NODEBFUNCTION',
        'label': 'NodeB Function',
        'technology': '3G',
        'command': 'LST NODEBFUNCTION',
        'group': '3G',
        'recommended': True,
        'products': ['BSC6900 UMTS', 'BSC6910 UMTS'],
        'parameters': [
            {'id': 'NodeB Name', 'name': 'NodeB Name'},
            {'id': 'NodeB ID', 'name': 'NodeB ID'},
        ],
    },
    {
        'id': 'GCELL',
        'label': 'GSM Cell',
        'technology': '2G',
        'command': 'LST GCELL',
        'group': '2G',
        'recommended': True,
        'products': ['BSC6900 GSM', 'BSC6910 GSM'],
        'parameters': [
            {'id': 'Cell Name', 'name': 'Cell Name'},
            {'id': 'Cell ID', 'name': 'Cell ID'},
            {'id': 'BTS Name', 'name': 'BTS Name'},
            {'id': 'LAC', 'name': 'LAC'},
            {'id': 'CI', 'name': 'CI'},
            {'id': 'BCCH', 'name': 'BCCH'},
        ],
    },
    {
        'id': 'BTSFUNCTION',
        'label': 'BTS Function',
        'technology': '2G',
        'command': 'LST BTSFUNCTION',
        'group': '2G',
        'recommended': True,
        'products': ['BSC6900 GSM', 'BSC6910 GSM'],
        'parameters': [
            {'id': 'BTS Name', 'name': 'BTS Name'},
            {'id': 'BTS ID', 'name': 'BTS ID'},
        ],
    },
]

_MO_ID_ALIASES = {
    # Legacy UI / saved selections
    'ENODEB': 'ENODEBFUNCTION',
}

_MO_BY_ID = {item['id']: item for item in HUAWEI_MO_CATALOG}

PREVIEW_ROW_LIMIT = 25
MML_SINGLE_NE_LIMIT = 100

HUAWEI_CM_TECHNOLOGIES = frozenset({'4G', 'Common'})
HUAWEI_SCOPE_TECHNOLOGIES = {
    'ENODEB': frozenset({'4G', 'Common', 'Multi'}),
    'RNC': frozenset({'3G', 'UMTS', 'WCDMA', 'Multi'}),
    'BSC': frozenset({'2G', 'GSM', 'Multi'}),
}
_HUAWEI_SCOPE_RECOMMENDED = {
    'ENODEB': frozenset({'CELL', 'ENODEBFUNCTION'}),
    'RNC': frozenset({'UCELL', 'NODEBFUNCTION'}),
    'BSC': frozenset({'GCELL', 'BTSFUNCTION'}),
}


def _discovered_mo_catalog() -> list[dict[str, Any]] | None:
    try:
        from core.cm_extractor.huawei_discovery import get_cached_discovery, load_discovery_from_disk

        load_discovery_from_disk()
        cache = get_cached_discovery(max_age_sec=10**9)
        catalog = (cache or {}).get('mo_catalog') or []
        return catalog if catalog else None
    except Exception:
        return None


def _param_dict_catalog() -> list[dict[str, Any]] | None:
    """Read-only MO/parameter baseline parsed from the bundled MOM reference."""
    try:
        from core.cm_extractor.huawei_param_dict import get_catalog_list

        items = get_catalog_list()
        return items or None
    except Exception:
        return None


def mo_matches_huawei_scope(item: dict[str, Any], scope_level: str = 'ENODEB') -> bool:
    """Return whether an MO catalog entry belongs on the Huawei extraction scope."""
    try:
        from core.cm_extractor.site_catalog import normalize_huawei_scope_level

        level = normalize_huawei_scope_level(scope_level)
    except Exception:
        level = 'ENODEB'
    allowed = HUAWEI_SCOPE_TECHNOLOGIES.get(level, HUAWEI_SCOPE_TECHNOLOGIES['ENODEB'])
    tech = str(item.get('technology') or '').strip()
    if tech in allowed and tech != 'Multi':
        return True
    if tech != 'Multi':
        return False
    products = ' '.join(str(p) for p in (item.get('products') or [])).upper()
    if not products:
        return level == 'ENODEB'
    if level == 'RNC':
        return any(token in products for token in ('UMTS', 'WCDMA'))
    if level == 'BSC':
        return 'GSM' in products
    return any(token in products for token in ('LTE', 'BTS3900', 'BTS5900', 'ENODEB'))


def get_mo_object_catalog(scope_level: str = 'ENODEB') -> list[dict[str, Any]]:
    discovered = _discovered_mo_catalog()
    baseline = _param_dict_catalog()

    if baseline:
        source, source_name = baseline, 'dictionary'
    elif discovered:
        source, source_name = discovered, 'discovered'
    else:
        source, source_name = HUAWEI_MO_CATALOG, 'builtin'

    discovered_ids = {str(item.get('id', '')).upper() for item in (discovered or [])}

    try:
        from core.cm_extractor.site_catalog import normalize_huawei_scope_level

        level = normalize_huawei_scope_level(scope_level)
    except Exception:
        level = 'ENODEB'
    recommended = _HUAWEI_SCOPE_RECOMMENDED.get(level, _HUAWEI_SCOPE_RECOMMENDED['ENODEB'])

    items: list[dict[str, Any]] = []
    for item in source:
        columns = item.get('columns') or []
        static_params = item.get('parameters') or []
        param_count = len(columns) if columns else len(static_params)
        mo_id = item['id']
        entry = {
            'id': mo_id,
            'label': item['label'],
            'technology': item['technology'],
            'command': normalize_mml_command(str(item.get('command') or f"LST {mo_id}")),
            'group': item.get('group') or item['technology'],
            'recommended': str(mo_id).upper() in recommended or bool(item.get('recommended')),
            'products': list(item.get('products') or []),
            'parameter_count': param_count,
            'source': source_name,
            'discovered': str(mo_id).upper() in discovered_ids,
            'permission_denied': bool(item.get('permission_denied')),
        }
        items.append(entry)
    filtered = [item for item in items if mo_matches_huawei_scope(item, level)]
    have = {str(item['id']).upper() for item in filtered}
    for builtin in HUAWEI_MO_CATALOG:
        mo_id = str(builtin['id']).upper()
        if mo_id in have or mo_id not in recommended:
            continue
        if not mo_matches_huawei_scope(builtin, level):
            continue
        filtered.append({
            'id': builtin['id'],
            'label': builtin['label'],
            'technology': builtin['technology'],
            'command': normalize_mml_command(str(builtin.get('command') or f'LST {mo_id}')),
            'group': builtin.get('group') or builtin['technology'],
            'recommended': True,
            'products': list(builtin.get('products') or []),
            'parameter_count': len(builtin.get('parameters') or []),
            'source': 'builtin',
            'discovered': mo_id in discovered_ids,
            'permission_denied': False,
        })
    return filtered


def get_parameters_for_object(mo_id: str) -> list[dict[str, str]]:
    token = _MO_ID_ALIASES.get((mo_id or '').strip().upper(), (mo_id or '').strip().upper())

    # 1) Parameter-dictionary baseline — authoritative, comprehensive, read-only.
    try:
        from core.cm_extractor.huawei_param_dict import get_mo_entry

        entry = get_mo_entry(token)
        if entry and entry.get('parameters'):
            return [
                {
                    'id': p['name'],
                    'name': p['name'],
                    'description': p.get('description', ''),
                    'param_id': p.get('param_id', ''),
                }
                for p in entry['parameters']
            ]
    except Exception:
        pass

    # 2) Live-probed columns from a real NE (for MOs not in the dictionary).
    try:
        from core.cm_extractor.huawei_discovery import get_cached_discovery, load_discovery_from_disk

        load_discovery_from_disk()
        cache = get_cached_discovery(max_age_sec=10**9) or {}
        columns = (cache.get('mo_columns') or {}).get(token) or []
        if columns:
            return [{'id': col, 'name': col} for col in columns]
        for item in cache.get('mo_catalog') or []:
            if str(item.get('id', '')).upper() == token and item.get('columns'):
                return [{'id': col, 'name': col} for col in item['columns']]
    except Exception:
        pass

    # 3) Built-in fallback.
    item = _MO_BY_ID.get(token)
    if not item:
        raise ValueError(
            f'Unknown Huawei MO object: {mo_id}. Rebuild the parameter dictionary '
            'or run Sync NEs from U2020 to probe commands.'
        )
    return list(item.get('parameters') or [])


def build_mml_command(mo_id: str) -> str:
    token = _MO_ID_ALIASES.get((mo_id or '').strip().upper(), (mo_id or '').strip().upper())

    # 1) Parameter-dictionary baseline command (LST preferred, else DSP).
    try:
        from core.cm_extractor.huawei_param_dict import get_mo_entry

        entry = get_mo_entry(token)
        if entry and entry.get('command'):
            return normalize_mml_command(str(entry['command']))
    except Exception:
        pass

    # 2) Live discovery command.
    try:
        from core.cm_extractor.huawei_discovery import get_cached_discovery, load_discovery_from_disk

        load_discovery_from_disk()
        cache = get_cached_discovery(max_age_sec=10**9) or {}
        for item in cache.get('mo_catalog') or []:
            if str(item.get('id', '')).upper() == token and item.get('command'):
                return normalize_mml_command(str(item['command']))
    except Exception:
        pass

    item = _MO_BY_ID.get(token)
    if not item:
        raise ValueError(f'Unknown Huawei MO object: {mo_id}')
    cmd = str(item['command']).strip().rstrip(':;')
    if not cmd:
        raise ValueError(f'Empty MML command for {mo_id}')
    return normalize_mml_command(cmd)


def _normalize_key(key: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', (key or '').lower())


def _column_lookup(row: dict[str, Any]) -> dict[str, str]:
    return {_normalize_key(k): k for k in row}


def filter_row_columns(
    row: dict[str, Any],
    *,
    parameter_ids: list[str] | None,
    export_all: bool,
    always_include: tuple[str, ...] = ('NE',),
) -> dict[str, Any]:
    if export_all or not parameter_ids:
        return dict(row)

    lookup = _column_lookup(row)
    wanted_norm = {_normalize_key(p) for p in parameter_ids}
    out: dict[str, Any] = {}
    for norm_key, orig_key in lookup.items():
        if norm_key in wanted_norm or orig_key in parameter_ids:
            out[orig_key] = row.get(orig_key, '')
    for key in always_include:
        if key in row and key not in out:
            out[key] = row[key]
    return out


def _mo_technology(mo_id: str) -> str:
    normalized = _MO_ID_ALIASES.get(mo_id, mo_id)
    meta = _MO_BY_ID.get(normalized) or {}
    return str(meta.get('technology') or '').strip().upper()


def _partition_ne_names_for_mo(
    ne_names: list[str],
    mo_id: str,
) -> tuple[list[str], list[dict[str, str]]]:
    """Drop NEs that lack the cell inventory required for the selected MO type."""
    from core.cm_extractor.huawei_discovery import parse_site_id_from_ne_name

    tech = _mo_technology(mo_id)
    if tech not in ('4G', '5G'):
        return list(ne_names), []

    site_ids = [
        sid for sid in dict.fromkeys(parse_site_id_from_ne_name(name) for name in ne_names)
        if sid
    ]
    if tech == '4G':
        eligible_sites = huawei_site_ids_with_lte(site_ids)
        reason = 'No Huawei 4G in inventory'
    else:
        eligible_sites = huawei_site_ids_with_nr(site_ids)
        reason = 'No Huawei 5G in inventory'

    eligible: list[str] = []
    skipped: list[dict[str, str]] = []
    for name in ne_names:
        sid = parse_site_id_from_ne_name(name) or ''
        if sid and sid in eligible_sites:
            eligible.append(name)
        else:
            skipped.append({
                'NE name': name,
                'Site ID': sid,
                'Reason': reason,
            })
    return eligible, skipped


def _run_mml_for_nes(
    client: HuaweiCmClient,
    command: str,
    ne_names: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    rows = client.run_mml_chunked(
        command,
        ne_names,
        chunk_size=MML_SINGLE_NE_LIMIT,
    )
    return rows, client.consume_mml_errors()


def _selection_rows(
    client: HuaweiCmClient,
    ne_names: list[str],
    selection: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    mo_id = str(selection.get('mo_id') or selection.get('id') or '').strip().upper()
    if not mo_id:
        raise ValueError('Each selection must include mo_id')

    export_all = bool(selection.get('export_all'))
    parameter_ids = selection.get('parameters') or []
    if isinstance(parameter_ids, str):
        parameter_ids = [p.strip() for p in parameter_ids.split(',') if p.strip()]

    command = build_mml_command(mo_id)
    eligible, skipped = _partition_ne_names_for_mo(ne_names, mo_id)
    for row in skipped:
        client._record_skipped_mml_nes([row['NE name']], reason=row['Reason'])
    if not eligible:
        return [], []
    raw_rows, errors = _run_mml_for_nes(client, command, eligible)
    raw_rows = repair_mml_rows(raw_rows)
    if export_all:
        return raw_rows, errors
    filtered = [
        filter_row_columns(row, parameter_ids=parameter_ids, export_all=False)
        for row in raw_rows
    ]
    return filtered, errors


def _raise_if_no_mml_rows(
    *,
    rows: list[dict[str, Any]],
    errors: list[str],
    context: str = '',
) -> None:
    if rows or not errors:
        return
    detail = '; '.join(errors[:5])
    if len(errors) > 5:
        detail += f' …and {len(errors) - 5} more'
    prefix = f'{context}: ' if context else ''
    raise HuaweiCmError(f'{prefix}{detail}')


def export_huawei_selection_to_excel(
    client: HuaweiCmClient,
    output_path: str,
    *,
    ne_names: list[str],
    selections: list[dict[str, Any]],
    pre_skipped_nes: list[dict[str, str]] | None = None,
) -> tuple[int, list[str], str, list[str]]:
    if not ne_names and not pre_skipped_nes:
        raise ValueError('At least one network element is required')
    if not selections:
        raise ValueError('Select at least one MO object type')

    client.clear_skipped_mml_nes()
    for row in pre_skipped_nes or []:
        client._record_skipped_mml_nes([row['NE name']], reason=row['Reason'])
    sheets: dict[str, list[dict[str, Any]]] = {}
    used_titles: set[str] = set()
    sheet_names: list[str] = []
    total_rows = 0
    warnings: list[str] = []

    for selection in selections:
        mo_id = str(selection.get('mo_id') or selection.get('id') or '').strip().upper()
        try:
            rows, errors = _selection_rows(client, ne_names, selection)
        except HuaweiCmError as exc:
            warnings.append(f'{mo_id}: {exc}')
            rows = []
            errors = []

        for err in errors:
            warnings.append(f'{mo_id}: {err}')

        sheet_name = allocate_sheet_title(mo_id, used_titles)
        sheets[sheet_name] = rows
        sheet_names.append(sheet_name)
        total_rows += len(rows)

    skipped_nes = client.consume_skipped_mml_nes()
    if skipped_nes:
        sheets['Skipped_NEs'] = skipped_nes
        sheet_names.append('Skipped_NEs')
        preview = ', '.join(row['NE name'] for row in skipped_nes[:8])
        suffix = '…' if len(skipped_nes) > 8 else ''
        warnings.append(
            f'Skipped {len(skipped_nes)} NE(s) — see Skipped_NEs sheet '
            f'({preview}{suffix}).',
        )

    if total_rows == 0 and warnings and not skipped_nes:
        _raise_if_no_mml_rows(rows=[], errors=warnings)

    write_huawei_sheets_excel(output_path, sheets)
    summary = (
        f'Huawei MML export: {len(ne_names)} NE(s), {len(selections)} object type(s), '
        f'{total_rows} row(s) across {len(sheet_names)} sheet(s).'
    )
    if warnings:
        summary += f' {len(warnings)} NE/MO warning(s) — see response warnings.'
    return total_rows, sheet_names, summary, warnings


def preview_huawei_selection(
    client: HuaweiCmClient,
    *,
    ne_names: list[str],
    selections: list[dict[str, Any]],
    preview_ne_limit: int = 3,
) -> dict[str, Any]:
    preview_nes = ne_names[: max(1, min(preview_ne_limit, len(ne_names)))]
    sheets: dict[str, Any] = {}
    sheet_names: list[str] = []
    total = 0
    warnings: list[str] = []

    if len(ne_names) > preview_ne_limit:
        warnings.append(
            f'Preview uses first {preview_ne_limit} of {len(ne_names)} selected NE(s).',
        )

    for selection in selections:
        mo_id = str(selection.get('mo_id') or selection.get('id') or '').strip().upper()
        try:
            rows, errors = _selection_rows(client, preview_nes, selection)
        except HuaweiCmError as exc:
            warnings.append(f'{mo_id}: {exc}')
            rows = []
            errors = []

        for err in errors:
            warnings.append(f'{mo_id}: {err}')

        columns: list[str] = []
        for row in rows:
            for key in row:
                if key not in columns:
                    columns.append(key)

        preview_rows = [[row.get(c, '') for c in columns] for row in rows[:PREVIEW_ROW_LIMIT]]
        sheet_names.append(mo_id)
        sheets[mo_id] = {
            'columns': columns,
            'rows': preview_rows,
            'count': len(rows),
        }
        total += len(rows)

    return {
        'count': total,
        'sheet_names': sheet_names,
        'sheets': sheets,
        'warnings': warnings,
        'preview_ne_count': len(preview_nes),
    }


def resolve_ne_names_for_site_ids(site_ids: list[str], *, scope_level: str = 'ENODEB') -> list[str]:
    resolved, unresolved, _alternates, _skipped = resolve_huawei_ne_names(site_ids, scope_level=scope_level)
    if unresolved:
        preview = ', '.join(unresolved[:8])
        suffix = '…' if len(unresolved) > 8 else ''
        raise ValueError(
            f'Could not map site id(s) to U2020 NE name: {preview}{suffix}. '
            'Run Sync NEs from U2020 in the Huawei tab (FM alarm discovery).',
        )
    return resolved
