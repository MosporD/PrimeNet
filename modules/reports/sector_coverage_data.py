"""
Sector coverage matrix — shared by Excel report and Sector Health UI.
"""

from __future__ import annotations

from datetime import datetime, timezone

from db.runtime import connect_metadata, execute_query
from modules.sync.metadata_active_sql import PER_TABLE_ACTIVE_WHERE
from .metadata_helpers import _metadata_table_columns, _sql_ident

EXCLUDED_TECH_BANDS = {
    '2G / DCS1800',
    '2G / GSM 900',
    '2G / GSM900_DCS1800',
    '3G / 3048',
    '3G / 3088',
}

MERGE_TECH_BANDS: dict[str, str] = {
    '5G / N/A': '5G',
    '5G / 100MHz': '5G',
    '3G / 10762': '3G',
    '3G / 10562': '3G',
}

TECH_SPECS = [
    ('cells_2g', '2G', 'site_id', 'site_name', 'frequency_band'),
    ('cells_3g', '3G', 'nodeb_id', 'nodeb_name', 'dl_uarfcn'),
    ('cells_4g_fdd', '4G-FDD', 'enb_id_actual', 'enb_name', 'band'),
    ('cells_4g_tdd', '4G-TDD', 'enb_id_actual', 'enb_name', 'band'),
    ('cells_5g', '5G', 'gnb_id_actual', 'gnb_name', 'bw'),
]

TECH_ORDER = ['2G', '3G', '4G-FDD', '4G-TDD', '5G']
LTE_TECHS = ('4G-FDD', '4G-TDD')
RAT_COUNT_TECHS = ('2G', '3G', '5G')
RAT_HAS_FIELD = {'2G': 'has_2g', '3G': 'has_3g', '5G': 'has_5g'}

# LTE bands excluded from Sector Health totals / pies (different deployment scope).
LTE_HEALTH_EXCLUDED_BAND_LABELS = frozenset({'L35'})


def _meta_conn():
    return connect_metadata()


def _sort_key_tb(tb: str):
    parts = tb.split(' / ', 1)
    tech = parts[0]
    band = parts[1] if len(parts) > 1 else ''
    idx = TECH_ORDER.index(tech) if tech in TECH_ORDER else 99
    return (idx, band)


def _tech_of(tb: str) -> str:
    return str(tb).split(' / ', 1)[0]


def _has_rat(tech_bands: set[str] | list[str], rat: str) -> bool:
    return any(_tech_of(tb) == rat for tb in tech_bands)


def _lte_bands_from(sorted_tb: list[str]) -> list[str]:
    return [tb for tb in sorted_tb if _tech_of(tb) in LTE_TECHS]


def _band_label(tb: str) -> str:
    parts = str(tb).split(' / ', 1)
    return parts[1].strip() if len(parts) > 1 else ''


def _is_lte_health_excluded_band(tb: str) -> bool:
    return _band_label(tb).upper() in {b.upper() for b in LTE_HEALTH_EXCLUDED_BAND_LABELS}


def _lte_bands_for_health(sorted_tb: list[str]) -> list[str]:
    """LTE bands used for Sector Health pies and LTE sector denominator (excludes L35)."""
    return [
        tb for tb in sorted_tb
        if _tech_of(tb) in LTE_TECHS and not _is_lte_health_excluded_band(tb)
    ]


def _pct(count: int, total: int) -> float:
    return round(100 * count / total, 1) if total else 0.0


def _sector_has_lte(lte_coverage: dict) -> bool:
    return any(bool(v) for v in (lte_coverage or {}).values())


def compute_health_summary(sectors: list[dict], lte_bands: list[str]) -> dict:
    """RAT sector counts; LTE layer % per band vs total LTE sectors in scope."""
    total = len(sectors)
    rat_counts = {}
    for rat in RAT_COUNT_TECHS:
        field = RAT_HAS_FIELD[rat]
        n = sum(1 for s in sectors if s.get(field))
        rat_counts[rat] = {'sector_count': n}

    lte_sector_count = sum(1 for s in sectors if s.get('has_lte'))
    lte_layers = []
    for tb in lte_bands:
        n = sum(1 for s in sectors if s.get('lte_coverage', {}).get(tb))
        lte_layers.append({
            'tech_band': tb,
            'sector_count': n,
            'without_count': max(0, lte_sector_count - n),
            'layer_pct': _pct(n, lte_sector_count),
        })

    return {
        'sector_count': total,
        'lte_sector_count': lte_sector_count,
        'rat_counts': rat_counts,
        'lte_layer_pct': lte_layers,
    }


