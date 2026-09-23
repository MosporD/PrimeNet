"""
Sector coverage matrix — shared by Excel report and Sector Health UI.
"""

from __future__ import annotations

from datetime import datetime, timezone

from db.runtime import connect_metadata, execute_query
from modules.sync.metadata_active_sql import (
    LEGACY_CELLS_ACTIVITY_CASE_SQL,
    PER_TABLE_ACTIVE_WHERE,
)
from .metadata_helpers import (
    _metadata_table_columns,
    _pick_col,
    _sql_ident,
    resolve_site_name,
)

# Sparse / non-deployed layers dropped from the coverage matrix.
# Do not exclude vendor label variants of live 2G bands (Nokia uses "GSM 900"
# with a space; Huawei uses "GSM900") — that zeroed Nokia 2G sector counts.
EXCLUDED_TECH_BANDS = {
    '3G / 3048',
    '3G / 3088',
}

MERGE_TECH_BANDS: dict[str, str] = {
    '5G / N/A': '5G',
    '5G / 100MHz': '5G',
    '3G / 10762': '3G',
    '3G / 10562': '3G',
    # Nokia metadata label → same column as Huawei GSM900
    '2G / GSM 900': '2G / GSM900',
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

# Canonical LTE layer categories for sector completeness checks (report column).
LTE_LAYER_CATEGORIES = ('L18', 'L18+', 'L9', 'L21')
_LTE_LAYER_CATEGORY_BANDS: dict[str, frozenset[str]] = {
    'L18': frozenset({'L18'}),
    'L18+': frozenset({'L18NEW', 'L18+', 'L18PLUS'}),
    'L9': frozenset({'L9'}),
    'L21': frozenset({'L21'}),
}

VENDOR_LABEL_THIN = 'Huawei / Nokia Thin'
VENDOR_LABEL_TDD_THIN = 'Huawei TDD / Nokia Thin'
VENDOR_LABEL_TDD_NOKIA = 'Huawei TDD / Nokia'
THIN_LAYER_LABELS = frozenset({VENDOR_LABEL_THIN, VENDOR_LABEL_TDD_THIN})


def _normalize_vendor_name(raw) -> str:
    v = str(raw or '').strip()
    low = v.lower()
    if low == 'huawei':
        return 'Huawei'
    if low == 'nokia':
        return 'Nokia'
    return v


def classify_sector_vendor_label(
    tech_band_vendors: dict[str, set[str]] | None,
    all_vendors: set[str] | list[str] | None = None,
) -> str:
    """
    Sector Vendor column label.

    - Huawei TDD / Nokia Thin: FDD split across vendors AND Huawei TDD present.
    - Huawei / Nokia Thin: FDD cells on the same sector span both vendors
      (typical: L18+ Nokia, L18/L9/L21 Huawei), no Huawei TDD.
    - Huawei TDD / Nokia: Huawei TDD present with Nokia, and FDD is not split.
    - Otherwise: sorted unique vendors joined with ' / '.
    """
    tb_vendors = tech_band_vendors or {}
    fdd_vendors: set[str] = set()
    has_huawei_tdd = False
    has_nokia = False
    for tb, vendors in tb_vendors.items():
        norm = {_normalize_vendor_name(v) for v in (vendors or ()) if str(v or '').strip()}
        if 'Nokia' in norm:
            has_nokia = True
        tech = _tech_of(tb)
        if tech == '4G-FDD':
            fdd_vendors |= norm
        elif tech == '4G-TDD' and 'Huawei' in norm:
            has_huawei_tdd = True

    fdd_thin = 'Huawei' in fdd_vendors and 'Nokia' in fdd_vendors
    if fdd_thin and has_huawei_tdd:
        return VENDOR_LABEL_TDD_THIN
    if fdd_thin:
        return VENDOR_LABEL_THIN
    if has_huawei_tdd and has_nokia:
        return VENDOR_LABEL_TDD_NOKIA

    names = {
        _normalize_vendor_name(v)
        for v in (all_vendors or ())
        if str(v or '').strip()
    }
    if not names:
        for vendors in tb_vendors.values():
            for v in vendors or ():
                if str(v or '').strip():
                    names.add(_normalize_vendor_name(v))
    return ' / '.join(sorted(names))


def is_thin_layer_sector(tech_band_vendors: dict[str, set[str]] | None) -> bool:
    """True when FDD layers on the sector are split across Huawei and Nokia."""
    return classify_sector_vendor_label(tech_band_vendors) in THIN_LAYER_LABELS



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


def _lte_band_labels_in_sector(tech_bands: set[str] | list[str]) -> set[str]:
    """Uppercase LTE band labels present on a sector (excludes L35)."""
    labels: set[str] = set()
    for tb in tech_bands:
        if _tech_of(tb) in LTE_TECHS and not _is_lte_health_excluded_band(tb):
            label = _band_label(tb).strip().upper()
            if label:
                labels.add(label)
    return labels


def sector_has_lte_layer_category(tech_bands: set[str] | list[str], category: str) -> bool:
    """True when the sector has the given canonical LTE layer (L18, L18+, L9, L21)."""
    labels = _lte_band_labels_in_sector(tech_bands)
    aliases = _LTE_LAYER_CATEGORY_BANDS.get(category)
    if not aliases:
        return False
    return bool(labels & aliases)


def missing_lte_layer_categories(tech_bands: set[str] | list[str]) -> list[str]:
    """Missing canonical LTE layers for a sector, in display order."""
    return [
        category for category in LTE_LAYER_CATEGORIES
        if not sector_has_lte_layer_category(tech_bands, category)
    ]


def format_missing_lte_layers(tech_bands: set[str] | list[str]) -> str:
    """Comma-separated missing LTE layer categories, or empty when complete."""
    missing = missing_lte_layer_categories(tech_bands)
    return ', '.join(missing)


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


def load_sector_coverage_rows(conn=None, *, active_only: bool = True) -> tuple[list[dict], list[str]]:
    """
    Returns (sector_list, sorted_tech_bands).
    Each sector dict: site_id, site_name, vendors (set), vendor_label, area, sector,
    tech_bands (set), tech_band_status, tech_band_vendors, is_thin_layer.

    When active_only is True (default), only on-air cells per PER_TABLE_ACTIVE_WHERE are included.
    When False, every configured cell row is included; tech_band_status marks on-air vs off-air.
    """
    if conn is None:
        from core.radio.section_runner import cached_build

        return cached_build(
            f"sector.rows|v4|{int(bool(active_only))}",
            lambda: _load_sector_coverage_rows_uncached(active_only=active_only),
            copy=_clone_sector_bundle,
        )
    return _load_sector_coverage_rows_uncached(conn, active_only=active_only)


def _clone_sector_bundle(payload: tuple[list[dict], list[str]]) -> tuple[list[dict], list[str]]:
    sectors, bands = payload
    out: list[dict] = []
    for sector in sectors:
        item = dict(sector)
        item["vendors"] = set(sector.get("vendors") or [])
        item["tech_bands"] = set(sector.get("tech_bands") or [])
        item["tech_band_status"] = dict(sector.get("tech_band_status") or {})
        item["tech_band_vendors"] = {
            tb: set(vs or [])
            for tb, vs in (sector.get("tech_band_vendors") or {}).items()
        }
        out.append(item)
    return out, list(bands)


def _normalize_activity_status(raw) -> str:
    status = str(raw or '').strip()
    return 'Active' if status == 'Active' else 'Inactive'


def _merge_layer_status(prev: str | None, new: str) -> str:
    """If any cell on the layer is on-air, the sector layer counts as Active."""
    if prev == 'Active' or new == 'Active':
        return 'Active'
    return 'Inactive'


def _load_sector_coverage_rows_uncached(conn=None, *, active_only: bool = True) -> tuple[list[dict], list[str]]:
    """
    Returns (sector_list, sorted_tech_bands).
    Each sector dict: site_id, site_name, vendors (set), vendor_label, area, sector,
    tech_bands (set), tech_band_status, tech_band_vendors, is_thin_layer.

    When active_only is True (default), only on-air cells per PER_TABLE_ACTIVE_WHERE are included.
    When False, every configured cell row is included; tech_band_status marks on-air vs off-air.
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
            cell_col = _pick_col(
                ['cell_name', 'cell name', 'wcel name', 'lncel name', 'nrcel name', 'bts name'],
                low,
            )
            b_col = low.get(band_col)
            v_col = low.get('vendor')
            a_col = low.get('area')
            sec_col = low.get('sector')
            az_col = low.get('azimuth')

            active_where = (
                PER_TABLE_ACTIVE_WHERE.get(table, '1=1') if active_only else '1=1'
            )
            activity_case = LEGACY_CELLS_ACTIVITY_CASE_SQL.get(table)
            activity_select = (
                f"({activity_case}) AS activity_status"
                if activity_case
                else "'Active' AS activity_status"
            )

            sql = f"""
                SELECT
                    {_sql_ident(s_col) if s_col else 'NULL'} AS site_id,
                    {_sql_ident(n_col) if n_col else 'NULL'} AS site_name,
                    {_sql_ident(cell_col) if cell_col else 'NULL'} AS cell_name,
                    {_sql_ident(v_col) if v_col else 'NULL'} AS vendor,
                    {_sql_ident(a_col) if a_col else 'NULL'} AS area,
                    {_sql_ident(sec_col) if sec_col else 'NULL'} AS sector,
                    {_sql_ident(az_col) if az_col else 'NULL'} AS azimuth,
                    '{tech}' AS technology,
                    {_sql_ident(b_col) if b_col else 'NULL'} AS frequency_band,
                    {activity_select}
                FROM {_sql_ident(table)}
                WHERE {active_where}
            """
            rows = execute_query(conn, sql, ()).fetchall()
            for r in rows:
                rd = dict(r)
                rd['site_name'] = resolve_site_name(rd.get('site_name'), cell_name=rd.get('cell_name'))
                band_raw = str(rd.get('frequency_band') or '').strip()
                if not band_raw:
                    band_raw = 'N/A'
                rd['tech_band'] = f"{tech} / {band_raw}"
                rd['activity_status'] = _normalize_activity_status(rd.get('activity_status'))
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
            tb = r['tech_band']
            tech_band_set.add(tb)
            if key not in sectors:
                sectors[key] = {
                    'site_id': sid,
                    'site_name': r.get('site_name') or '',
                    'vendors': set(),
                    'area': r.get('area') or '',
                    'sector': sec,
                    'tech_bands': set(),
                    'tech_band_status': {},
                    'tech_band_vendors': {},
                }
            else:
                sectors[key]['site_name'] = resolve_site_name(
                    sectors[key]['site_name'],
                    r.get('site_name'),
                    cell_name=r.get('cell_name'),
                )
            v = _normalize_vendor_name(r.get('vendor'))
            if v:
                sectors[key]['vendors'].add(v)
                sectors[key]['tech_band_vendors'].setdefault(tb, set()).add(v)
            sectors[key]['tech_bands'].add(tb)
            sectors[key]['tech_band_status'][tb] = _merge_layer_status(
                sectors[key]['tech_band_status'].get(tb),
                r.get('activity_status') or 'Inactive',
            )

        for sec in sectors.values():
            tb_vendors = sec.get('tech_band_vendors') or {}
            sec['vendor_label'] = classify_sector_vendor_label(tb_vendors, sec.get('vendors'))
            sec['is_thin_layer'] = sec['vendor_label'] in THIN_LAYER_LABELS

        sorted_tb = sorted(tech_band_set, key=_sort_key_tb)
        sector_list = sorted(sectors.values(), key=lambda s: (s['area'], s['site_id'], s['sector']))
        return sector_list, sorted_tb
    finally:
        if close_conn:
            conn.close()


def _sector_to_payload(sec: dict, lte_bands: list[str], *, include_full_coverage: bool = False) -> dict:
    tb_set = sec['tech_bands']
    lte_coverage = {tb: (tb in tb_set) for tb in lte_bands}
    vendor_label = sec.get('vendor_label') or classify_sector_vendor_label(
        sec.get('tech_band_vendors'),
        sec.get('vendors'),
    )
    row = {
        'site_id': sec['site_id'],
        'site_name': sec['site_name'],
        'vendors': sorted(sec['vendors']),
        'vendor_label': vendor_label,
        'is_thin_layer': bool(sec.get('is_thin_layer') or vendor_label in THIN_LAYER_LABELS),
        'area': sec['area'],
        'sector': sec['sector'],
        'has_2g': _has_rat(tb_set, '2G'),
        'has_3g': _has_rat(tb_set, '3G'),
        'has_5g': _has_rat(tb_set, '5G'),
        'has_lte': _sector_has_lte(lte_coverage),
        'lte_coverage': lte_coverage,
        'missing_lte_layers': missing_lte_layer_categories(tb_set),
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


def build_sector_health_bundle(*, active_only: bool = True) -> tuple[list[str], list[dict]]:
    """Load sectors once: (lte_bands_for_health, lightweight rows for filtering)."""
    from core.radio.section_runner import cached_build

    def _run():
        sector_list, sorted_tb = load_sector_coverage_rows(active_only=active_only)
        lte_bands = _lte_bands_for_health(sorted_tb)
        rows = [_sector_to_payload(sec, lte_bands) for sec in sector_list]
        return lte_bands, rows

    def _copy(payload):
        bands, rows = payload
        return list(bands), [dict(row) for row in rows]

    return cached_build(f"sector.health_bundle|{int(bool(active_only))}", _run, copy=_copy)


def build_sector_coverage_payload(*, active_only: bool = True) -> dict:
    """Full payload (Excel report tooling) — includes all sectors."""
    from core.radio.section_runner import cached_build

    def _run():
        sector_list, sorted_tb = load_sector_coverage_rows(active_only=active_only)
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

    def _copy(payload):
        out = dict(payload)
        if isinstance(out.get('sectors'), list):
            out['sectors'] = [dict(row) for row in out['sectors']]
        return out

    return cached_build(f"sector.coverage_payload|{int(bool(active_only))}", _run, copy=_copy)


def build_sector_health_api_response(
    *,
    area: str = '',
    rat: str = '',
    search: str = '',
    active_only: bool = True,
) -> dict:
    """Summary-only API for Sector Health (no sector table)."""
    lte_bands, all_rows = build_sector_health_bundle(active_only=active_only)
    areas = sorted({s['area'] for s in all_rows if s.get('area')})
    filtered = _filter_sectors(all_rows, area=area, rat=rat, search=search)

    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'active_only': active_only,
        'lte_tech_bands': lte_bands,
        'rat_techs': list(RAT_COUNT_TECHS),
        'lte_excluded_bands': sorted(LTE_HEALTH_EXCLUDED_BAND_LABELS),
        'sector_count': len(all_rows),
        'filtered_sector_count': len(filtered),
        'areas': areas,
        'health_summary': compute_health_summary(filtered, lte_bands),
    }
