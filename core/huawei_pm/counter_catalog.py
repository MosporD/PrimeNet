"""
Huawei MAE system counter catalog from OSS export CSVs.

CSV columns: Function Subset ID, Function Subset Name, KPI ID, KPI Name, KPI Unit,
Time/Reference Time/Object aggregations.

KPI ID is the MAE Open API ``counterIds`` value (§5.4).
"""

from __future__ import annotations

import csv
import threading
from pathlib import Path
from typing import Any

_CATALOG_DIR = Path(__file__).resolve().parents[2] / 'data' / 'huawei_pm_counters'

TECHNOLOGY_FILES: dict[str, dict[str, str]] = {
    '2G': {
        'file': '2GBSC.csv',
        'ne_type': 'BSC6900 GSM',
        'oss_label': '2GBSC',
        'description': '2G BSC system counters',
    },
    '3G': {
        'file': '3GRNC.csv',
        'ne_type': 'BSC6900 UMTS',
        'oss_label': '3GRNC',
        'description': '3G RNC system counters',
    },
    '4G': {
        'file': '4GBTS.csv',
        'ne_type': 'eNodeB',
        'oss_label': '4GBTS',
        'description': '4G BTS / eNodeB system counters',
    },
}

_CACHE: dict[str, Any] = {}
_CACHE_LOCK = threading.Lock()

_HEADER_ALIASES = {
    'function subset id': 'function_subset_id',
    'function subset name': 'function_subset_name',
    'kpi id': 'id',
    'kpi name': 'name',
    'kpi unit': 'unit',
    'time aggregation': 'time_aggregation',
    'reference time aggregation': 'reference_time_aggregation',
    'object aggregation': 'object_aggregation',
    'reference object aggregation': 'reference_object_aggregation',
}


def catalog_dir() -> Path:
    return _CATALOG_DIR


def _parse_int(raw: str) -> int | None:
    text = (raw or '').strip().rstrip(',')
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _parse_counter_file(path: Path) -> tuple[str, list[dict[str, Any]]]:
    if not path.is_file():
        return '', []

    oss_ne_type = ''
    counters: list[dict[str, Any]] = []
    col_map: dict[int, str] = {}

    with path.open(newline='', encoding='utf-8-sig') as fh:
        reader = csv.reader(fh)
        for row in reader:
            if not row or not any(str(c).strip() for c in row):
                continue
            first = str(row[0]).strip()
            lower_first = first.lower()

            if lower_first.startswith('ne type') and not col_map:
                oss_ne_type = str(row[1]).strip().rstrip(',') if len(row) > 1 else ''
                continue

            if lower_first == 'function subset id' or first == 'Function Subset ID':
                col_map = {}
                for idx, cell in enumerate(row):
                    key = _HEADER_ALIASES.get(str(cell).strip().lower())
                    if key:
                        col_map[idx] = key
                continue

            if not col_map:
                continue

            item: dict[str, Any] = {}
            for idx, key in col_map.items():
                if idx < len(row):
                    item[key] = str(row[idx]).strip().rstrip(',')
                else:
                    item[key] = ''

            counter_id = _parse_int(str(item.get('id') or ''))
            subset_id = _parse_int(str(item.get('function_subset_id') or ''))
            name = str(item.get('name') or '').strip()
            if counter_id is None or not name:
                continue

            item['id'] = counter_id
            item['function_subset_id'] = subset_id
            item['label'] = name
            item['search'] = ' '.join(
                filter(
                    None,
                    [
                        name.lower(),
                        str(counter_id),
                        str(item.get('function_subset_name') or '').lower(),
                        str(subset_id or ''),
                    ],
                ),
            )
            counters.append(item)

    return oss_ne_type, counters