def load_sector_coverage_rows(conn=None) -> tuple[list[dict], list[str]]:
    """
    Returns (sector_list, sorted_tech_bands).
    Each sector dict: site_id, site_name, vendors (set), area, sector, tech_bands (set).
    """
    close_conn = False
    if conn is None:
        conn = _meta_conn()
        close_conn = True

    all_rows: list[dict] = []
    try:
        for table, tech, site_col, name_col, band_col in TECH_SPECS:
            cols = _metadata_table_columns(conn, table)
            if not cols:
                continue
            low = {c.strip().lower(): c for c in cols}

            s_col = low.get(site_col)
            n_col = low.get(name_col) or low.get('site_name')
            b_col = low.get(band_col)
            v_col = low.get('vendor')
            a_col = low.get('area')
            sec_col = low.get('sector')
            az_col = low.get('azimuth')

            active_where = PER_TABLE_ACTIVE_WHERE.get(table, '1=1')

            sql = f"""
                SELECT
                    {_sql_ident(s_col) if s_col else 'NULL'} AS site_id,
                    {_sql_ident(n_col) if n_col else 'NULL'} AS site_name,
                    {_sql_ident(v_col) if v_col else 'NULL'} AS vendor,
                    {_sql_ident(a_col) if a_col else 'NULL'} AS area,
                    {_sql_ident(sec_col) if sec_col else 'NULL'} AS sector,
                    {_sql_ident(az_col) if az_col else 'NULL'} AS azimuth,
                    '{tech}' AS technology,
                    {_sql_ident(b_col) if b_col else 'NULL'} AS frequency_band
                FROM {_sql_ident(table)}
                WHERE {active_where}
            """
            rows = execute_query(conn, sql, ()).fetchall()
            for r in rows:
                rd = dict(r)
                band_raw = str(rd.get('frequency_band') or '').strip()
                if not band_raw:
                    band_raw = 'N/A'
                rd['tech_band'] = f"{tech} / {band_raw}"
                all_rows.append(rd)

        for r in all_rows:
            tb = r['tech_band']
            if tb in MERGE_TECH_BANDS:
                r['tech_band'] = MERGE_TECH_BANDS[tb]

        all_rows = [r for r in all_rows if r['tech_band'] not in EXCLUDED_TECH_BANDS]

        tech_band_set: set[str] = set()
        sectors: dict[str, dict] = {}
        for r in all_rows:
            sid = str(r.get('site_id') or 'Unknown')
            sec = str(r.get('sector') or r.get('azimuth') or 'Unknown')
            key = f"{sid}|{sec}"
            tech_band_set.add(r['tech_band'])
            if key not in sectors:
                sectors[key] = {
                    'site_id': sid,
                    'site_name': r.get('site_name') or '',
                    'vendors': set(),
                    'area': r.get('area') or '',
                    'sector': sec,
                    'tech_bands': set(),
                }
            v = str(r.get('vendor') or '').strip()
            if v:
                sectors[key]['vendors'].add(v)
            sectors[key]['tech_bands'].add(r['tech_band'])

        sorted_tb = sorted(tech_band_set, key=_sort_key_tb)
        sector_list = sorted(sectors.values(), key=lambda s: (s['area'], s['site_id'], s['sector']))
        return sector_list, sorted_tb
    finally:
        if close_conn:
            conn.close()


def _sector_to_payload(sec: dict, lte_bands: list[str], *, include_full_coverage: bool = False) -> dict:
    tb_set = sec['tech_bands']
    lte_coverage = {tb: (tb in tb_set) for tb in lte_bands}
    row = {
        'site_id': sec['site_id'],
        'site_name': sec['site_name'],
        'vendors': sorted(sec['vendors']),
        'area': sec['area'],
        'sector': sec['sector'],
        'has_2g': _has_rat(tb_set, '2G'),
        'has_3g': _has_rat(tb_set, '3G'),
        'has_5g': _has_rat(tb_set, '5G'),
        'has_lte': _sector_has_lte(lte_coverage),
        'lte_coverage': lte_coverage,
    }
    if include_full_coverage:
        row['tech_bands'] = sorted(tb_set, key=_sort_key_tb)
        row['coverage'] = lte_coverage
    return row


