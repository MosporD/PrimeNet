"""
Site geometry for the RET Management hologram.

Reads the PrimeNet metadata inventory (per-technology ``cells_*`` tables) and
returns the sector layout of one site: true azimuth per sector, tilts, antenna
height and the cells that make up each sector. The RET Management UI draws this
as a top view and binds the live RET rows (Huawei ``RETSUBUNIT`` / Nokia
``RETU_R``) onto the matching sector.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from collections import Counter
from typing import Any

from core.cm_extractor.site_catalog import (
    _known_nokia_metadata_site_ids,
    resolve_nokia_metadata_site_id,
    resolve_nokia_netact_site_id,
)
from db.runtime import connect_metadata, execute_query
from modules.reports.metadata_helpers import _metadata_table_columns, _pick_col, _sql_ident

logger = logging.getLogger(__name__)

# Sector suffix on a cell name, e.g. AMMAN1_A2 / AMMAN1-B / AMMAN1_C13.
# Deliberately limited to A-F: letters further along are technology/band markers in
# PrimeNet cell names (``..._N1`` is NR, ``..._G1`` is GSM), not sector ids.
_CELL_SECTOR_SUFFIX_RE = re.compile(r'[-_]([A-Fa-f])(\d*)$')
_DIGITS_RE = re.compile(r'(\d+)')

# table, technology label, site-id aliases, site-name aliases, band aliases
TECH_SPECS: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[str, ...]], ...] = (
    (
        'cells_2g',
        '2G',
        ('site_id', 'bcf id', 'bts id'),
        ('site_name', 'bts name'),
        ('frequency_band', 'band', 'bcch'),
    ),
    (
        'cells_3g',
        '3G',
        ('site_id', 'nodeb_id'),
        ('nodeb_name', 'site_name'),
        ('frequency_band', 'band', 'dl_uarfcn'),
    ),
    (
        'cells_4g_fdd',
        '4G-FDD',
        ('site_id', 'enb_id_actual', 'enb_id_config', 'enodeb id'),
        ('enb_name', 'site_name'),
        ('band', 'frequency_band', 'dl_earfcn'),
    ),
    (
        'cells_4g_tdd',
        '4G-TDD',
        ('site_id', 'enb_id_actual', 'enb_id_config', 'enodeb id'),
        ('enb_name', 'site_name'),
        ('band', 'frequency_band', 'dl_earfcn'),
    ),
    (
        'cells_5g',
        '5G',
        ('site_id', 'gnb_id_actual', 'gnb_id_config', 'gnb id'),
        ('gnb_name', 'site_name'),
        ('band', 'bw', 'nrarfcn'),
    ),
)

TECH_ORDER = ('2G', '3G', '4G-FDD', '4G-TDD', '5G')
DEFAULT_ANTENNA_HEIGHT_M = 25.0
DEFAULT_BEAMWIDTH_DEG = 65.0


def _as_float(value: Any) -> float | None:
    text = str(value if value is not None else '').strip()
    if not text or text.lower() in ('none', 'null', 'nan', '?', '-'):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _as_text(value: Any) -> str:
    text = str(value if value is not None else '').strip()
    return '' if text.lower() in ('none', 'null', 'nan', '?') else text


def normalize_azimuth(value: Any) -> float | None:
    """Wrap an azimuth into [0, 360). Returns None when not numeric."""
    deg = _as_float(value)
    if deg is None:
        return None
    deg = deg % 360.0
    if deg < 0:
        deg += 360.0
    return round(deg, 1)


def normalize_sector_key(value: Any, *, cell_name: str = '') -> str:
    """
    Canonical sector key shared by metadata, Nokia ``sectorID`` and Huawei subunits.

    Letters map onto numbers (A → 1, B → 2, C → 3) so ``AMMAN1_A2`` and
    ``sectorID=1`` land on the same sector.
    """
    text = _as_text(value).upper()
    if not text and cell_name:
        match = _CELL_SECTOR_SUFFIX_RE.search(str(cell_name).strip())
        if match:
            text = match.group(1).upper()
    if not text:
        return ''
    if text.endswith('.0') and text[:-2].isdigit():
        text = text[:-2]
    if len(text) == 1 and text.isalpha():
        return str(ord(text) - 64)
    digits = _DIGITS_RE.search(text)
    if digits:
        return str(int(digits.group(1)))
    letters = re.sub(r'[^A-Z]', '', text)
    if len(letters) == 1:
        return str(ord(letters) - 64)
    return text


def sector_label(key: str) -> str:
    if key.isdigit():
        index = int(key)
        if 1 <= index <= 26:
            return f'{index} ({chr(64 + index)})'
        return str(index)
    return key or 'Unassigned'


def default_beamwidth(sector_count: int) -> float:
    if sector_count <= 1:
        return 360.0
    if sector_count <= 4:
        return DEFAULT_BEAMWIDTH_DEG
    return max(20.0, round(360.0 / sector_count * 0.85, 1))


def _dominant(values: list[float], *, tolerance: float = 5.0) -> float | None:
    """Most common value (within *tolerance*), falling back to the first value."""
    if not values:
        return None
    buckets: Counter[float] = Counter()
    for value in values:
        placed = False
        for existing in list(buckets):
            if abs(((value - existing + 180.0) % 360.0) - 180.0) <= tolerance:
                buckets[existing] += 1
                placed = True
                break
        if not placed:
            buckets[round(value, 1)] += 1
    best, _count = buckets.most_common(1)[0]
    members = [
        value for value in values
        if abs(((value - best + 180.0) % 360.0) - 180.0) <= tolerance
    ]
    if not members:
        return round(best, 1)
    return round(sum(members) / len(members), 1)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 2)
    return round((ordered[mid - 1] + ordered[mid]) / 2.0, 2)


def site_id_candidates(
    vendor: str,
    site_id: str,
    *,
    metadata_site_id: str = '',
) -> list[str]:
    """
    Every id spelling that may appear in the inventory for one picked NE.

    The Nokia picker hands out NetAct MRBTS instance ids (``51021``) while the
    inventory keys on the PrimeNet metadata id (``1021``); Huawei uses the
    metadata id directly.
    """
    tokens: list[str] = []

    def add(value: Any) -> None:
        text = _as_text(value)
        if text and text not in tokens:
            tokens.append(text)

    add(metadata_site_id)
    add(site_id)
    if (vendor or '').strip().lower() == 'nokia':
        raw = _as_text(site_id)
        if raw:
            try:
                known = _known_nokia_metadata_site_ids()
            except Exception:  # metadata not synced yet
                known = set()
            add(resolve_nokia_metadata_site_id(raw, known_metadata_ids=known))
            try:
                add(resolve_nokia_netact_site_id(raw, known_metadata_ids=known))
            except Exception:
                pass
    for token in list(tokens):
        if token.isdigit():
            add(str(int(token)))
    return tokens


def _select_site_cells(
    conn,
    table: str,
    technology: str,
    site_aliases: tuple[str, ...],
    name_aliases: tuple[str, ...],
    band_aliases: tuple[str, ...],
    *,
    id_candidates: list[str],
    site_name: str,
) -> list[dict[str, Any]]:
    columns = _metadata_table_columns(conn, table)
    if not columns:
        return []
    low_to_real = {str(c).strip().lower(): c for c in columns}
    site_col = _pick_col(list(site_aliases), low_to_real)
    name_col = _pick_col(list(name_aliases), low_to_real)
    cell_col = _pick_col(
        ['cell_name', 'cell name', 'wcel name', 'lncel name', 'nrcel name', 'bts name'],
        low_to_real,
    )
    sector_col = _pick_col(['sector', 'sector_id', 'sector id', 'sectorid'], low_to_real)
    az_col = _pick_col(['azimuth', 'azimuth_deg', 'azimuth degree'], low_to_real)
    et_col = _pick_col(['etilt', 'electrical_tilt', 'electrical tilt', 'e_tilt'], low_to_real)
    mt_col = _pick_col(['mtilt', 'mechanical_tilt', 'mechanical tilt', 'm_tilt'], low_to_real)
    height_col = _pick_col(['height', 'antenna_height', 'antenna height'], low_to_real)
    band_col = _pick_col(list(band_aliases), low_to_real)
    vendor_col = _pick_col(['vendor'], low_to_real)
    lat_col = _pick_col(['lat', 'latitude'], low_to_real)
    lng_col = _pick_col(['long', 'longitude', 'lng', 'lon'], low_to_real)
    state_col = _pick_col(['active_state', 'admin_state', 'status'], low_to_real)

    if not site_col and not name_col:
        return []

    def expr(col: str | None) -> str:
        return _sql_ident(col) if col else 'NULL'

    where: list[str] = []
    params: list[Any] = []
    if site_col and id_candidates:
        placeholders = ', '.join(['?'] * len(id_candidates))
        where.append(f'TRIM(CAST({_sql_ident(site_col)} AS TEXT)) IN ({placeholders})')
        params.extend(id_candidates)
    if name_col and site_name:
        where.append(f'UPPER(TRIM(CAST({_sql_ident(name_col)} AS TEXT))) = ?')
        params.append(site_name.strip().upper())
    if not where:
        return []

    sql = f'''
        SELECT
            {expr(cell_col)}   AS cell_name,
            {expr(sector_col)} AS sector,
            {expr(az_col)}     AS azimuth,
            {expr(et_col)}     AS electrical_tilt,
            {expr(mt_col)}     AS mechanical_tilt,
            {expr(height_col)} AS height,
            {expr(band_col)}   AS band,
            {expr(vendor_col)} AS vendor,
            {expr(lat_col)}    AS latitude,
            {expr(lng_col)}    AS longitude,
            {expr(state_col)}  AS state,
            {expr(site_col)}   AS site_ref,
            {expr(name_col)}   AS site_ref_name
        FROM {_sql_ident(table)}
        WHERE {' OR '.join(where)}
    '''
    try:
        rows = execute_query(conn, sql, params).fetchall()
    except (sqlite3.OperationalError, sqlite3.DatabaseError) as exc:
        logger.warning('RET site layout: %s query failed (%s)', table, exc)
        return []

    out: list[dict[str, Any]] = []
    for row in rows:
        record = dict(row) if not isinstance(row, dict) else row
        cell_name = _as_text(record.get('cell_name'))
        out.append({
            'cell_name': cell_name,
            'technology': technology,
            'sector_key': normalize_sector_key(record.get('sector'), cell_name=cell_name),
            'sector_raw': _as_text(record.get('sector')),
            'azimuth': normalize_azimuth(record.get('azimuth')),
            'electrical_tilt': _as_float(record.get('electrical_tilt')),
            'mechanical_tilt': _as_float(record.get('mechanical_tilt')),
            'height': _as_float(record.get('height')),
            'band': _as_text(record.get('band')),
            'vendor': _as_text(record.get('vendor')),
            'latitude': _as_float(record.get('latitude')),
            'longitude': _as_float(record.get('longitude')),
            'state': _as_text(record.get('state')),
            'site_ref': _as_text(record.get('site_ref')),
            'site_ref_name': _as_text(record.get('site_ref_name')),
        })
    return out


def _lookup_site_row(conn, id_candidates: list[str], site_name: str) -> dict[str, Any]:
    where: list[str] = []
    params: list[Any] = []
    if id_candidates:
        placeholders = ', '.join(['?'] * len(id_candidates))
        where.append(f'TRIM(CAST(site_id AS TEXT)) IN ({placeholders})')
        params.extend(id_candidates)
    if site_name:
        where.append('UPPER(TRIM(site_name)) = ?')
        params.append(site_name.strip().upper())
    if not where:
        return {}
    sql = (
        'SELECT site_id, site_name, latitude, longitude, region, vendor, site_type '
        f'FROM sites WHERE {" OR ".join(where)} LIMIT 1'
    )
    try:
        row = execute_query(conn, sql, params).fetchone()
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return {}
    if not row:
        return {}
    record = dict(row) if not isinstance(row, dict) else row
    return {
        'site_id': _as_text(record.get('site_id')),
        'site_name': _as_text(record.get('site_name')),
        'latitude': _as_float(record.get('latitude')),
        'longitude': _as_float(record.get('longitude')),
        'region': _as_text(record.get('region')),
        'vendor': _as_text(record.get('vendor')),
        'site_type': _as_text(record.get('site_type')),
    }


def _tech_sort_key(tech: str) -> int:
    return TECH_ORDER.index(tech) if tech in TECH_ORDER else len(TECH_ORDER)


def _sector_sort_key(key: str) -> tuple[int, int, str]:
    if not key:
        return (2, 0, '')
    if key.isdigit():
        return (0, int(key), '')
    return (1, 0, key)


def _build_sectors(cells: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for cell in cells:
        grouped.setdefault(cell['sector_key'], []).append(cell)

    unassigned = grouped.pop('', [])
    if unassigned:
        # No sector id and no A-F cell-name suffix: fold each leftover into the
        # sector it shares an azimuth with, else bucket it by azimuth, so the
        # hologram still shows the lobe instead of dropping the cell.
        known_azimuths: dict[str, float] = {}
        for key, members in grouped.items():
            azimuths = [cell['azimuth'] for cell in members if cell['azimuth'] is not None]
            dominant = _dominant(azimuths)
            if dominant is not None:
                known_azimuths[key] = dominant
        matched = 0
        for cell in unassigned:
            azimuth = cell.get('azimuth')
            target = ''
            if azimuth is not None:
                for key, sector_azimuth in known_azimuths.items():
                    if abs(((azimuth - sector_azimuth + 180.0) % 360.0) - 180.0) <= 15.0:
                        target = key
                        break
            if target:
                grouped[target].append(cell)
                matched += 1
            else:
                bucket = f'AZ{int(round(azimuth / 10.0) * 10)}' if azimuth is not None else 'UNKNOWN'
                grouped.setdefault(bucket, []).append(cell)
        leftover = len(unassigned) - matched
        note = f'{len(unassigned)} cell(s) have no sector id in metadata'
        if matched:
            note += f' — {matched} matched onto a sector by azimuth'
        if leftover:
            note += f'{";" if matched else " —"} {leftover} grouped into their own azimuth lobe'
        warnings.append(note + '.')

    sector_count = len([key for key in grouped if key != 'UNKNOWN'])
    beamwidth = default_beamwidth(sector_count)

    sectors: list[dict[str, Any]] = []
    for key in sorted(grouped, key=_sector_sort_key):
        members = grouped[key]
        azimuths = [cell['azimuth'] for cell in members if cell['azimuth'] is not None]
        azimuth = _dominant(azimuths)
        heights = [cell['height'] for cell in members if cell['height'] is not None and cell['height'] > 0]
        etilts = [cell['electrical_tilt'] for cell in members if cell['electrical_tilt'] is not None]
        mtilts = [cell['mechanical_tilt'] for cell in members if cell['mechanical_tilt'] is not None]
        technologies = sorted({cell['technology'] for cell in members}, key=_tech_sort_key)
        bands = sorted({cell['band'] for cell in members if cell['band']})
        vendors = sorted({cell['vendor'] for cell in members if cell['vendor']})
        members_sorted = sorted(
            members,
            key=lambda cell: (_tech_sort_key(cell['technology']), cell['band'], cell['cell_name']),
        )
        sectors.append({
            'key': key,
            'label': sector_label(key),
            'azimuth': azimuth,
            'azimuth_spread': (
                round(max(azimuths) - min(azimuths), 1) if len(azimuths) > 1 else 0.0
            ),
            'azimuth_source': 'metadata' if azimuth is not None else 'unknown',
            'beamwidth': beamwidth,
            'height': _median(heights) or None,
            'electrical_tilt': _median(etilts),
            'mechanical_tilt': _median(mtilts),
            'technologies': technologies,
            'bands': bands,
            'vendors': vendors,
            'cell_count': len(members),
            'cells': [
                {
                    'cell_name': cell['cell_name'],
                    'technology': cell['technology'],
                    'band': cell['band'],
                    'azimuth': cell['azimuth'],
                    'electrical_tilt': cell['electrical_tilt'],
                    'mechanical_tilt': cell['mechanical_tilt'],
                    'height': cell['height'],
                    'vendor': cell['vendor'],
                    'state': cell['state'],
                }
                for cell in members_sorted
            ],
        })

    missing_azimuth = [s['key'] for s in sectors if s['azimuth'] is None]
    if missing_azimuth:
        warnings.append(
            'No azimuth in metadata for sector(s) '
            + ', '.join(sector_label(key) for key in missing_azimuth)
            + ' — those lobes are placed on an even split.'
        )
    return sectors, warnings


def _fill_missing_azimuths(sectors: list[dict[str, Any]]) -> None:
    """Place azimuth-less sectors on an even split so the top view stays readable."""
    missing = [sector for sector in sectors if sector['azimuth'] is None]
    if not missing:
        return
    step = 360.0 / max(1, len(sectors))
    known = {round(sector['azimuth'] or 0.0) for sector in sectors if sector['azimuth'] is not None}
    slot = 0
    for sector in missing:
        while slot < len(sectors) and round(slot * step) in known:
            slot += 1
        sector['azimuth'] = round((slot * step) % 360.0, 1)
        sector['azimuth_source'] = 'estimated'
        known.add(round(sector['azimuth']))
        slot += 1


def fetch_site_layout(
    vendor: str,
    *,
    site_id: str,
    metadata_site_id: str = '',
    site_name: str = '',
    ne_name: str = '',
) -> dict[str, Any]:
    """Sector layout of one site for the RET hologram."""
    vendor = (vendor or 'nokia').strip().lower()
    if vendor not in ('nokia', 'huawei'):
        raise ValueError('Vendor must be nokia or huawei')
    site_id = _as_text(site_id)
    metadata_site_id = _as_text(metadata_site_id)
    site_name = _as_text(site_name)
    if not site_id and not metadata_site_id and not site_name:
        raise ValueError('site_id or site_name is required')

    id_candidates = site_id_candidates(vendor, site_id, metadata_site_id=metadata_site_id)
    warnings: list[str] = []
    cells: list[dict[str, Any]] = []

    conn = connect_metadata()
    try:
        site_row = _lookup_site_row(conn, id_candidates, site_name)
        resolved_name = site_row.get('site_name') or site_name
        for table, technology, site_aliases, name_aliases, band_aliases in TECH_SPECS:
            cells.extend(
                _select_site_cells(
                    conn,
                    table,
                    technology,
                    site_aliases,
                    name_aliases,
                    band_aliases,
                    id_candidates=id_candidates,
                    site_name=resolved_name,
                )
            )
    finally:
        conn.close()

    sectors, sector_warnings = _build_sectors(cells)
    warnings.extend(sector_warnings)
    _fill_missing_azimuths(sectors)

    if not cells:
        warnings.append(
            f'No inventory rows found for site {site_id or site_name or metadata_site_id} '
            'in the PrimeNet metadata database — run a metadata sync to draw the hologram.'
        )

    latitude = site_row.get('latitude')
    longitude = site_row.get('longitude')
    if latitude is None:
        latitude = next((cell['latitude'] for cell in cells if cell['latitude'] is not None), None)
    if longitude is None:
        longitude = next((cell['longitude'] for cell in cells if cell['longitude'] is not None), None)

    heights = [
        sector['height'] for sector in sectors
        if sector.get('height') is not None and sector['height'] > 0
    ]
    return {
        'site': {
            'site_id': site_id,
            'metadata_site_id': site_row.get('site_id') or metadata_site_id or site_id,
            'site_name': site_row.get('site_name') or site_name or ne_name or site_id,
            'ne_name': ne_name,
            'latitude': latitude,
            'longitude': longitude,
            'region': site_row.get('region', ''),
            'vendor': site_row.get('vendor', '') or vendor.title(),
            'site_type': site_row.get('site_type', ''),
            'antenna_height': _median(heights) or DEFAULT_ANTENNA_HEIGHT_M,
            'height_source': 'metadata' if heights else 'default',
        },
        'sectors': sectors,
        'sector_count': len(sectors),
        'cell_count': len(cells),
        'id_candidates': id_candidates,
        'warnings': warnings,
    }