def _load_technology(technology: str) -> dict[str, Any]:
    tech = str(technology or '').strip().upper()
    meta = TECHNOLOGY_FILES.get(tech)
    if not meta:
        return {'technology': tech, 'counters': [], 'subsets': [], 'configured': False}

    path = _CATALOG_DIR / meta['file']
    oss_ne_type, counters = _parse_counter_file(path)

    subsets_map: dict[int, dict[str, Any]] = {}
    for row in counters:
        sid = row.get('function_subset_id')
        if sid is None:
            continue
        if sid not in subsets_map:
            subsets_map[sid] = {
                'id': sid,
                'name': row.get('function_subset_name') or f'Subset {sid}',
                'counter_count': 0,
            }
        subsets_map[sid]['counter_count'] += 1

    subsets = sorted(subsets_map.values(), key=lambda s: str(s.get('name') or '').lower())

    return {
        'technology': tech,
        'configured': path.is_file(),
        'file': meta['file'],
        'ne_type': meta['ne_type'],
        'oss_ne_type': oss_ne_type or meta['oss_label'],
        'description': meta['description'],
        'counters': counters,
        'subsets': subsets,
        'total_counters': len(counters),
    }


def get_technology_catalog(technology: str, *, reload: bool = False) -> dict[str, Any]:
    tech = str(technology or '').strip().upper()
    if not tech:
        return {'technology': '', 'counters': [], 'subsets': [], 'configured': False}

    with _CACHE_LOCK:
        if not reload and tech in _CACHE:
            return _CACHE[tech]
        payload = _load_technology(tech)
        _CACHE[tech] = payload
        return payload


def list_technologies() -> list[dict[str, Any]]:
    out = []
    for tech, meta in TECHNOLOGY_FILES.items():
        cat = get_technology_catalog(tech)
        out.append({
            'technology': tech,
            'configured': cat.get('configured'),
            'file': meta['file'],
            'ne_type': meta['ne_type'],
            'total_counters': cat.get('total_counters', 0),
            'subset_count': len(cat.get('subsets') or []),
            'description': meta['description'],
        })
    return out


def filter_counters(
    technology: str,
    *,
    q: str = '',
    subset_id: int | None = None,
    limit: int = 300,
    offset: int = 0,
) -> dict[str, Any]:
    cat = get_technology_catalog(technology)
    rows = list(cat.get('counters') or [])

    if subset_id is not None:
        rows = [r for r in rows if r.get('function_subset_id') == subset_id]

    query = (q or '').strip().lower()
    if query:
        rows = [r for r in rows if query in r.get('search', '')]

    total = len(rows)
    limit = max(1, min(int(limit or 300), 500))
    offset = max(0, int(offset or 0))
    page = rows[offset: offset + limit]

    return {
        'technology': cat.get('technology') or technology,
        'ne_type': cat.get('ne_type'),
        'oss_ne_type': cat.get('oss_ne_type'),
        'configured': cat.get('configured'),
        'total': total,
        'offset': offset,
        'limit': limit,
        'counters': [
            {
                'id': r['id'],
                'name': r.get('name') or r.get('label'),
                'label': r.get('label') or r.get('name'),
                'unit': r.get('unit') or '',
                'function_subset_id': r.get('function_subset_id'),
                'function_subset_name': r.get('function_subset_name') or '',
                'time_aggregation': r.get('time_aggregation') or '',
                'object_aggregation': r.get('object_aggregation') or '',
            }
            for r in page
        ],
    }


def counters_for_subset(technology: str, subset_id: int, *, max_count: int = 150) -> list[int]:
    cat = get_technology_catalog(technology)
    ids: list[int] = []
    for row in cat.get('counters') or []:
        if row.get('function_subset_id') != subset_id:
            continue
        cid = row.get('id')
        if isinstance(cid, int):
            ids.append(cid)
        if len(ids) >= max_count:
            break
    return ids


def validate_query_counter_ids(counter_ids: list[int], technology: str) -> tuple[list[int], list[int]]:
    """Return (valid_ids, unknown_ids)."""
    cat = get_technology_catalog(technology)
    known = {r['id'] for r in (cat.get('counters') or []) if isinstance(r.get('id'), int)}
    valid: list[int] = []
    unknown: list[int] = []
    for cid in counter_ids:
        if cid in known:
            valid.append(cid)
        else:
            unknown.append(cid)
    return valid, unknown


def subset_ids_for_counters(counter_ids: list[int], technology: str) -> set[int]:
    cat = get_technology_catalog(technology)
    by_id = {r['id']: r.get('function_subset_id') for r in (cat.get('counters') or [])}
    out: set[int] = set()
    for cid in counter_ids:
        sid = by_id.get(cid)
        if sid is not None:
            out.add(int(sid))
    return out
