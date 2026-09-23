"""Parse Nokia BSC BTS / TRX / ADCE managed-object payloads for Adjacency GIS."""

from __future__ import annotations

import re
from typing import Any

# channel0Type = 4 → MBCCH (main BCCH) per Nokia param dictionary.
BCCH_CHANNEL0_TYPE = 4
NCL_HARD_LIMIT = 32
DEFAULT_OVERSHOOT_KM = 15.0

_UNLOCKED_TOKENS = frozenset({
    '',
    '0',
    'unlocked',
    'unlock',
    'enabled',
    'on',
})


def _param_lookup(parameters: dict[str, Any], name: str) -> Any:
    if name in parameters:
        return parameters[name]
    lowered = name.lower()
    for key, value in parameters.items():
        if str(key).lower() == lowered:
            return value
    return None


def _scalar(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, (list, tuple)):
        if not value:
            return ''
        return _scalar(value[0])
    if isinstance(value, dict):
        for key in ('value', 'Value', 'items', '$value'):
            if key in value:
                return _scalar(value[key])
        return ''
    return str(value).strip()


def _to_int(value: Any) -> int | None:
    text = _scalar(value)
    if not text:
        return None
    # "MBCCH (4)" / "4: MBCCH" / "4"
    match = re.search(r'(?<!\d)(\d+)(?!\d)', text)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    try:
        return int(float(text.replace(',', '')))
    except (TypeError, ValueError):
        return None


def is_admin_active(value: Any) -> bool:
    """True when adminState is unlocked / enabled (Nokia 2G convention: 0 = unlocked)."""
    # Prefer numeric enum when present (0 unlocked, 1 locked).
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value) == 0
    token = _scalar(value).lower().replace(' ', '')
    if token in _UNLOCKED_TOKENS:
        return True
    n = _to_int(value)
    if n is not None and token.replace('.', '', 1).isdigit():
        return n == 0
    return False


def is_bcch_channel0_type(value: Any) -> bool:
    """channel0Type == 4 (MBCCH)."""
    n = _to_int(value)
    if n == BCCH_CHANNEL0_TYPE:
        return True
    text = _scalar(value).upper()
    return 'MBCCH' in text and 'MBCCHC' not in text and 'MBCCB' not in text and n is None


def parent_bts_dn(dn: str) -> str:
    """Strip trailing /TRX-* or /ADCE-* to the parent BTS DN."""
    text = str(dn or '').strip()
    if not text:
        return ''
    for marker in ('/TRX-', '/ADCE-', '/trx-', '/adce-'):
        idx = text.upper().rfind(marker.upper())
        if idx != -1:
            return text[:idx]
    # Generic: drop last path segment if it looks like TRX/ADCE.
    parts = text.rsplit('/', 1)
    if len(parts) == 2 and re.match(r'(?i)(TRX|ADCE)-', parts[1]):
        return parts[0]
    return text


def bsc_id_from_dn(dn: str) -> str:
    match = re.search(r'/BSC-([^/]+)', str(dn or ''), flags=re.IGNORECASE)
    return match.group(1).strip() if match else ''


def bcf_id_from_dn(dn: str) -> str:
    match = re.search(r'/BCF-([^/]+)', str(dn or ''), flags=re.IGNORECASE)
    return match.group(1).strip() if match else ''


def record_from_managed_object(mo: dict[str, Any], param_names: tuple[str, ...]) -> dict[str, Any]:
    dn = str(mo.get('moId') or mo.get('distName') or '').strip()
    parameters = mo.get('parameters') if isinstance(mo.get('parameters'), dict) else {}
    record: dict[str, Any] = {'DN': dn}
    instance = _param_lookup(parameters, '$instance')
    if instance is None:
        tail = dn.rsplit('/', 1)[-1]
        if '-' in tail:
            instance = tail.rsplit('-', 1)[-1]
    if instance is not None:
        record['$instance'] = _scalar(instance)
    for name in param_names:
        raw = _param_lookup(parameters, name)
        if raw is not None:
            record[name] = raw
    return record


