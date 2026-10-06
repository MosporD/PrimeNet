"""
PCI / PSC / BCCH directional conflict logic: co-channel (and 2G adjacent) reuse,
distance, azimuth vs. inter-site bearing.

Tune thresholds in CONFLICT_STRICTNESS_PROFILES below.
"""

from __future__ import annotations

import io
import math
import re
from datetime import datetime, timedelta
from itertools import combinations

from db.runtime import execute_query

from modules.reports.metadata_helpers import (
    _metadata_inventory_union_sql,
    _metadata_table_columns,
    _pick_col,
    _sql_ident,
)

CONFLICT_CACHE_TTL = timedelta(days=1)
_CONFLICT_CACHE: dict[str, dict] = {}

# ── Strictness (distance + azimuth vs. inter-site bearing) ─────────────────────
#
# Pair candidates are built once up to max(dist_max_km) across all profiles, then
# each profile filters by its own dist_max_km and recomputes High / Medium / Low.
#
# Directional profiles (azimuth matters):
#   - d_a / d_b = |azimuth − geographic bearing toward the other site| (wrapped 0–180°).
#   - "Aligned" for a side means d ≤ az_near_deg.
#   - High: both sides aligned AND distance_km ≤ dist_high_km.
#   - Medium: both aligned OR exactly one side aligned (and not High).
#   - Low: neither side aligned.
#
# Distance-only profile (`distance_only: True`):
#   - Azimuth is ignored.
#   - High: distance_km ≤ dist_high_km.
#   - Medium: between dist_high_km and midpoint(dist_high_km, dist_max_km).
#   - Low: remainder within dist_max_km.
CONFLICT_STRICTNESS_PROFILES: dict[str, dict[str, object]] = {
    'strict': {
        'label': 'Strict',
        'hint': 'Smallest search radius; tightest match between antenna azimuth and bearing to the neighbor.',
        'dist_max_km': 4.0,
        'dist_high_km': 2.5,
        'az_near_deg': 35.0,
    },
    'standard': {
        'label': 'Standard',
        'hint': 'Original default thresholds (6 km cap, 4 km for High when both aimed, ±50°).',
        'dist_max_km': 6.0,
        'dist_high_km': 4.0,
        'az_near_deg': 50.0,
    },
    'moderate': {
        'label': 'Moderate',
        'hint': 'Between Standard and Relaxed: more pairs qualify, looser bearing window.',
        'dist_max_km': 8.0,
        'dist_high_km': 5.0,
        'az_near_deg': 58.0,
    },
    'relaxed': {
        'label': 'Relaxed',
        'hint': 'Largest radius and loosest bearing match — exploratory / catch-all screening.',
        'dist_max_km': 10.0,
        'dist_high_km': 7.0,
        'az_near_deg': 65.0,
    },
    'distance': {
        'label': 'Distance only',
        'hint': 'Ignore antenna azimuth — draw and score pairs by inter-site distance only (6 km cap, High ≤4 km).',
        'dist_max_km': 6.0,
        'dist_high_km': 4.0,
        'az_near_deg': 0.0,
        'distance_only': True,
    },
}

DEFAULT_CONFLICT_STRICTNESS = 'standard'

# 2G conflict pairing modes (selectable in UI / report).
CONFLICT_MODES = ('co', 'adjacent', 'both')
DEFAULT_CONFLICT_MODE = 'both'
CONFLICT_MODE_LABELS = {
    'co': 'Co-channel',
    'adjacent': 'Adjacent (±1)',
    'both': 'Co-channel + Adjacent',
}


def normalize_conflict_tech(technology: str = '4G') -> str:
    t = str(technology or '4G').strip().upper()
    return t if t in ('2G', '3G', '4G', '5G') else '4G'


