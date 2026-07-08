"""Shared CM record normalization used by NE Comparison and the discrepancy audit.

Extracted from ``modules/ne_comparison/routes.py`` so both the interactive
comparison endpoints and the daily full-network audit normalize CM pulls the
same way (identity columns, object keys, value normalization).
"""

from __future__ import annotations

from typing import Any

# Columns that identify an object instance rather than configure it.
IDENTITY_COLUMNS = {
    'dn', 'distname', 'moid', '$instance', 'instance', 'ne',
    'cell name', 'object name',
}

# Preferred columns (in order) for building a stable per-object key.
KEY_PRIORITY = (
    'DN', 'distName', 'moId', '$instance', 'instance',
    'Local Cell ID', 'Cell Name', 'Cell ID', 'eNodeB ID',
    'Nr Cell ID', 'BTS ID', 'TRX ID', 'Object Name',
)


def record_key(record: dict[str, Any], *, fallback: str) -> str:
    for col in KEY_PRIORITY:
        value = record.get(col)
        if value not in (None, ''):
            return f'{col}={value}'
    for col, value in record.items():
        if value not in (None, ''):
            return f'{col}={value}'
    return fallback


def sheet_to_records(
    sheet: dict[str, Any],
    *,
    ignore_columns: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Convert a Nokia extraction sheet ({headers, rows}) to keyed records."""
    headers = [str(h) for h in (sheet.get('headers') or [])]
    rows = sheet.get('rows') or []
    ignore = {c.lower() for c in (ignore_columns or set())}
    records: dict[str, dict[str, Any]] = {}
    for idx, row in enumerate(rows):
        record = {
            header: row[pos] if pos < len(row) else ''
            for pos, header in enumerate(headers)
            if header.lower() not in ignore
        }
        key = record_key(record, fallback=f'row-{idx + 1}')
        records[key] = record
    return records


def rows_to_records(
    rows: list[dict[str, Any]],
    *,
    ignore_columns: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Convert Huawei MML row dicts to keyed records."""
    ignore = {c.lower() for c in (ignore_columns or set())}
    records: dict[str, dict[str, Any]] = {}
    for idx, row in enumerate(rows):
        record = {str(k): v for k, v in row.items() if str(k).lower() not in ignore}
        key = record_key(record, fallback=f'row-{idx + 1}')
        records[key] = record
    return records


def normalize_value(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, (dict, list, tuple)):
        return str(value)
    return str(value).strip()
