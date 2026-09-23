"""Parse Huawei BSC GTRX / GCELL / G2GNCELL MML rows for Adjacency GIS."""

from __future__ import annotations

import re
from typing import Any

_YES_TOKENS = frozenset({
    'yes', 'y', 'true', '1', 'on', 'main', 'bcch', 'mainbcch',
})
_ACTIVE_TOKENS = frozenset({
    'activated', 'active', 'normal', 'available', 'unblocked', 'yes', '1', 'on',
})
_UNLOCKED_TOKENS = frozenset({
    'unlocked', 'unlock', 'enabled', 'unblocked', '0', 'normal',
})


def _norm_col(key: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', (key or '').lower())


def _column_map(row: dict[str, Any]) -> dict[str, str]:
    return {_norm_col(k): k for k in row}


def _pick(row: dict[str, Any], *candidates: str) -> Any:
    cmap = _column_map(row)
    for name in candidates:
        key = cmap.get(_norm_col(name))
        if key is not None and row.get(key) not in (None, ''):
            return row.get(key)
    return None


def _scalar(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, (list, tuple)):
        if not value:
            return ''
        return _scalar(value[0])
    return str(value).strip()


def _to_int(value: Any) -> int | None:
    text = _scalar(value)
    if not text:
        return None
    match = re.search(r'-?\d+', text.replace(',', ''))
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def is_main_bcch_trx(value: Any) -> bool:
    token = _scalar(value).lower().replace(' ', '')
    if not token:
        return False
    if token in _YES_TOKENS:
        return True
    return 'mainbcch' in token or token.startswith('yes')


def is_trx_active(active_status: Any, admin_state: Any) -> bool:
    """Keep TRX when Active Status is activated and Administrative State unlocked."""
    active = _scalar(active_status).lower().replace(' ', '')
    admin = _scalar(admin_state).lower().replace(' ', '')
    active_ok = (not active) or any(t in active for t in _ACTIVE_TOKENS) or active in _ACTIVE_TOKENS
    admin_ok = (not admin) or admin in _UNLOCKED_TOKENS or 'unlock' in admin
    # Explicit negatives
    if any(x in active for x in ('deactiv', 'inactive', 'fault', 'block')):
        active_ok = False
    if any(x in admin for x in ('lock', 'shut', 'disable')) and 'unlock' not in admin:
        admin_ok = False
    return active_ok and admin_ok


def sector_dn(bsc: str, cell_index: int | str, trx_id: Any = None) -> str:
    bsc_t = _scalar(bsc) or 'BSC'
    cell_t = _scalar(cell_index)
    trx_t = _scalar(trx_id)
    if trx_t:
        return f'huawei:{bsc_t}:{cell_t}:trx:{trx_t}'
    return f'huawei:{bsc_t}:{cell_t}'


def parse_gcell_row(row: dict[str, Any], *, ne_name: str = '') -> dict[str, Any] | None:
    """Flatten LST GCELL for Cell Index → name / CI / LAC / BCCH."""
    bsc = _scalar(_pick(row, 'BSC Name', 'BSC', 'NE Name', 'ne_name')) or _scalar(ne_name)
    cell_index = _to_int(_pick(row, 'Cell Index', 'Local Cell ID', 'Cell No.', 'Cell No'))
    cell_name = _scalar(_pick(row, 'Cell Name', 'GSM Cell Name', 'Name'))
    ci = _to_int(_pick(row, 'CI', 'Cell ID', 'CGI'))
    lac = _to_int(_pick(row, 'LAC', 'Location Area Code'))
    bcch = _to_int(_pick(row, 'BCCH', 'BCCH Frequency', 'Frequency'))
    if cell_index is None and not cell_name:
        return None
    return {
        'bsc_id': bsc,
        'cell_index': cell_index,
        'cell_name': cell_name,
        'cell_id': ci,
        'lac': lac,
        'bcch': bcch,
        'ne_name': _scalar(ne_name) or bsc,
    }


def parse_gtrx_bcch_row(row: dict[str, Any], *, ne_name: str = '') -> dict[str, Any] | None:
    """
    Keep main BCCH TRX rows from LST GTRX.

    Expected columns (U2020): BSC Name, Cell Index, TRX ID, TRX Name,
    Frequency, Is Main BCCH TRX, TRX No., Active Status, Administrative State.
    """
    if not is_main_bcch_trx(_pick(row, 'Is Main BCCH TRX', 'Main BCCH TRX', 'Is Main BCCH', 'BCCH TRX')):
        return None
    active = _pick(row, 'Active Status', 'TRX Active Status', 'Operational State')
    admin = _pick(row, 'Administrative State', 'Admin State', 'TRX Admin State')
    if not is_trx_active(active, admin):
        return None

    bsc = _scalar(_pick(row, 'BSC Name', 'BSC', 'NE Name')) or _scalar(ne_name)
    cell_index = _to_int(_pick(row, 'Cell Index', 'Local Cell ID', 'Cell No.', 'Cell No'))
    trx_id = _scalar(_pick(row, 'TRX ID', 'TRX Id', 'TRX No.', 'TRX No', 'TRX Index'))
    trx_name = _scalar(_pick(row, 'TRX Name', 'Name'))
    freq = _to_int(_pick(row, 'Frequency', 'Freq', 'ARFCN', 'BCCH Frequency', 'initialFrequency'))
    if cell_index is None and not trx_name:
        return None

    dn = sector_dn(bsc, cell_index if cell_index is not None else trx_name, trx_id or '0')
    return {
        'dn': dn,
        'bts_dn': sector_dn(bsc, cell_index if cell_index is not None else trx_name),
        'bsc_id': bsc,
        'bcf_id': '',
        'instance': trx_id,
        'segment_name': trx_name,
        'cell_name': '',  # filled from GCELL join
        'cell_index': cell_index,
        'cell_id': None,
        'bcch': freq,
        'trx_dn': dn,
        'admin_state': _scalar(admin),
        'active_status': _scalar(active),
        'vendor': 'huawei',
        'ne_name': _scalar(ne_name) or bsc,
    }


def parse_g2gncell_row(row: dict[str, Any], *, ne_name: str = '') -> dict[str, Any] | None:
    """Flatten LST G2GNCELL (GSM→GSM configured neighbor)."""
    bsc = _scalar(_pick(row, 'BSC Name', 'BSC', 'NE Name')) or _scalar(ne_name)
    src_index = _to_int(_pick(
        row,
        'Cell Index',
        'Source Cell Index',
        'Src Cell Index',
        'Local Cell Index',
        'Serving Cell Index',
    ))
    adj_ci = _to_int(_pick(
        row,
        'NCell CI',
        'Neighbor Cell CI',
        'Neighbour Cell CI',
        'NCELL CI',
        'Adjacent Cell CI',
        'CI',
        'Neighbor CI',
        'NCell ID',
        'Neighbor Cell ID',
    ))
    adj_lac = _to_int(_pick(
        row,
        'NCell LAC',
        'Neighbor Cell LAC',
        'Neighbour Cell LAC',
        'NCELL LAC',
        'Adjacent Cell LAC',
        'LAC',
        'Neighbor LAC',
    ))
    adj_name = _scalar(_pick(
        row,
        'NCell Name',
        'Neighbor Cell Name',
        'Neighbour Cell Name',
        'NCELL Name',
        'Adjacent Cell Name',
        'Neighbor Name',
    ))
    bcch = _to_int(_pick(
        row,
        'NCell BCCH',
        'Neighbor BCCH',
        'Neighbour BCCH',
        'NCELL BCCH',
        'BCCH',
        'BCCH Frequency',
        'Frequency',
    ))
    ncell_index = _to_int(_pick(
        row,
        'NCell Index',
        'Neighbor Cell Index',
        'Neighbour Cell Index',
        'NCELL Index',
    ))
    if src_index is None:
        return None
    if adj_ci is None and not adj_name and ncell_index is None:
        return None

    src_dn = sector_dn(bsc, src_index)
    edge_id = (
        f'huawei:{bsc}:{src_index}->'
        f'{adj_ci if adj_ci is not None else adj_name or ncell_index}'
    )
    return {
        'dn': edge_id,
        'bts_dn': src_dn,
        'source_dn': src_dn,
        'source_cell_index': src_index,
        'adj_ci': adj_ci if adj_ci is not None else ncell_index,
        'adj_lac': adj_lac,
        'adj_mcc': _to_int(_pick(row, 'MCC', 'NCell MCC', 'Neighbor MCC')),
        'adj_mnc': _to_int(_pick(row, 'MNC', 'NCell MNC', 'Neighbor MNC')),
        'bcch_frequency': bcch,
        'adj_name': adj_name,
        'ncell_index': ncell_index,
        'vendor': 'huawei',
        'bsc_id': bsc,
        'ne_name': _scalar(ne_name) or bsc,
    }


def join_trx_with_gcell(
    trx_rows: list[dict[str, Any]],
    gcell_by_key: dict[tuple[str, int], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach cell_name / CI from GCELL onto main-BCCH TRX sectors."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for trx in trx_rows:
        bsc = str(trx.get('bsc_id') or '')
        idx = trx.get('cell_index')
        gcell = None
        if idx is not None:
            gcell = gcell_by_key.get((_scalar(bsc).lower(), int(idx)))
        sector = dict(trx)
        if gcell:
            sector['cell_name'] = gcell.get('cell_name') or sector.get('cell_name') or ''
            sector['segment_name'] = sector['cell_name'] or sector.get('segment_name') or ''
            if sector.get('cell_id') is None:
                sector['cell_id'] = gcell.get('cell_id')
            if sector.get('bcch') is None:
                sector['bcch'] = gcell.get('bcch')
            # Stable sector key without TRX suffix for edge join
            sector['dn'] = sector_dn(bsc, idx)
            sector['bts_dn'] = sector['dn']
        else:
            sector['segment_name'] = sector.get('segment_name') or sector.get('trx_dn') or ''
            sector['cell_name'] = sector.get('cell_name') or sector['segment_name']
            sector['dn'] = sector.get('bts_dn') or sector['dn']
        if sector['dn'] in seen:
            continue
        seen.add(sector['dn'])
        sector['vendor'] = 'huawei'
        out.append(sector)
    return out