def normalize_conflict_mode(mode: str | None, technology: str | None = None) -> str:
    """Return co | adjacent | both. Non-2G always co (adjacent BCCH is GSM-only)."""
    tech = normalize_conflict_tech(technology or '4G')
    if tech != '2G':
        return 'co'
    m = str(mode or '').strip().lower()
    if m in CONFLICT_MODES:
        return m
    return DEFAULT_CONFLICT_MODE


def conflict_mode_options_public(technology: str | None = None) -> list[dict[str, object]]:
    tech = normalize_conflict_tech(technology or '4G')
    if tech != '2G':
        return [{'id': 'co', 'label': CONFLICT_MODE_LABELS['co']}]
    return [{'id': k, 'label': CONFLICT_MODE_LABELS[k]} for k in CONFLICT_MODES]


def strictness_profiles_for_tech(technology: str | None = None) -> dict[str, dict[str, object]]:
    """Same distance/azimuth profiles for all RATs (including 2G)."""
    return CONFLICT_STRICTNESS_PROFILES


def conflict_build_max_km(technology: str | None = None) -> float:
    profiles = strictness_profiles_for_tech(technology)
    return max(float(p['dist_max_km']) for p in profiles.values())


def normalize_strictness(slug: str | None, technology: str | None = None) -> str:
    profiles = strictness_profiles_for_tech(technology)
    k = str(slug or '').strip().lower()
    if k in profiles:
        return k
    return DEFAULT_CONFLICT_STRICTNESS


def filter_conflict_rows(
    rows: list[dict],
    *,
    risk: str = 'all',
    area_values: list[str] | None = None,
    band: str = 'all',
    pci: str | None = None,
    conflict_mode: str | None = None,
    technology: str | None = None,
) -> list[dict]:
    """Apply UI filters to strictness-scored conflict pair rows."""
    area_values = area_values or []
    area_set = {v for v in area_values if str(v).strip() and str(v).lower() != 'all'}
    band_norm = str(band or 'all').strip()
    risk_norm = str(risk or 'all').strip().lower()
    pci_norm = str(pci).strip() if pci not in (None, '') else ''
    mode = normalize_conflict_mode(conflict_mode, technology)

    out: list[dict] = []
    for r in rows:
        ctype = str(r.get('conflict_type') or 'co').strip().lower()
        if mode == 'co' and ctype != 'co':
            continue
        if mode == 'adjacent' and ctype != 'adjacent':
            continue
        if risk_norm in ('high', 'medium', 'low') and str(r.get('risk', '')).lower() != risk_norm:
            continue
        if area_set:
            area_a = str(r.get('a_area') or '')
            area_b = str(r.get('b_area') or '')
            if area_a not in area_set and area_b not in area_set:
                continue
        if band_norm.lower() != 'all':
            band_a = str(r.get('a_band') or '')
            band_b = str(r.get('b_band') or '')
            if band_norm not in (band_a, band_b):
                continue
        if pci_norm:
            pci_val = str(r.get('pci') or '').strip()
            if ctype == 'adjacent':
                parts = [p.strip() for p in pci_val.split('/') if p.strip()]
                if pci_norm not in parts and pci_norm != pci_val:
                    continue
            elif pci_val != pci_norm:
                continue
        out.append(dict(r))
    return out


def _conflict_profile_thresholds(slug: str, technology: str | None = None) -> dict[str, float | bool]:
    profiles = strictness_profiles_for_tech(technology)
    p = profiles[normalize_strictness(slug, technology)]
    return {
        'dist_max_km': float(p['dist_max_km']),
        'dist_high_km': float(p['dist_high_km']),
        'az_near_deg': float(p.get('az_near_deg') or 0.0),
        'distance_only': bool(p.get('distance_only')),
    }


