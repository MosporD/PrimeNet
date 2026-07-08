"""Full-network CM pulls for the discrepancy audit.

Nokia MO classes are pulled network-wide in one pass per class
(``extract_full_mo_class`` with no site scope) so the daily job does not loop
over ~1700 sites per MO. Huawei MOs are pulled with one MML batch across all
resolved eNodeB NE names.
"""

from __future__ import annotations

import re
from typing import Any

from core.cm_discrepancy.records import rows_to_records, sheet_to_records
from core.cm_extractor.huawei_semantics import _selection_rows
from core.cm_extractor.nokia_semantics import (
    extract_full_mo_class,
    fetch_parameters_for_classes,
    get_mo_class_catalog,
)
from core.cm_extractor.site_catalog import (
    list_huawei_db_sites,
    list_nokia_inventory_sites,
    resolve_huawei_ne_names,
)

_DN_NE_RE = re.compile(r'(MRBTS|LNBTS|NRBTS|RNC|BSC|BCF|WBTS)-([\w]+)')


def ne_name_from_dn(dn: str) -> str:
    """Best-effort NE label from a NetAct distName (e.g. ``MRBTS-12345``)."""
    match = _DN_NE_RE.search(str(dn or ''))
    return f'{match.group(1)}-{match.group(2)}' if match else ''


def _record_ne_name(record: dict[str, Any]) -> str:
    for col in ('DN', 'distName', 'moId'):
        value = record.get(col)
        if value:
            ne = ne_name_from_dn(str(value))
            if ne:
                return ne
    return ''


# ---------------------------------------------------------------------------
# Target resolution (no manual NE picker for scheduled runs)
# ---------------------------------------------------------------------------

def resolve_nokia_site_ids(scope_level: str) -> list[str]:
    items, _source = list_nokia_inventory_sites('', scope_level=scope_level, limit=5000)
    return [str(item.get('site_id') or '').strip() for item in items if item.get('site_id')]


def resolve_huawei_targets() -> tuple[list[str], list[str]]:
    """Return ``(ne_names, warnings)`` for every Huawei eNodeB in inventory."""
    sites = list_huawei_db_sites('', scope_level='ENODEB', limit=5000)
    site_ids = [str(site.get('site_id') or '').strip() for site in sites if site.get('site_id')]
    resolved, unresolved, _alternates, skipped = resolve_huawei_ne_names(
        site_ids, scope_level='ENODEB'
    )
    warnings: list[str] = []
    if unresolved:
        warnings.append(
            f'{len(unresolved)} Huawei site id(s) could not be resolved to U2020 NE names '
            f'(e.g. {", ".join(unresolved[:5])})'
        )
    if skipped:
        warnings.append(f'{len(skipped)} site(s) skipped (no Huawei 4G inventory)')
    return resolved, warnings


# ---------------------------------------------------------------------------
# Per-MO pulls
# ---------------------------------------------------------------------------

def nokia_mo_meta(
    client,
    mo_class_ids: list[str],
    *,
    scope_level: str,
) -> dict[str, list[dict[str, str]]]:
    """MO-class parameter metadata (needed for controller full exports)."""
    try:
        catalog = {
            str(item.get('id') or ''): item
            for item in get_mo_class_catalog(client, scope_level=scope_level)
        }
    except Exception:
        catalog = {}
    requests = []
    for mo_id in mo_class_ids:
        version = str((catalog.get(mo_id) or {}).get('version') or '').strip()
        if version:
            requests.append({'mo_class_id': mo_id, 'version': version})
    if not requests:
        return {}
    try:
        return fetch_parameters_for_classes(client, requests)
    except Exception:
        return {}


def pull_nokia_mo_records(
    client,
    mo_class_id: str,
    *,
    scope_level: str,
    conf_id: int = 1,
    meta_parameters: list[dict[str, str]] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, str], list[str]]:
    """
    Network-wide full export of one Nokia MO class.

    Returns ``(records, ne_by_object_key, warnings)``.
    """
    if ':' not in mo_class_id:
        raise ValueError(f'Invalid Nokia MO class id: {mo_class_id}')
    adaptation, abbreviation = mo_class_id.split(':', 1)
    part = extract_full_mo_class(
        client,
        adaptation,
        abbreviation,
        conf_id=conf_id,
        site_id=None,
        scope_level=scope_level,
        meta_parameters=meta_parameters,
    )
    part.pop('mo_count', None)
    records = sheet_to_records(part)
    ne_by_key = {key: _record_ne_name(record) for key, record in records.items()}
    return records, ne_by_key, []


def pull_huawei_mo_records(
    client,
    mo_id: str,
    ne_names: list[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, str], list[str]]:
    """
    Full MML export of one Huawei MO across all eNodeBs.

    Object keys are prefixed with the NE name so they stay unique network-wide.
    Returns ``(records, ne_by_object_key, warnings)``.
    """
    selection = {'mo_id': mo_id, 'export_all': True, 'parameters': []}
    rows, errors = _selection_rows(client, ne_names, selection)

    records: dict[str, dict[str, Any]] = {}
    ne_by_key: dict[str, str] = {}
    by_ne: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        ne = str(row.get('NE') or '').strip()
        by_ne.setdefault(ne, []).append(row)
    for ne, ne_rows in by_ne.items():
        ne_records = rows_to_records(ne_rows, ignore_columns={'NE'})
        for key, record in ne_records.items():
            full_key = f'{ne}|{key}' if ne else key
            records[full_key] = record
            ne_by_key[full_key] = ne
    warnings = [str(err) for err in errors]
    return records, ne_by_key, warnings