def parse_bts_record(mo: dict[str, Any]) -> dict[str, Any] | None:
    """Flatten one NOKBSC:BTS MO. Returns None if inactive."""
    rec = record_from_managed_object(
        mo,
        ('segmentName', 'name', 'cellId', 'adminState', 'nwName'),
    )
    dn = rec.get('DN') or ''
    if not dn:
        return None
    if not is_admin_active(rec.get('adminState')):
        return None
    segment = _scalar(rec.get('segmentName'))
    name = _scalar(rec.get('name')) or segment
    cell_id = _to_int(rec.get('cellId'))
    return {
        'dn': dn,
        'bsc_id': bsc_id_from_dn(dn),
        'bcf_id': bcf_id_from_dn(dn),
        'instance': _scalar(rec.get('$instance')),
        'segment_name': segment,
        'cell_name': name or segment,
        'cell_id': cell_id,
        'admin_state': _scalar(rec.get('adminState')),
    }


def parse_trx_bcch(mo: dict[str, Any]) -> dict[str, Any] | None:
    """Return BCCH TRX summary when channel0Type==4 and TRX is active."""
    rec = record_from_managed_object(
        mo,
        ('channel0Type', 'initialFrequency', 'adminState', 'preferredBcchMark'),
    )
    dn = rec.get('DN') or ''
    if not dn:
        return None
    if not is_admin_active(rec.get('adminState')):
        return None
    if not is_bcch_channel0_type(rec.get('channel0Type')):
        return None
    freq = _to_int(rec.get('initialFrequency'))
    return {
        'dn': dn,
        'bts_dn': parent_bts_dn(dn),
        'channel0_type': _to_int(rec.get('channel0Type')) or BCCH_CHANNEL0_TYPE,
        'bcch': freq,
        'admin_state': _scalar(rec.get('adminState')),
    }


def parse_adce_record(mo: dict[str, Any]) -> dict[str, Any] | None:
    """Flatten one NOKBSC:ADCE adjacency under a BTS."""
    rec = record_from_managed_object(
        mo,
        (
            'adjacentCellIdCI',
            'adjacentCellIdLac',
            'adjacentCellIdMCC',
            'adjacentCellIdMNC',
            'adjIdCi',
            'adjIdLac',
            'adjIdMCC',
            'adjIdMNC',
            'bcchFrequency',
            'adminState',
        ),
    )
    dn = rec.get('DN') or ''
    if not dn:
        return None
    # Some ADCE trees expose adminState; if present and locked, skip.
    if 'adminState' in rec and not is_admin_active(rec.get('adminState')):
        return None
    ci = _to_int(rec.get('adjacentCellIdCI'))
    if ci is None:
        ci = _to_int(rec.get('adjIdCi'))
    lac = _to_int(rec.get('adjacentCellIdLac'))
    if lac is None:
        lac = _to_int(rec.get('adjIdLac'))
    if ci is None:
        return None
    return {
        'dn': dn,
        'bts_dn': parent_bts_dn(dn),
        'adj_ci': ci,
        'adj_lac': lac,
        'adj_mcc': _to_int(rec.get('adjacentCellIdMCC')) or _to_int(rec.get('adjIdMCC')),
        'adj_mnc': _to_int(rec.get('adjacentCellIdMNC')) or _to_int(rec.get('adjIdMNC')),
        'bcch_frequency': _to_int(rec.get('bcchFrequency')),
    }


def build_sector_rows(
    bts_rows: list[dict[str, Any]],
    bcch_by_bts: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Join active BTS with BCCH TRX frequency."""
    out: list[dict[str, Any]] = []
    for bts in bts_rows:
        dn = bts['dn']
        bcch_rec = bcch_by_bts.get(dn) or {}
        out.append({
            **bts,
            'bcch': bcch_rec.get('bcch'),
            'trx_dn': bcch_rec.get('dn') or '',
        })
    return out
