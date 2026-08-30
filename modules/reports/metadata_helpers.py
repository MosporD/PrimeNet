"""
Shared SQLite helpers for metadata inventory UNION queries (reports + conflict map).
"""

import re

from db.runtime import execute_query

_CELL_SUFFIX_RE = re.compile(r'[-_][A-Za-z]\d*$')


def _sql_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _metadata_table_columns(conn, table: str) -> list[str]:
    rows = execute_query(conn, f'PRAGMA table_info({_sql_ident(table)})').fetchall()
    return [r[1] for r in rows] if rows else []


def _pick_col(candidates: list[str], low_to_real: dict[str, str]) -> str | None:
    for c in candidates:
        real = low_to_real.get(str(c).strip().lower())
        if real:
            return real
    return None


def site_name_from_cell_name(cell_name: str | None) -> str:
    """Strip trailing sector/cell suffix (e.g. -A2, _B1) to derive the site name."""
    raw = str(cell_name or '').strip()
    if not raw or raw == '?':
        return ''
    return _CELL_SUFFIX_RE.sub('', raw).strip()


def resolve_site_name(*site_name_candidates: str | None, cell_name: str | None = None) -> str:
    """Prefer the first real configured site name; otherwise derive from cell_name."""
    for candidate in site_name_candidates:
        name = str(candidate or '').strip()
        if name and name != '?':
            return name
    return site_name_from_cell_name(cell_name)


def _metadata_inventory_union_sql(conn) -> str:
    """
    Build a normalized UNION over per-technology metadata tables.
    We do not rely on the legacy `cells` table because recent loaders may keep
    data only in canonical tables (`cells_2g`, `cells_3g`, ...).
    """
    specs = [
        ('cells_2g', '2G', ['site_id', 'bcf id', 'bts id']),
        ('cells_3g', '3G', ['site_id', 'nodeb_id']),
        ('cells_4g_fdd', '4G-FDD', ['site_id', 'enb_id_actual', 'enodeb id']),
        ('cells_4g_tdd', '4G-TDD', ['site_id', 'enb_id_actual', 'enodeb id']),
        ('cells_5g', '5G', ['site_id', 'gnb_id_actual', 'gnb id']),
    ]

    parts: list[str] = []
    for table, tech, site_aliases in specs:
        col_names = _metadata_table_columns(conn, table)
        if not col_names:
            continue
        low_to_real = {str(c).strip().lower(): c for c in col_names}
        site_col = _pick_col(site_aliases, low_to_real)
        cell_col = _pick_col(
            ['cell_name', 'cell name', 'wcel name', 'lncel name', 'nrcel name', 'bts name'],
            low_to_real,
        )
        vendor_col = _pick_col(['vendor'], low_to_real)
        band_col = _pick_col(
            [
                'frequency_band', 'band',
                'earfcn', 'nrarfcn', 'arfcn',
                'uarfcn', 'uarfcn_dl', 'uarfcn downlink', 'dl_uarfcn', 'downlink_uarfcn',
                'uarfcn_downlink', 'downlink uarfcn', 'channel', 'channel_number',
            ],
            low_to_real,
        )
        az_col = _pick_col(['azimuth', 'azimuth_deg', 'azimuth degree'], low_to_real)
        pci_col = _pick_col(['pci', 'psc', 'bcch'], low_to_real)
        area_col = _pick_col(['area', 'region', 'market'], low_to_real)
        et_col = _pick_col(['electrical_tilt', 'electrical tilt', 'e_tilt'], low_to_real)
        mt_col = _pick_col(['mechanical_tilt', 'mechanical tilt', 'm_tilt'], low_to_real)
        status_col = _pick_col(['status', 'activity_status'], low_to_real)
        cluster_col = _pick_col(['cluster'], low_to_real)
        lat_col = _pick_col(['lat', 'latitude'], low_to_real)
        lng_col = _pick_col(['long', 'longitude', 'lng', 'lon'], low_to_real)
        rnc_col = _pick_col(['rnc_name', 'rnc'], low_to_real)
        bsc_col = _pick_col(['bsc_name', 'bsc'], low_to_real)

        site_expr = f'CAST({_sql_ident(site_col)} AS TEXT)' if site_col else 'NULL'
        cell_expr = _sql_ident(cell_col) if cell_col else 'NULL'
        vendor_expr = _sql_ident(vendor_col) if vendor_col else 'NULL'
        band_expr = _sql_ident(band_col) if band_col else 'NULL'
        az_expr = _sql_ident(az_col) if az_col else 'NULL'
        pci_expr = _sql_ident(pci_col) if pci_col else 'NULL'
        area_expr = _sql_ident(area_col) if area_col else 'NULL'
        et_expr = _sql_ident(et_col) if et_col else 'NULL'
        mt_expr = _sql_ident(mt_col) if mt_col else 'NULL'
        status_expr = _sql_ident(status_col) if status_col else "''"
        cluster_expr = _sql_ident(cluster_col) if cluster_col else 'NULL'
        lat_expr = _sql_ident(lat_col) if lat_col else 'NULL'
        lng_expr = _sql_ident(lng_col) if lng_col else 'NULL'
        rnc_expr = _sql_ident(rnc_col) if rnc_col else 'NULL'
        bsc_expr = _sql_ident(bsc_col) if bsc_col else 'NULL'
        controller_expr = f'COALESCE({rnc_expr}, {bsc_expr})'

        parts.append(
            f"""
            SELECT
                {site_expr} AS site_id,
                {cell_expr} AS cell_name,
                '{tech}' AS technology,
                {vendor_expr} AS vendor,
                {band_expr} AS frequency_band,
                {az_expr} AS azimuth,
                {pci_expr} AS pci,
                {area_expr} AS area,
                {et_expr} AS electrical_tilt,
                {mt_expr} AS mechanical_tilt,
                {status_expr} AS status,
                {cluster_expr} AS cluster,
                {lat_expr} AS latitude,
                {lng_expr} AS longitude,
                {controller_expr} AS controller
            FROM {_sql_ident(table)}
            """
        )

    if not parts:
        return (
            "SELECT NULL AS site_id, NULL AS cell_name, NULL AS technology, NULL AS vendor, "
            "NULL AS frequency_band, NULL AS azimuth, NULL AS pci, NULL AS area, NULL AS electrical_tilt, "
            "NULL AS mechanical_tilt, NULL AS status, NULL AS cluster, NULL AS latitude, "
            "NULL AS longitude, NULL AS controller WHERE 1=0"
        )
    return "\nUNION ALL\n".join(parts)