def _filter_sectors(sectors: list[dict], *, area: str = '', rat: str = '', search: str = '') -> list[dict]:
    out = sectors
    if area:
        out = [s for s in out if s.get('area') == area]
    rat = (rat or '').strip().upper()
    if rat == '2G':
        out = [s for s in out if s.get('has_2g')]
    elif rat == '3G':
        out = [s for s in out if s.get('has_3g')]
    elif rat == '5G':
        out = [s for s in out if s.get('has_5g')]
    elif rat == 'NO_2G':
        out = [s for s in out if not s.get('has_2g')]
    elif rat == 'NO_3G':
        out = [s for s in out if not s.get('has_3g')]
    elif rat == 'NO_5G':
        out = [s for s in out if not s.get('has_5g')]
    elif rat == 'LTE':
        out = [s for s in out if s.get('has_lte')]
    elif rat == 'NO_LTE':
        out = [s for s in out if not s.get('has_lte')]
    if search:
        q = search.lower()
        out = [
            s for s in out
            if q in str(s.get('site_id', '')).lower()
            or q in str(s.get('site_name', '')).lower()
            or q in str(s.get('sector', '')).lower()
            or q in str(s.get('area', '')).lower()
        ]
    return out


def build_sector_health_bundle() -> tuple[list[str], list[dict]]:
    """Load sectors once: (lte_bands_for_health, lightweight rows for filtering)."""
    sector_list, sorted_tb = load_sector_coverage_rows()
    lte_bands = _lte_bands_for_health(sorted_tb)
    rows = [_sector_to_payload(sec, lte_bands) for sec in sector_list]
    return lte_bands, rows


def build_sector_coverage_payload() -> dict:
    """Full payload (Excel report tooling) — includes all sectors."""
    sector_list, sorted_tb = load_sector_coverage_rows()
    lte_bands = _lte_bands_from(sorted_tb)
    sectors_out = [_sector_to_payload(sec, lte_bands, include_full_coverage=True) for sec in sector_list]

    tb_summary = []
    total = len(sectors_out)
    lte_bands_health = _lte_bands_for_health(sorted_tb)
    lte_total = sum(
        1 for sec in sector_list
        if any(tb in sec['tech_bands'] for tb in lte_bands_health)
    )
    for tb in sorted_tb:
        sector_count = sum(1 for s in sector_list if tb in s['tech_bands'])
        site_ids = {s['site_id'] for s in sector_list if tb in s['tech_bands']}
        entry = {
            'tech_band': tb,
            'sector_count': sector_count,
            'site_count': len(site_ids),
        }
        if tb in lte_bands_health:
            entry['layer_pct'] = _pct(sector_count, lte_total)
        tb_summary.append(entry)

    areas = sorted({s['area'] for s in sector_list if s.get('area')})

    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'tech_bands': sorted_tb,
        'lte_tech_bands': lte_bands,
        'rat_techs': list(RAT_COUNT_TECHS),
        'sectors': sectors_out,
        'sector_count': total,
        'tech_band_summary': tb_summary,
        'areas': areas,
        'health_summary': compute_health_summary(sectors_out, lte_bands_health),
    }


def build_sector_health_api_response(
    *,
    area: str = '',
    rat: str = '',
    search: str = '',
) -> dict:
    """Summary-only API for Sector Health (no sector table)."""
    lte_bands, all_rows = build_sector_health_bundle()
    areas = sorted({s['area'] for s in all_rows if s.get('area')})
    filtered = _filter_sectors(all_rows, area=area, rat=rat, search=search)

    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'lte_tech_bands': lte_bands,
        'rat_techs': list(RAT_COUNT_TECHS),
        'lte_excluded_bands': sorted(LTE_HEALTH_EXCLUDED_BAND_LABELS),
        'sector_count': len(all_rows),
        'filtered_sector_count': len(filtered),
        'areas': areas,
        'health_summary': compute_health_summary(filtered, lte_bands),
    }