def _conflict_risk_for_metrics(
    dist_km: float,
    d_a: float | None,
    d_b: float | None,
    thresholds: dict[str, float | bool],
) -> str:
    dh = float(thresholds['dist_high_km'])
    if thresholds.get('distance_only'):
        # Azimuth ignored — tier purely by distance within the profile radius.
        if dist_km <= dh:
            return 'High'
        dmax = float(thresholds['dist_max_km'])
        mid = (dh + dmax) / 2.0
        if dist_km <= mid:
            return 'Medium'
        return 'Low'

    az = float(thresholds['az_near_deg'])
    both_aligned = d_a is not None and d_b is not None and d_a <= az and d_b <= az
    one_aligned = (d_a is not None and d_a <= az) or (d_b is not None and d_b <= az)
    if both_aligned and dist_km <= dh:
        return 'High'
    if both_aligned or one_aligned:
        return 'Medium'
    return 'Low'


def conflict_strictness_profiles_public(technology: str | None = None) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for key, p in strictness_profiles_for_tech(technology).items():
        distance_only = bool(p.get('distance_only'))
        out.append({
            'id': key,
            'label': str(p.get('label', key.title())),
            'hint': str(p.get('hint', '')),
            'dist_max_km': float(p['dist_max_km']),
            'dist_high_km': float(p['dist_high_km']),
            'az_near_deg': None if distance_only else float(p.get('az_near_deg') or 0.0),
            'distance_only': distance_only,
        })
    return out


def apply_strictness_to_pairs(
    base_rows: list[dict],
    strictness: str | None,
    technology: str | None = None,
) -> list[dict]:
    slug = normalize_strictness(strictness, technology)
    thr = _conflict_profile_thresholds(slug, technology)
    dmax = thr['dist_max_km']
    out: list[dict] = []
    for r in base_rows:
        dist = r.get('distance_km')
        if dist is None or float(dist) > dmax:
            continue
        da = r.get('_d_a')
        db = r.get('_d_b')
        rr = {k: v for k, v in r.items() if not str(k).startswith('_')}
        rr['risk'] = _conflict_risk_for_metrics(float(dist), da, db, thr)
        rr['strictness'] = slug
        out.append(rr)
    risk_rank = {'High': 0, 'Medium': 1, 'Low': 2}
    out.sort(
        key=lambda x: (
            risk_rank.get(x['risk'], 9),
            x['distance_km'],
            str(x.get('conflict_type') or ''),
            str(x.get('pci') or ''),
        )
    )
    return out


def _safe_float(v):
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _extract_coband_key(cell_name: str) -> str:
    s = str(cell_name or '').strip()
    if not s:
        return ''
    hits = re.findall(r'(\d+)', s)
    return hits[-1] if hits else ''


def _parse_code_int(v) -> int | None:
    try:
        if v is None:
            return None
        s = str(v).strip()
        if not s:
            return None
        return int(float(s))
    except (TypeError, ValueError):
        return None


def _haversine_km(lat1, lon1, lat2, lon2) -> float | None:
    lat1 = _safe_float(lat1)
    lon1 = _safe_float(lon1)
    lat2 = _safe_float(lat2)
    lon2 = _safe_float(lon2)
    if None in (lat1, lon1, lat2, lon2):
        return None
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _bearing_deg(lat1, lon1, lat2, lon2) -> float | None:
    lat1 = _safe_float(lat1)
    lon1 = _safe_float(lon1)
    lat2 = _safe_float(lat2)
    lon2 = _safe_float(lon2)
    if None in (lat1, lon1, lat2, lon2):
        return None
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    y = math.sin(dlambda) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlambda)
    b = math.degrees(math.atan2(y, x))
    return (b + 360.0) % 360.0


def _az_diff_deg(a, b) -> float | None:
    a = _safe_float(a)
    b = _safe_float(b)
    if a is None or b is None:
        return None
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)


def _meta():
    from modules.reports.routes import _meta as reports_meta

    return reports_meta()


