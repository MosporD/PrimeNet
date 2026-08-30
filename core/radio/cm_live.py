"""Live CM parameter reads across the network."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from core.cm_extractor.extraction import build_huawei_client, build_nokia_client
from core.cm_extractor.huawei_semantics import _selection_rows
from core.cm_extractor.nokia_semantics import (
    build_mo_path,
    extract_nokia_selection,
    fetch_parameters_for_classes,
    filter_mo_ids_for_site,
    filter_queryable_parameters,
    get_mo_class_catalog,
    normalize_scope_level,
    query_selected_parameters,
)
from core.cm_extractor.huawei_semantics import get_parameters_for_object
from core.cm_extractor.site_catalog import (
    list_huawei_db_sites,
    list_nokia_inventory_sites,
    resolve_huawei_ne_names,
)

MAX_UI_VALUE_SAMPLES = 12
MAX_NES_DEFAULT = 2000
CONTROLLER_ADAPTATIONS = frozenset({'NOKRNC', 'NOKBSC'})
IDENTITY_COLUMNS = {
    'dn', 'distname', 'moid', '$instance', 'instance', 'ne',
    'cell name', 'object name',
}


def _area_key(value: str) -> str:
    from core.site_area import canonicalize_area

    raw = str(value or '').strip()
    return (canonicalize_area(raw) or raw).strip().lower()


def _ne_display_name(ne: dict[str, Any]) -> str:
    return str(
        ne.get('label')
        or ne.get('site_name')
        or ne.get('u2020_ne_name')
        or ne.get('ne_name')
        or ne.get('site_id')
        or 'NE'
    )


def _normalize_value(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, (dict, list, tuple)):
        return str(value)
    return str(value).strip()


def _audit_status(score: float) -> str:
    if score <= 0:
        return 'consistent'
    if score < 0.05:
        return 'low'
    if score < 0.2:
        return 'medium'
    return 'high'


def _record_key(record: dict[str, Any], *, fallback: str) -> str:
    priority = (
        'DN', 'distName', 'moId', '$instance', 'instance',
        'Local Cell ID', 'Cell Name', 'Cell ID', 'eNodeB ID',
        'Nr Cell ID', 'BTS ID', 'TRX ID', 'Object Name',
    )
    for col in priority:
        value = record.get(col)
        if value not in (None, ''):
            return f'{col}={value}'
    for col, value in record.items():
        if value not in (None, ''):
            return f'{col}={value}'
    return fallback


def _sheet_to_records(sheet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    headers = [str(h) for h in (sheet.get('headers') or [])]
    rows = sheet.get('rows') or []
    records: dict[str, dict[str, Any]] = {}
    for idx, row in enumerate(rows):
        record = {
            header: row[pos] if pos < len(row) else ''
            for pos, header in enumerate(headers)
        }
        key = _record_key(record, fallback=f'row-{idx + 1}')
        records[key] = record
    return records


def _rows_to_records(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for idx, row in enumerate(rows):
        record = {str(k): v for k, v in row.items() if str(k).lower() != 'ne'}
        key = _record_key(record, fallback=f'row-{idx + 1}')
        records[key] = record
    return records


def _site_id_from_dn(dn: str, scope_level: str) -> str:
    text = str(dn or '')
    level = normalize_scope_level(scope_level)
    if level == 'MRBTS':
        for segment in ('MRBTS', 'LNBTS', 'NRBTS'):
            match = re.search(rf'/{segment}-(\d+)', text)
            if match:
                return match.group(1)
        tail = text.rsplit('/', 1)[-1]
        if '-' in tail:
            return tail.rsplit('-', 1)[-1]
        return tail
    if level == 'RNC':
        match = re.search(r'/RNC-(\d+)', text)
        return match.group(1) if match else ''
    if level == 'BSC':
        match = re.search(r'/BSC-(\d+)', text)
        return match.group(1) if match else ''
    return ''


def _parameter_value(record: dict[str, Any], parameter: str) -> str:
    raw_value = record.get(parameter)
    if raw_value is None:
        for header, value in record.items():
            if str(header).lower() == parameter.lower():
                raw_value = value
                break
    if raw_value is None and len(record) == 1:
        raw_value = next(iter(record.values()))
    return _normalize_value(raw_value)


def _resolve_nes(
    *,
    vendor: str,
    scope_level: str,
    area: str,
    site_ids: list[str] | None,
    max_nes: int,
) -> tuple[list[dict[str, Any]], int, str | None]:
    area_filter = (area or 'all').strip()
    if area_filter.lower() == 'all':
        area_filter = ''

    if vendor == 'nokia':
        items, _source = list_nokia_inventory_sites('', scope_level=scope_level, limit=max_nes * 2)
    else:
        items = list_huawei_db_sites('', scope_level=scope_level, limit=max_nes * 2)

    if site_ids:
        wanted = {str(s).strip() for s in site_ids if str(s).strip()}
        items = [item for item in items if str(item.get('site_id') or '').strip() in wanted]

    if area_filter:
        want = _area_key(area_filter)
        items = [
            item for item in items
            if _area_key(str(item.get('area') or '')) == want
        ]

    total_available = len(items)
    truncated = total_available > max_nes
    if truncated:
        items = items[:max_nes]

    note = None
    if truncated:
        note = f'Scope limited to {max_nes} of {total_available} NEs. Narrow by area or site selection.'
    return items, total_available, note


def _distribution_entries(
    value_counts: Counter,
    total: int,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for value, count in value_counts.most_common(limit):
        entries.append({
            'value': value,
            'count': count,
            'percent': round((count / total) * 100, 2) if total else 0,
        })
    return entries


def _build_summary(samples: list[dict[str, str]]) -> dict[str, Any]:
    if not samples:
        return {
            'object_count': 0,
            'ne_count': 0,
            'distinct_values': 0,
            'most_common_value': '',
            'most_common_count': 0,
            'inconsistent_count': 0,
            'inconsistency_pct': 0.0,
            'status': 'consistent',
            'value_distribution': [],
            'value_distribution_all': [],
        }

    value_counts = Counter(sample['value'] for sample in samples)
    most_common_value, most_common_count = value_counts.most_common(1)[0]
    total = len(samples)
    inconsistent = total - most_common_count
    score = inconsistent / total if total else 0.0

    distribution_all = _distribution_entries(value_counts, total)
    distribution_ui = _distribution_entries(
        value_counts,
        total,
        limit=MAX_UI_VALUE_SAMPLES,
    )

    return {
        'object_count': total,
        'ne_count': len({sample['ne'] for sample in samples}),
        'distinct_values': len(value_counts),
        'most_common_value': most_common_value,
        'most_common_count': most_common_count,
        'inconsistent_count': inconsistent,
        'inconsistency_pct': round(score * 100, 2),
        'status': _audit_status(score),
        'value_distribution': distribution_ui,
        'value_distribution_all': distribution_all,
    }


def _display_fields(record: dict[str, Any]) -> dict[str, str]:
    labels = (
        ('DN', 'dn'),
        ('distName', 'dn'),
        ('Cell Name', 'cell_name'),
        ('Cell ID', 'cell_id'),
        ('Local Cell ID', 'cell_id'),
        ('Nr Cell ID', 'cell_id'),
        ('eNodeB ID', 'site_id'),
        ('BTS ID', 'site_id'),
    )
    out: dict[str, str] = {}
    for col, key in labels:
        value = record.get(col)
        if value not in (None, '') and key not in out:
            out[key] = str(value)
    return out


def _ne_lookup(nes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(ne.get('site_id') or '').strip(): ne
        for ne in nes
        if str(ne.get('site_id') or '').strip()
    }


def _records_to_audit_rows(
    records: dict[str, dict[str, Any]],
    *,
    parameter: str,
    ne_by_site: dict[str, dict[str, Any]],
    scope_level: str,
    allowed_sites: set[str] | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for object_key, record in records.items():
        dn = str(record.get('DN') or record.get('distName') or '')
        site_id = _site_id_from_dn(dn, scope_level)
        if allowed_sites is not None:
            if site_id in allowed_sites:
                pass
            elif dn and ne_by_site:
                matched = False
                for candidate_id, ne in ne_by_site.items():
                    if filter_mo_ids_for_site(
                        [dn],
                        candidate_id,
                        scope_level=scope_level,
                        site_name=str(ne.get('site_name') or ''),
                    ):
                        site_id = candidate_id
                        matched = True
                        break
                if not matched:
                    continue
            else:
                continue

        ne = ne_by_site.get(site_id, {})
        value = _parameter_value(record, parameter)
        extra = _display_fields(record)
        rows.append({
            'ne': _ne_display_name(ne) if ne else (site_id or dn or object_key),
            'site_id': site_id,
            'area': str(ne.get('area') or ''),
            'object': object_key,
            'dn': extra.get('dn', dn),
            'cell_name': extra.get('cell_name', ''),
            'value': value,
            'matches_dominant': False,
        })
    return rows


def _nokia_mo_version(client, scope_level: str, mo_class: str, mo_version: str) -> str:
    if mo_version:
        return mo_version
    for item in get_mo_class_catalog(client, scope_level=scope_level):
        if str(item.get('id') or '') == mo_class:
            return str(item.get('version') or '')
    return ''


def _query_nokia_network_wide(
    client,
    *,
    scope_level: str,
    mo_class: str,
    parameter: str,
    conf_id: int,
    version: str,
    ne_by_site: dict[str, dict[str, Any]],
    allowed_sites: set[str] | None,
) -> tuple[list[dict[str, Any]], list[str], str]:
    adaptation, abbreviation = mo_class.split(':', 1)
    level = normalize_scope_level(scope_level)
    mo_path = build_mo_path(
        adaptation,
        abbreviation,
        scope_level=level,
        element_id=None,
    )

    meta_by_class = fetch_parameters_for_classes(
        client,
        [{'mo_class_id': mo_class, 'version': version}],
    )
    meta_params = meta_by_class.get(mo_class) or []
    queryable, skipped = filter_queryable_parameters([parameter], meta_params)
    warnings: list[str] = []
    if skipped:
        warnings.append(
            f'Parameter {parameter} is not directly queryable via CM Open API '
            f'({", ".join(skipped)}). Try another parameter or full MO export in CM Extractor.',
        )
    if not queryable:
        return [], warnings, 'network_wide'

    headers, raw_rows = query_selected_parameters(
        client,
        mo_path,
        queryable,
        adaptation=adaptation,
        abbreviation=abbreviation,
        conf_id=conf_id,
        site_id=None,
        scope_level=level,
    )
    records: dict[str, dict[str, Any]] = {}
    for idx, row in enumerate(raw_rows):
        record = {
            header: row[pos] if pos < len(row) else ''
            for pos, header in enumerate(headers)
        }
        key = _record_key(record, fallback=f'row-{idx + 1}')
        records[key] = record

    rows = _records_to_audit_rows(
        records,
        parameter=parameter,
        ne_by_site=ne_by_site,
        scope_level=level,
        allowed_sites=allowed_sites,
    )
    if not rows and raw_rows:
        warnings.append(
            'CM returned rows but none matched the selected area/site scope. '
            'Try All areas or verify MO class scope.',
        )
    return rows, warnings, 'network_wide'


def _query_nokia_per_scope_batch(
    client,
    *,
    scope_level: str,
    mo_class: str,
    parameter: str,
    conf_id: int,
    version: str,
    nes: list[dict[str, Any]],
    ne_by_site: dict[str, dict[str, Any]],
    allowed_sites: set[str] | None,
) -> tuple[list[dict[str, Any]], list[str], str]:
    selection = {
        'mo_class_id': mo_class,
        'version': version,
        'export_mode': 'selected',
        'parameters': [parameter],
    }
    site_ids = [str(ne.get('site_id') or '').strip() for ne in nes if str(ne.get('site_id') or '').strip()]
    warnings: list[str] = []
    if not site_ids:
        return [], ['No site ids available for the selected scope.'], 'per_scope_batch'

    sheets, _, _, sheet_warnings = extract_nokia_selection(
        client,
        selections=[selection],
        site_ids=site_ids,
        scope_level=scope_level,
        conf_id=conf_id,
    )
    warnings.extend(sheet_warnings)
    if not sheets:
        return [], warnings, 'per_scope_batch'

    sheet = next(iter(sheets.values()))
    records = _sheet_to_records(sheet)
    rows = _records_to_audit_rows(
        records,
        parameter=parameter,
        ne_by_site=ne_by_site,
        scope_level=scope_level,
        allowed_sites=allowed_sites,
    )
    return rows, warnings, 'per_scope_batch'


def _query_nokia(
    *,
    scope_level: str,
    mo_class: str,
    parameter: str,
    conf_id: int,
    nes: list[dict[str, Any]],
    mo_version: str,
    area: str,
    site_ids: list[str] | None,
) -> tuple[list[dict[str, Any]], list[str], str]:
    client = build_nokia_client()
    version = _nokia_mo_version(client, scope_level, mo_class, mo_version)
    ne_by_site = _ne_lookup(nes)

    area_filter = (area or 'all').strip().lower()
    scoped = bool(site_ids) or (area_filter not in ('', 'all'))
    allowed_sites = set(ne_by_site.keys()) if scoped else None

    if not ne_by_site and not scoped:
        inventory, _ = list_nokia_inventory_sites('', scope_level=scope_level, limit=5000)
        ne_by_site = _ne_lookup(inventory)

    adaptation = mo_class.split(':', 1)[0]
    level = normalize_scope_level(scope_level)
    use_network_wide = level == 'MRBTS' and adaptation not in CONTROLLER_ADAPTATIONS

    if use_network_wide:
        return _query_nokia_network_wide(
            client,
            scope_level=scope_level,
            mo_class=mo_class,
            parameter=parameter,
            conf_id=conf_id,
            version=version,
            ne_by_site=ne_by_site,
            allowed_sites=allowed_sites,
        )

    return _query_nokia_per_scope_batch(
        client,
        scope_level=scope_level,
        mo_class=mo_class,
        parameter=parameter,
        conf_id=conf_id,
        version=version,
        nes=nes,
        ne_by_site=ne_by_site,
        allowed_sites=allowed_sites,
    )


def _resolve_huawei_parameter(mo_class: str, parameter: str) -> tuple[str, str]:
    """Map abbreviation/param_id to the MML report column name."""
    needle = (parameter or '').strip()
    if not needle:
        raise ValueError('Select a parameter')
    mo = (mo_class or '').strip().upper()
    try:
        params = get_parameters_for_object(mo)
    except ValueError:
        return needle, needle

    for item in params:
        param_id = str(item.get('param_id') or '').strip()
        name = str(item.get('name') or item.get('id') or '').strip()
        item_id = str(item.get('id') or '').strip()
        aliases = {value.lower() for value in (param_id, name, item_id) if value}
        if needle.lower() in aliases:
            return name or needle, param_id or name or needle
    return needle, needle


def _huawei_ne_name_lookup(nes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for ne in nes:
        for key in (
            ne.get('u2020_ne_name'),
            ne.get('ne_name'),
            ne.get('site_name'),
            ne.get('label'),
        ):
            name = str(key or '').strip()
            if name:
                lookup[name.lower()] = ne
    return lookup


def _query_huawei(
    *,
    mo_class: str,
    parameter: str,
    nes: list[dict[str, Any]],
    scope_level: str = 'ENODEB',
) -> tuple[list[dict[str, Any]], list[str], str, str]:
    client = build_huawei_client()
    query_column, display_parameter = _resolve_huawei_parameter(mo_class, parameter)
    selection = {
        'mo_id': mo_class.strip().upper(),
        'export_all': False,
        'parameters': [query_column],
    }
    warnings: list[str] = []

    site_ids = [
        str(ne.get('site_id') or '').strip()
        for ne in nes
        if str(ne.get('site_id') or '').strip()
    ]
    site_names = {
        str(ne.get('site_id') or '').strip(): str(ne.get('site_name') or '')
        for ne in nes
        if str(ne.get('site_id') or '').strip()
    }
    ne_names, unresolved, _alternates, skipped = resolve_huawei_ne_names(
        site_ids,
        scope_level=scope_level,
        site_names_by_id=site_names,
    )
    for row in skipped:
        warnings.append(
            f"{row.get('NE name') or row.get('Site ID')}: {row.get('Reason') or 'skipped'}",
        )
    if unresolved:
        preview = ', '.join(unresolved[:8])
        suffix = '…' if len(unresolved) > 8 else ''
        warnings.append(
            f'Could not map site id(s) to U2020 NE name: {preview}{suffix}. '
            'Sync NEs from U2020 in CM Extractor or verify metadata site names.',
        )
    if not ne_names:
        return [], warnings, display_parameter, query_column

    ne_by_name = _huawei_ne_name_lookup(nes)
    rows: list[dict[str, Any]] = []
    try:
        raw_rows, errors = _selection_rows(client, ne_names, selection)
        for err in errors:
            warnings.append(err)
        if not raw_rows and not errors:
            warnings.append(
                f'No MML rows returned for {mo_class} / {display_parameter}. '
                f'Queried column: {query_column}.',
            )
        records = _rows_to_records(raw_rows)
        for object_key, record in records.items():
            value = _parameter_value(record, query_column)
            ne_name = str(record.get('NE') or record.get('ne') or '')
            ne_meta = ne_by_name.get(ne_name.lower(), {})
            extra = _display_fields(record)
            rows.append({
                'ne': ne_name or _ne_display_name(ne_meta),
                'site_id': str(ne_meta.get('site_id') or extra.get('site_id') or ''),
                'area': str(ne_meta.get('area') or ''),
                'object': object_key,
                'dn': extra.get('dn', ''),
                'cell_name': extra.get('cell_name', ''),
                'value': value,
                'matches_dominant': False,
            })
    except Exception as exc:
        warnings.append(str(exc))

    return rows, warnings, display_parameter, query_column


def query_live_parameter_status(
    *,
    vendor: str,
    scope_level: str,
    mo_class: str,
    parameter: str,
    conf_id: int = 1,
    area: str = 'all',
    site_ids: list[str] | None = None,
    max_nes: int = MAX_NES_DEFAULT,
    mo_version: str = '',
) -> dict[str, Any]:
    vendor_key = (vendor or 'nokia').strip().lower()
    if vendor_key not in ('nokia', 'huawei'):
        raise ValueError('Vendor must be nokia or huawei')

    scope = (scope_level or ('MRBTS' if vendor_key == 'nokia' else 'ENODEB')).strip().upper()
    mo = (mo_class or '').strip()
    param = (parameter or '').strip()
    if not mo:
        raise ValueError('Select a managed object class')
    if not param:
        raise ValueError('Select a parameter')
    if ':' not in mo and vendor_key == 'nokia':
        raise ValueError('Nokia MO class must use adaptation:abbreviation form (e.g. NOKLTE:LNCEL)')

    cap = max(1, min(int(max_nes or MAX_NES_DEFAULT), MAX_NES_DEFAULT))
    nes, total_available, scope_note = _resolve_nes(
        vendor=vendor_key,
        scope_level=scope,
        area=area,
        site_ids=site_ids,
        max_nes=cap,
    )
    if not nes:
        raise ValueError('No network elements match the selected scope')

    query_mode = 'huawei_batch'
    query_column = param
    if vendor_key == 'nokia':
        rows, warnings, query_mode = _query_nokia(
            scope_level=scope,
            mo_class=mo,
            parameter=param,
            conf_id=int(conf_id or 1),
            nes=nes,
            mo_version=mo_version,
            area=area,
            site_ids=site_ids,
        )
    else:
        rows, warnings, param, query_column = _query_huawei(
            mo_class=mo,
            parameter=param,
            nes=nes,
            scope_level=scope,
        )

    samples = [{'value': row['value'], 'ne': row['ne'], 'object': row['object']} for row in rows]
    summary = _build_summary(samples)
    dominant = summary.get('most_common_value', '')
    for row in rows:
        row['matches_dominant'] = row['value'] == dominant

    return {
        'vendor': vendor_key,
        'scope_level': scope,
        'mo_class': mo,
        'parameter': param,
        'query_column': query_column,
        'conf_id': int(conf_id or 1),
        'query_mode': query_mode,
        'ne_scope': {
            'queried': len(nes),
            'available': total_available,
            'truncated': total_available > cap,
            'area': area or 'all',
        },
        'summary': summary,
        'rows': rows,
        'warnings': warnings,
        'note': scope_note,
    }
