"""Map RMOD active*CellsList tokens → band labels via PrimeNet metadata."""

from __future__ import annotations

import re
from typing import Any

# 3G UARFCN → band label (Zain Jordan: both main carriers are Band I / 2100).
_UARFCN_BAND: dict[str, str] = {
    '10562': 'U2100',
    '10762': 'U2100',
    '3048': 'U900',
}

_CELL_TOKEN_RE = re.compile(
    r'(?:^|[,;|\s/])(?:(?:LNCEL|WCEL|NRCELL|BTS|GNCEL|NRBTS)[-_])?(\d+)\b',
    flags=re.IGNORECASE,
)


def parse_cell_tokens(value: Any) -> list[str]:
    """Extract numeric cell / local-cell ids from an active*CellsList value."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        tokens: list[str] = []
        for item in value:
            tokens.extend(parse_cell_tokens(item))
        return _dedupe(tokens)
    if isinstance(value, dict):
        for key in ('value', 'values', 'list', 'items', 'cellList', 'cells', 'dn', 'distName'):
            if key in value:
                return parse_cell_tokens(value[key])
        return []

    text = str(value).strip()
    if not text:
        return []
    # Prefer structured MO tails / bare integers.
    found = [m.group(1) for m in _CELL_TOKEN_RE.finditer(',' + text)]
    if found:
        return _dedupe(found)
    # Fallback: split on common separators.
    parts = [p.strip() for p in re.split(r'[,;|]', text) if p.strip()]
    out: list[str] = []
    for part in parts:
        m = re.search(r'(\d+)\s*$', part)
        if m:
            out.append(m.group(1))
    return _dedupe(out)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        token = str(item).strip()
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def uarfcn_to_band(uarfcn: Any) -> str:
    raw = str(uarfcn or '').strip()
    if not raw:
        return ''
    if raw in _UARFCN_BAND:
        return _UARFCN_BAND[raw]
    # Unknown channel — keep the UARFCN itself so the Sankey stays informative.
    return f'U{raw}'


def normalize_lte_band(band: Any) -> str:
    text = str(band or '').strip()
    return text


class BandIndex:
    """
    Lookup tables for (site, cell_token) → band label.

    LTE: ``cells_4g_fdd.band`` keyed by (enb/site, cell_id).
    3G: ``cells_3g.dl_uarfcn`` keyed by (nodeb/site, cell_id) and by
    (site, local suffix) when CI is ``{site}{local}`` (e.g. 1031 → local 1).
    Also keeps per-site unique 3G bands for fallback when WCEL local ids
    do not match metadata CI (common on RMOD lists).
    """

    def __init__(self) -> None:
        self.lte_by_site_cell: dict[tuple[str, str], str] = {}
        self.wcdma_by_site_cell: dict[tuple[str, str], str] = {}
        self.wcdma_by_site_local: dict[tuple[str, str], str] = {}
        self.wcdma_site_bands: dict[str, set[str]] = {}

    def lte_band(self, site_keys: list[str], cell_token: str) -> str:
        for site in site_keys:
            hit = self.lte_by_site_cell.get((site, cell_token))
            if hit:
                return hit
        return ''

    def wcdma_band(self, site_keys: list[str], cell_token: str) -> str:
        for site in site_keys:
            hit = self.wcdma_by_site_cell.get((site, cell_token))
            if hit:
                return hit
            hit = self.wcdma_by_site_local.get((site, cell_token))
            if hit:
                return hit
        # Site-level fallback: if the site only has one 3G band, use it.
        for site in site_keys:
            bands = self.wcdma_site_bands.get(site) or set()
            if len(bands) == 1:
                return next(iter(bands))
        return ''


def load_band_index() -> BandIndex:
    """Build band index from the local metadata SQLite (no NetAct)."""
    from db.runtime import connect_metadata

    index = BandIndex()
    conn = connect_metadata()
    try:
        for row in conn.execute(
            """
            SELECT TRIM(CAST(COALESCE(enb_id_actual, '') AS TEXT)) AS site_id,
                   TRIM(CAST(COALESCE(cell_id, '') AS TEXT)) AS cell_id,
                   TRIM(CAST(COALESCE(band, '') AS TEXT)) AS band
            FROM cells_4g_fdd
            WHERE LOWER(COALESCE(vendor, '')) LIKE '%nokia%'
              AND TRIM(CAST(COALESCE(cell_id, '') AS TEXT)) != ''
              AND TRIM(CAST(COALESCE(band, '') AS TEXT)) != ''
            """
        ):
            site = str(row['site_id'] or '').strip()
            cell = str(row['cell_id'] or '').strip()
            band = normalize_lte_band(row['band'])
            if not site or not cell or not band:
                continue
            index.lte_by_site_cell[(site, cell)] = band

        for row in conn.execute(
            """
            SELECT TRIM(CAST(COALESCE(nodeb_id, '') AS TEXT)) AS site_id,
                   TRIM(CAST(COALESCE(cell_id, '') AS TEXT)) AS cell_id,
                   TRIM(CAST(COALESCE(dl_uarfcn, '') AS TEXT)) AS uarfcn
            FROM cells_3g
            WHERE LOWER(COALESCE(vendor, '')) LIKE '%nokia%'
              AND TRIM(CAST(COALESCE(cell_id, '') AS TEXT)) != ''
              AND TRIM(CAST(COALESCE(dl_uarfcn, '') AS TEXT)) != ''
            """
        ):
            site = str(row['site_id'] or '').strip()
            cell = str(row['cell_id'] or '').strip()
            label = uarfcn_to_band(row['uarfcn'])
            if not site or not cell or not label:
                continue
            index.wcdma_by_site_cell[(site, cell)] = label
            index.wcdma_site_bands.setdefault(site, set()).add(label)
            if cell.startswith(site) and len(cell) > len(site):
                local = cell[len(site):]
                if local:
                    index.wcdma_by_site_local[(site, local)] = label
    finally:
        conn.close()
    return index


def site_keys_for_row(row: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for field in ('metadata_site_id', 'site_id'):
        token = str(row.get(field) or '').strip()
        if token and token not in keys:
            keys.append(token)
    return keys


def band_techs_for_rmod(
    row: dict[str, Any],
    *,
    band_index: BandIndex | None = None,
) -> list[str]:
    """
    Technologies for one RMOD, with 3G/4G expanded to band labels.

    Examples: ``4G-L18``, ``4G-L21``, ``3G-U2100``. Unresolved stays ``3G``/``4G``.
    2G / 5G stay coarse. Empty lists → ``Unused``.
    """
    from modules.rru_inventory.logic import (
        TECH_LIST_PARAMS,
        UNUSED_TECH,
        is_cells_list_empty,
    )

    index = band_index
    sites = site_keys_for_row(row)
    techs: list[str] = []
    seen: set[str] = set()

    def add(label: str) -> None:
        if label and label not in seen:
            seen.add(label)
            techs.append(label)

    for param, tech in TECH_LIST_PARAMS:
        raw = row.get(param)
        if raw is None:
            # Snapshot store uses snake_case aliases.
            aliases = {
                'activeGsmCellsList': 'active_gsm',
                'activeWcdmaCellsList': 'active_wcdma',
                'activeLteCellsList': 'active_lte',
                'activeNrCellsList': 'active_nr',
            }
            raw = row.get(aliases.get(param, ''))
        if is_cells_list_empty(raw):
            continue

        if tech == '2G':
            add('2G')
            continue
        if tech == '5G':
            add('5G')
            continue

        if index is None:
            add(tech)
            continue

        tokens = parse_cell_tokens(raw)
        resolved: list[str] = []
        if tech == '4G':
            for token in tokens:
                band = index.lte_band(sites, token)
                resolved.append(f'4G-{band}' if band else '4G')
            if not resolved:
                resolved = ['4G']
        elif tech == '3G':
            for token in tokens:
                band = index.wcdma_band(sites, token)
                resolved.append(f'3G-{band}' if band else '3G')
            if not resolved:
                # Non-empty list but no parseable tokens — still try site fallback.
                band = index.wcdma_band(sites, '')
                resolved = [f'3G-{band}' if band else '3G']
        else:
            resolved = [tech]

        for label in resolved:
            add(label)

    return techs or [UNUSED_TECH]