def _pair_row(
    *,
    code_label: str,
    coband: str,
    conflict_type: str,
    technology,
    a: dict,
    b: dict,
    dist_km: float,
    brg_ab: float | None,
    brg_ba: float | None,
    d_a: float | None,
    d_b: float | None,
) -> dict:
    return {
        'pci': code_label,
        'coband': coband,
        'conflict_type': conflict_type,
        'technology': technology or a.get('technology') or b.get('technology'),
        'distance_km': round(dist_km, 3),
        'bearing_ab': None if brg_ab is None else round(brg_ab, 1),
        'bearing_ba': None if brg_ba is None else round(brg_ba, 1),
        'a_name': a.get('cell_name'),
        'a_site': a.get('site_name') or a.get('site_id'),
        'a_az': a.get('azimuth'),
        'a_band': a.get('frequency_band'),
        'a_area': a.get('cell_area') or a.get('site_area'),
        'a_cluster': a.get('site_cluster'),
        'a_lat': _safe_float(a.get('latitude')),
        'a_lng': _safe_float(a.get('longitude')),
        'a_code': _parse_code_int(a.get('pci')),
        'b_name': b.get('cell_name'),
        'b_site': b.get('site_name') or b.get('site_id'),
        'b_az': b.get('azimuth'),
        'b_band': b.get('frequency_band'),
        'b_area': b.get('cell_area') or b.get('site_area'),
        'b_cluster': b.get('site_cluster'),
        'b_lat': _safe_float(b.get('latitude')),
        'b_lng': _safe_float(b.get('longitude')),
        'b_code': _parse_code_int(b.get('pci')),
        'a_to_b_diff': None if d_a is None else round(d_a, 1),
        'b_to_a_diff': None if d_b is None else round(d_b, 1),
        '_d_a': d_a,
        '_d_b': d_b,
    }


def _emit_pair_if_near(
    pair_rows: list[dict],
    *,
    a: dict,
    b: dict,
    code_label: str,
    coband: str,
    conflict_type: str,
    technology,
    dist_build_max_km: float | None,
) -> None:
    if str(a.get('site_id') or '') == str(b.get('site_id') or ''):
        return
    dist_km = _haversine_km(a.get('latitude'), a.get('longitude'), b.get('latitude'), b.get('longitude'))
    if dist_km is None:
        return
    if dist_build_max_km is not None and dist_km > float(dist_build_max_km):
        return
    brg_ab = _bearing_deg(a.get('latitude'), a.get('longitude'), b.get('latitude'), b.get('longitude'))
    brg_ba = _bearing_deg(b.get('latitude'), b.get('longitude'), a.get('latitude'), a.get('longitude'))
    d_a = _az_diff_deg(a.get('azimuth'), brg_ab)
    d_b = _az_diff_deg(b.get('azimuth'), brg_ba)
    pair_rows.append(
        _pair_row(
            code_label=code_label,
            coband=coband,
            conflict_type=conflict_type,
            technology=technology,
            a=a,
            b=b,
            dist_km=dist_km,
            brg_ab=brg_ab,
            brg_ba=brg_ba,
            d_a=d_a,
            d_b=d_b,
        )
    )


def _build_2g_pairs(rows: list, dist_build_max_km: float | None) -> list[dict]:
    """Co-channel (same BCCH) and adjacent (|ΔBCCH|==1). No band split — all L900."""
    by_bcch: dict[int, list] = {}
    for r in rows:
        rd = dict(r)
        code = _parse_code_int(rd.get('pci'))
        if code is None:
            continue
        by_bcch.setdefault(code, []).append(rd)

    pair_rows: list[dict] = []
    # Co-channel
    for bcch, grp in by_bcch.items():
        if len({g.get('site_id') for g in grp}) < 2:
            continue
        for a, b in combinations(grp, 2):
            _emit_pair_if_near(
                pair_rows,
                a=a,
                b=b,
                code_label=str(bcch),
                coband='',
                conflict_type='co',
                technology='2G',
                dist_build_max_km=dist_build_max_km,
            )

    # Adjacent: pair BCCH N with N+1 only (avoids double-count)
    for bcch in sorted(by_bcch.keys()):
        upper = bcch + 1
        if upper not in by_bcch:
            continue
        grp_lo = by_bcch[bcch]
        grp_hi = by_bcch[upper]
        label = f'{bcch}/{upper}'
        for a in grp_lo:
            for b in grp_hi:
                _emit_pair_if_near(
                    pair_rows,
                    a=a,
                    b=b,
                    code_label=label,
                    coband='',
                    conflict_type='adjacent',
                    technology='2G',
                    dist_build_max_km=dist_build_max_km,
                )

    pair_rows.sort(
        key=lambda r: (r['distance_km'], str(r.get('conflict_type') or ''), str(r.get('pci') or ''))
    )
    return pair_rows


def _build_pci_psc_pairs(rows: list, tech_req: str, dist_build_max_km: float | None) -> list[dict]:
    """3G/4G/5G co-channel PCI/PSC reuse with coband key from cell name."""
    groups: dict[tuple[str, str], list] = {}
    for r in rows:
        rd = dict(r)
        coband = _extract_coband_key(rd.get('cell_name'))
        if not coband:
            continue
        key = (str(rd.get('pci')).strip(), coband)
        groups.setdefault(key, []).append(rd)

    pair_rows: list[dict] = []
    for (pci, coband), grp in groups.items():
        if len({g['site_id'] for g in grp}) < 2:
            continue
        for a, b in combinations(grp, 2):
            _emit_pair_if_near(
                pair_rows,
                a=a,
                b=b,
                code_label=pci,
                coband=coband,
                conflict_type='co',
                technology=a.get('technology') or b.get('technology') or tech_req,
                dist_build_max_km=dist_build_max_km,
            )

    pair_rows.sort(key=lambda r: (r['distance_km'], str(r.get('pci') or '')))
    return pair_rows


def build_conflict_base_pairs(
    technology: str = '4G',
    *,
    dist_max_km: float | None = None,
    unlimited_distance: bool = False,
):
    """Return pair geometry + code grouping; no risk tier (that depends on strictness).

    Distance cap:
      - default: max across strictness profiles for the technology
      - ``dist_max_km``: explicit cap in km
      - ``unlimited_distance=True``: no distance filter (report use)
    """
    conn = _meta()
    inv_union = _metadata_inventory_union_sql(conn, active_only=True)
    site_col_names = _metadata_table_columns(conn, 'sites')
    site_low_to_real = {str(c).strip().lower(): c for c in site_col_names}
    site_area_col = _pick_col(['area', 'region', 'market'], site_low_to_real)
    site_cluster_col = _pick_col(['cluster', 'cluster_name'], site_low_to_real)
    site_area_expr = f"s.{_sql_ident(site_area_col)}" if site_area_col else 'NULL'
    site_cluster_expr = f"s.{_sql_ident(site_cluster_col)}" if site_cluster_col else 'NULL'

    tech_req = normalize_conflict_tech(technology)
    if tech_req == '2G':
        tech_filter = ('2G',)
    elif tech_req == '3G':
        tech_filter = ('3G',)
    elif tech_req == '4G':
        tech_filter = ('4G-FDD', '4G-TDD')
    else:
        tech_filter = ('5G',)
    filter_sql = ', '.join(['?'] * len(tech_filter))

    rows = execute_query(
        conn,
        f'''
        SELECT v.cell_name, v.technology, v.vendor, v.pci, v.azimuth, v.frequency_band,
               v.area AS cell_area,
               s.site_id, s.site_name, s.latitude, s.longitude,
               {site_area_expr} AS site_area,
               {site_cluster_expr} AS site_cluster
        FROM ({inv_union}) v
        LEFT JOIN sites s ON CAST(s.site_id AS TEXT) = CAST(v.site_id AS TEXT)
        WHERE v.cell_name IS NOT NULL
          AND TRIM(CAST(v.cell_name AS TEXT)) <> ''
          AND v.pci IS NOT NULL
          AND TRIM(CAST(v.pci AS TEXT)) <> ''
          AND LOWER(TRIM(COALESCE(v.status, ''))) = 'active'
          AND v.technology IN ({filter_sql})
        ORDER BY v.pci, s.site_name
    ''',
        tech_filter,
    ).fetchall()
    conn.close()

    if unlimited_distance:
        dist_build_max_km: float | None = None
    elif dist_max_km is not None:
        dist_build_max_km = float(dist_max_km)
    else:
        dist_build_max_km = conflict_build_max_km(tech_req)
    if tech_req == '2G':
        pair_rows = _build_2g_pairs(rows, dist_build_max_km)
    else:
        pair_rows = _build_pci_psc_pairs(rows, tech_req, dist_build_max_km)
    return tech_req, pair_rows


def get_cached_conflict_base(technology: str, force_refresh: bool = False):
    tech = normalize_conflict_tech(technology)
    now = datetime.utcnow()
    cached = _CONFLICT_CACHE.get(tech)
    if (not force_refresh) and cached and 'base_rows' in cached:
        gen = cached.get('generated_at')
        if isinstance(gen, datetime) and now - gen <= CONFLICT_CACHE_TTL:
            return tech, cached['base_rows'], gen, False
    tech_req, base_rows = build_conflict_base_pairs(tech)
    generated_at = datetime.utcnow()
    _CONFLICT_CACHE[tech_req] = {'base_rows': base_rows, 'generated_at': generated_at}
    return tech_req, base_rows, generated_at, True


def get_cached_conflict_pairs(
    technology: str,
    strictness: str | None = None,
    force_refresh: bool = False,
    conflict_mode: str | None = None,
):
    tech, base_rows, gen, ref = get_cached_conflict_base(technology, force_refresh=force_refresh)
    rows = apply_strictness_to_pairs(base_rows, strictness, tech)
    mode = normalize_conflict_mode(conflict_mode, tech)
    if mode != 'both':
        rows = [r for r in rows if str(r.get('conflict_type') or 'co') == mode]
    return tech, rows, gen, ref


def kmlline_style_id(risk: str) -> str:
    r = str(risk or '').lower()
    if r == 'high':
        return 'risk-high'
    if r == 'medium':
        return 'risk-medium'
    return 'risk-low'


def destination_point(lat: float, lng: float, bearing_deg: float, distance_km: float):
    r = 6371.0
    br = math.radians(bearing_deg)
    p1 = math.radians(lat)
    l1 = math.radians(lng)
    d = distance_km / r
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(br))
    l2 = l1 + math.atan2(math.sin(br) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), math.degrees(l2)


def wedge_polygon_coords(lat, lng, azimuth, width_deg=40.0, distance_km=0.8, segments=8):
    lat = _safe_float(lat)
    lng = _safe_float(lng)
    az = _safe_float(azimuth)
    if None in (lat, lng, az):
        return []
    start = az - (width_deg / 2.0)
    step = width_deg / max(1, segments)
    pts = [(lat, lng)]
    for i in range(segments + 1):
        b = start + (i * step)
        pts.append(destination_point(lat, lng, b, distance_km))
    pts.append((lat, lng))
    return pts


def generate_pci_conflicts_workbook(
    technology: str = '4G',
    conflict_mode: str | None = None,
    distance_km: float | None = None,
    azimuth_deg: float | None = None,
    strictness: str | None = None,  # unused — kept for call-site compat
):
    """Excel conflict report with optional distance (km) and azimuth (°) filters.

    Empty/None filters are not applied. Azimuth, when set, requires *both* sides'
    azimuth-vs-bearing difference ≤ the threshold (1–180).
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
    except ImportError as e:
        raise RuntimeError('openpyxl required') from e

    tech_req = normalize_conflict_tech(technology)
    mode = normalize_conflict_mode(conflict_mode, tech_req)

    dist_filter = float(distance_km) if distance_km is not None else None
    az_filter = float(azimuth_deg) if azimuth_deg is not None else None

    if dist_filter is not None:
        _, pair_rows = build_conflict_base_pairs(tech_req, dist_max_km=dist_filter)
    else:
        _, pair_rows = build_conflict_base_pairs(tech_req, unlimited_distance=True)

    out_rows: list[dict] = []
    for r in pair_rows:
        ctype = str(r.get('conflict_type') or 'co').strip().lower()
        if mode == 'co' and ctype != 'co':
            continue
        if mode == 'adjacent' and ctype != 'adjacent':
            continue
        dist = r.get('distance_km')
        if dist_filter is not None and (dist is None or float(dist) > dist_filter):
            continue
        if az_filter is not None:
            da = r.get('_d_a')
            db = r.get('_d_b')
            if da is None or db is None:
                continue
            if float(da) > az_filter or float(db) > az_filter:
                continue
        out_rows.append({k: v for k, v in r.items() if not str(k).startswith('_')})

    wb = Workbook()
    ws = wb.active
    code_hdr = 'BCCH' if tech_req == '2G' else 'PCI'
    ws.title = 'BCCH Conflicts' if tech_req == '2G' else 'PCI Conflicts'

    headers = [
        'Filter_Distance_km',
        'Filter_Azimuth_deg',
        'Conflict_Type',
        code_hdr,
        'CoBand',
        'Distance_km',
        'Bearing_A_to_B_deg',
        'Bearing_B_to_A_deg',
        'Cell_A',
        'Site_A',
        'Area_A',
        'Cluster_A',
        'Azimuth_A',
        'A_to_B_Azimuth_Diff_deg',
        'Band_A',
        'Code_A',
        'Cell_B',
        'Site_B',
        'Area_B',
        'Cluster_B',
        'Azimuth_B',
        'B_to_A_Azimuth_Diff_deg',
        'Band_B',
        'Code_B',
    ]
    hdr_fill = PatternFill(start_color='C0392B', end_color='C0392B', fill_type='solid')
    hdr_font = Font(color='FFFFFF', bold=True)
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = hdr_fill
        cell.font = hdr_font

    type_labels = {'co': 'Co-channel', 'adjacent': 'Adjacent'}
    dist_label = dist_filter if dist_filter is not None else 'any'
    az_label = az_filter if az_filter is not None else 'any'
    for r in out_rows:
        ctype = str(r.get('conflict_type') or 'co')
        ws.append(
            [
                dist_label,
                az_label,
                type_labels.get(ctype, ctype),
                r['pci'],
                r.get('coband') or '',
                r['distance_km'],
                r['bearing_ab'],
                r['bearing_ba'],
                r['a_name'],
                r['a_site'],
                r['a_area'],
                r['a_cluster'],
                r['a_az'],
                r['a_to_b_diff'],
                r['a_band'],
                r.get('a_code'),
                r['b_name'],
                r['b_site'],
                r['b_area'],
                r['b_cluster'],
                r['b_az'],
                r['b_to_a_diff'],
                r['b_band'],
                r.get('b_code'),
            ]
        )

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    prefix = 'BCCH_Conflicts' if tech_req == '2G' else 'PCI_Conflicts'
    mode_tag = mode if tech_req == '2G' else 'co'
    dist_tag = f'd{dist_filter:g}km' if dist_filter is not None else 'dAny'
    az_tag = f'az{az_filter:g}' if az_filter is not None else 'azAny'
    fn = f'{prefix}_{tech_req}_{mode_tag}_{dist_tag}_{az_tag}_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'
    return buf, fn, len(out_rows)


# Kept for compatibility; dual pack replaced by UI distance/azimuth settings.
BCCH_DUAL_AZ_MAX_DEG = 50.0


def generate_bcch_conflict_dual_workbook():
    """Deprecated: use generate_pci_conflicts_workbook with distance/azimuth filters."""
    return generate_pci_conflicts_workbook(
        technology='2G',
        conflict_mode='both',
        distance_km=None,
        azimuth_deg=None,
    )
