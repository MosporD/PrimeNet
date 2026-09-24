"""Adjacency GIS — join CM snapshot to metadata and audit NCL relations."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any

from db.runtime import connect_metadata

from modules.adjacency_gis.nokia_parse import (
    DEFAULT_OVERSHOOT_KM,
    NCL_HARD_LIMIT,
    build_sector_rows,
    parse_adce_record,
    parse_bts_record,
    parse_trx_bcch,
)

EARTH_KM = 6371.0


def _norm_key(value: object) -> str:
    return re.sub(r'\s+', ' ', str(value or '').strip()).lower()


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == '':
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_KM * math.asin(min(1.0, math.sqrt(a)))


def destination_point(lat: float, lng: float, bearing_deg: float, distance_km: float):
    r = EARTH_KM
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


def _mo_ids_from_lites(lites: list[Any]) -> list[str]:
    return [
        lite['moId']
        for lite in lites
        if isinstance(lite, dict) and lite.get('moId')
    ]


def _mo_ids_from_dn_rows(rows: list[list[Any]]) -> list[str]:
    return [str(row[0]) for row in rows if row and str(row[0]).strip()]


def _list_mo_ids(client, adaptation: str, abbreviation: str, *, conf_id: int = 1) -> list[str]:
    from core.cm_extractor.nokia_client import NokiaCmError
    from core.cm_extractor.nokia_semantics import build_mo_path

    mo_path = build_mo_path(
        adaptation,
        abbreviation,
        scope_level='BSC',
        element_id=None,
    )
    bare = mo_path.split(' as ', 1)[0]
    try:
        mo_ids = _mo_ids_from_lites(client.query_mo_lites(bare, conf_id=conf_id))
        if mo_ids:
            return mo_ids
    except NokiaCmError:
        pass
    rows = client.query(mo_path, ['dn()'], conf_id=conf_id)
    return _mo_ids_from_dn_rows(rows)


def fetch_nokia_adjacency_snapshot(
    client,
    *,
    conf_id: int = 1,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], dict[str, Any]]:
    """
    Network-wide Nokia BTS + BCCH TRX + ADCE pull.

    Returns (sectors, edges, warnings, summary).
    """
    warnings: list[str] = []
    adaptation = 'NOKBSC'

    bts_ids = _list_mo_ids(client, adaptation, 'BTS', conf_id=conf_id)
    trx_ids = _list_mo_ids(client, adaptation, 'TRX', conf_id=conf_id)
    adce_ids = _list_mo_ids(client, adaptation, 'ADCE', conf_id=conf_id)

    if not bts_ids:
        warnings.append('No NOKBSC:BTS instances returned from NetAct.')
    if not trx_ids:
        warnings.append('No NOKBSC:TRX instances returned from NetAct.')
    if not adce_ids:
        warnings.append('No NOKBSC:ADCE instances returned from NetAct.')

    bts_mos = client.get_managed_objects(bts_ids, conf_id=conf_id) if bts_ids else []
    trx_mos = client.get_managed_objects(trx_ids, conf_id=conf_id) if trx_ids else []
    adce_mos = client.get_managed_objects(adce_ids, conf_id=conf_id) if adce_ids else []

    bts_rows: list[dict[str, Any]] = []
    for mo in bts_mos or []:
        parsed = parse_bts_record(mo)
        if parsed:
            bts_rows.append(parsed)

    bcch_by_bts: dict[str, dict[str, Any]] = {}
    for mo in trx_mos or []:
        parsed = parse_trx_bcch(mo)
        if not parsed:
            continue
        bts_dn = parsed['bts_dn']
        # Prefer first BCCH TRX per BTS.
        if bts_dn and bts_dn not in bcch_by_bts:
            bcch_by_bts[bts_dn] = parsed

    sectors = build_sector_rows(bts_rows, bcch_by_bts)
    for s in sectors:
        s['vendor'] = 'nokia'

    edges: list[dict[str, Any]] = []
    bts_dn_set = {s['dn'] for s in sectors}
    skipped_orphan = 0
    for mo in adce_mos or []:
        parsed = parse_adce_record(mo)
        if not parsed:
            continue
        if parsed['bts_dn'] not in bts_dn_set:
            # Parent BTS inactive / missing — skip.
            skipped_orphan += 1
            continue
        parsed['vendor'] = 'nokia'
        edges.append(parsed)

    if skipped_orphan:
        warnings.append(
            f'Skipped {skipped_orphan} ADCE row(s) whose parent BTS was inactive or missing.'
        )

    empty_bcch = sum(1 for s in sectors if s.get('bcch') is None)
    if empty_bcch:
        warnings.append(
            f'{empty_bcch} active BTS sector(s) have no BCCH TRX (channel0Type=4).'
        )

    summary = {
        'bts_listed': len(bts_ids),
        'trx_listed': len(trx_ids),
        'adce_listed': len(adce_ids),
        'bts_active': len(bts_rows),
        'sectors': len(sectors),
        'edges': len(edges),
        'bcch_mapped': len(bcch_by_bts),
    }
    return sectors, edges, warnings, summary


def _list_huawei_bsc_ne_names() -> tuple[list[str], list[str]]:
    """Return (ne_names, warnings) for Huawei GSM BSCs from metadata + discovery."""
    from core.cm_extractor.site_catalog import list_huawei_db_sites

    warnings: list[str] = []
    items = list_huawei_db_sites('', scope_level='BSC', limit=5000)
    names: list[str] = []
    unresolved = 0
    for item in items:
        ne = str(item.get('u2020_ne_name') or item.get('ne_name') or '').strip()
        if ne:
            names.append(ne)
        else:
            unresolved += 1
    # stable unique
    seen: set[str] = set()
    unique: list[str] = []
    for name in names:
        key = name.upper()
        if key in seen:
            continue
        seen.add(key)
        unique.append(name)
    if not unique:
        warnings.append('No Huawei BSC NE names resolved from metadata/discovery.')
    if unresolved:
        warnings.append(f'{unresolved} Huawei BSC controller(s) had no U2020 NE name.')
    return unique, warnings


def _mml_ne_name(row: dict[str, Any]) -> str:
    for key in ('NE name', 'NE Name', 'ne_name', 'BSC Name', 'BSC'):
        val = row.get(key)
        if val not in (None, ''):
            return str(val).strip()
    return ''


def fetch_huawei_adjacency_snapshot(
    client,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], dict[str, Any]]:
    """
    Network-wide Huawei BSC GTRX (main BCCH) + G2GNCELL + GCELL name join.

    Returns (sectors, edges, warnings, summary).
    """
    from core.cm_extractor.huawei_semantics import (
        MML_HIGH_CARDINALITY_CHUNK,
        MML_SINGLE_NE_LIMIT,
        build_mml_command,
    )
    from core.cm_extractor.mml_parser import repair_mml_rows
    from modules.adjacency_gis.huawei_parse import (
        join_trx_with_gcell,
        parse_g2gncell_row,
        parse_gcell_row,
        parse_gtrx_bcch_row,
    )

    warnings: list[str] = []
    ne_names, name_warnings = _list_huawei_bsc_ne_names()
    warnings.extend(name_warnings)
    if not ne_names:
        return [], [], warnings, {'bsc_nes': 0, 'sectors': 0, 'edges': 0}

    def _run(mo_id: str, *, chunk: int) -> list[dict[str, Any]]:
        cmd = build_mml_command(mo_id)
        rows = client.run_mml_chunked(cmd, ne_names, chunk_size=chunk)
        rows = repair_mml_rows(rows or [])
        errors = []
        try:
            errors = client.consume_mml_errors()
        except Exception:
            errors = []
        for err in errors[:8]:
            warnings.append(f'{mo_id}: {err}')
        if len(errors) > 8:
            warnings.append(f'{mo_id}: …and {len(errors) - 8} more MML errors')
        return rows

    gcell_rows = _run('GCELL', chunk=MML_SINGLE_NE_LIMIT)
    try:
        trx_rows_raw = _run('GTRX', chunk=MML_SINGLE_NE_LIMIT)
    except Exception as exc:
        warnings.append(f'LST GTRX failed: {exc}')
        trx_rows_raw = []
    try:
        ncell_rows_raw = _run('G2GNCELL', chunk=MML_HIGH_CARDINALITY_CHUNK)
    except Exception as exc:
        warnings.append(f'LST G2GNCELL failed: {exc}')
        ncell_rows_raw = []

    gcell_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    for row in gcell_rows:
        parsed = parse_gcell_row(row, ne_name=_mml_ne_name(row))
        if not parsed or parsed.get('cell_index') is None:
            continue
        key = (str(parsed['bsc_id']).strip().lower(), int(parsed['cell_index']))
        gcell_by_key[key] = parsed

    trx_parsed = []
    for row in trx_rows_raw:
        parsed = parse_gtrx_bcch_row(row, ne_name=_mml_ne_name(row))
        if parsed:
            trx_parsed.append(parsed)

    sectors = join_trx_with_gcell(trx_parsed, gcell_by_key)

    # Fallback: if GTRX empty, build sectors from GCELL BCCH alone.
    if not sectors and gcell_by_key:
        warnings.append('No main-BCCH GTRX rows; falling back to GCELL BCCH for sectors.')
        from modules.adjacency_gis.huawei_parse import sector_dn

        for gcell in gcell_by_key.values():
            idx = gcell['cell_index']
            bsc = gcell['bsc_id']
            dn = sector_dn(bsc, idx)
            sectors.append({
                'dn': dn,
                'bts_dn': dn,
                'bsc_id': bsc,
                'bcf_id': '',
                'instance': str(idx),
                'segment_name': gcell.get('cell_name') or '',
                'cell_name': gcell.get('cell_name') or '',
                'cell_id': gcell.get('cell_id'),
                'bcch': gcell.get('bcch'),
                'trx_dn': '',
                'admin_state': '',
                'vendor': 'huawei',
            })

    sector_dns = {s['dn'] for s in sectors}
    # Also index by (bsc, cell_index) for edge source resolution
    sector_by_cell: dict[tuple[str, int], str] = {}
    for s in sectors:
        # dn form huawei:bsc:index
        parts = str(s['dn']).split(':')
        if len(parts) >= 3:
            try:
                sector_by_cell[(parts[1].lower(), int(parts[2]))] = s['dn']
            except ValueError:
                pass

    edges: list[dict[str, Any]] = []
    skipped = 0
    for row in ncell_rows_raw:
        parsed = parse_g2gncell_row(row, ne_name=_mml_ne_name(row))
        if not parsed:
            continue
        if parsed.get('adj_ci') is None:
            skipped += 1
            continue
        src_idx = parsed.get('source_cell_index')
        bsc = str(parsed.get('bsc_id') or '').lower()
        src_dn = None
        if src_idx is not None:
            src_dn = sector_by_cell.get((bsc, int(src_idx)))
        if not src_dn:
            src_dn = parsed.get('source_dn')
        if src_dn not in sector_dns:
            skipped += 1
            continue
        parsed['source_dn'] = src_dn
        parsed['bts_dn'] = src_dn
        edges.append(parsed)

    if skipped:
        warnings.append(f'Skipped {skipped} G2GNCELL row(s) without resolvable source/target CI.')
    if not trx_rows_raw:
        warnings.append('LST GTRX returned no rows — check BSC NE names / MML permissions.')
    if not ncell_rows_raw:
        warnings.append('LST G2GNCELL returned no rows — neighbor map will be empty for Huawei.')

    summary = {
        'bsc_nes': len(ne_names),
        'gcell_rows': len(gcell_rows),
        'gtrx_rows': len(trx_rows_raw),
        'g2gncell_rows': len(ncell_rows_raw),
        'gcell_mapped': len(gcell_by_key),
        'sectors': len(sectors),
        'edges': len(edges),
    }
    return sectors, edges, warnings, summary


def load_cells_2g_index() -> dict[str, Any]:
    """Indexes for joining ADCE targets and BTS sources to metadata geometry."""
    by_name: dict[str, dict[str, Any]] = {}
    by_cell_id: dict[str, dict[str, Any]] = {}
    by_ci_lac: dict[tuple[int, int | None], dict[str, Any]] = {}
    by_ci: dict[int, list[dict[str, Any]]] = defaultdict(list)

    conn = connect_metadata()
    try:
        rows = conn.execute(
            """
            SELECT
                cell_name, site_id, site_name, cell_id, lac, bcch,
                CAST(lat AS REAL) AS latitude,
                CAST(long AS REAL) AS longitude,
                CAST(azimuth AS REAL) AS azimuth,
                area, vendor, frequency_band
            FROM cells_2g
            WHERE lat IS NOT NULL AND long IS NOT NULL
            """
        ).fetchall()
    except Exception:
        # Column names may vary slightly across deployments.
        try:
            rows = conn.execute(
                """
                SELECT
                    cell_name, site_id, site_name, cell_id, lac, bcch,
                    CAST(lat AS REAL) AS latitude,
                    CAST(long AS REAL) AS longitude,
                    CAST(azimuth AS REAL) AS azimuth,
                    '' AS area, vendor, frequency_band
                FROM cells_2g
                WHERE lat IS NOT NULL AND long IS NOT NULL
                """
            ).fetchall()
        except Exception:
            return {
                'by_name': by_name,
                'by_cell_id': by_cell_id,
                'by_ci_lac': by_ci_lac,
                'by_ci': by_ci,
            }
    finally:
        try:
            conn.close()
        except Exception:
            pass

    for row in rows:
        if hasattr(row, 'keys'):
            item = {k: row[k] for k in row.keys()}
        else:
            continue
        cell = {
            'cell_name': str(item.get('cell_name') or '').strip(),
            'site_id': str(item.get('site_id') or '').strip(),
            'site_name': str(item.get('site_name') or '').strip(),
            'cell_id': item.get('cell_id'),
            'lac': item.get('lac'),
            'bcch': _safe_float(item.get('bcch')),
            'lat': _safe_float(item.get('latitude')),
            'lng': _safe_float(item.get('longitude')),
            'azimuth': _safe_float(item.get('azimuth')),
            'area': str(item.get('area') or '').strip(),
            'vendor': str(item.get('vendor') or '').strip(),
            'frequency_band': str(item.get('frequency_band') or '').strip(),
        }
        if cell['lat'] is None or cell['lng'] is None:
            continue
        if cell['cell_name']:
            by_name[_norm_key(cell['cell_name'])] = cell
        cid = cell['cell_id']
        try:
            cid_int = int(cid) if cid is not None and str(cid).strip() != '' else None
        except (TypeError, ValueError):
            cid_int = None
        if cid_int is not None:
            by_cell_id[str(cid_int)] = cell
            by_ci[cid_int].append(cell)
            lac_val = None
            try:
                lac_val = int(cell['lac']) if cell['lac'] is not None and str(cell['lac']).strip() != '' else None
            except (TypeError, ValueError):
                lac_val = None
            by_ci_lac[(cid_int, lac_val)] = cell
    return {
        'by_name': by_name,
        'by_cell_id': by_cell_id,
        'by_ci_lac': by_ci_lac,
        'by_ci': dict(by_ci),
    }


def resolve_source_meta(sector: dict[str, Any], index: dict[str, Any]) -> dict[str, Any] | None:
    name = _norm_key(sector.get('cell_name') or sector.get('segment_name'))
    if name and name in index['by_name']:
        return index['by_name'][name]
    seg = _norm_key(sector.get('segment_name'))
    if seg and seg in index['by_name']:
        return index['by_name'][seg]
    cid = sector.get('cell_id')
    if cid is not None and str(cid) in index['by_cell_id']:
        return index['by_cell_id'][str(cid)]
    return None


def resolve_target_meta(
    adj_ci: int,
    adj_lac: int | None,
    index: dict[str, Any],
) -> dict[str, Any] | None:
    if adj_lac is not None and (adj_ci, adj_lac) in index['by_ci_lac']:
        return index['by_ci_lac'][(adj_ci, adj_lac)]
    # Prefer lac-less exact key
    if (adj_ci, None) in index['by_ci_lac']:
        return index['by_ci_lac'][(adj_ci, None)]
    candidates = index['by_ci'].get(adj_ci) or []
    if len(candidates) == 1:
        return candidates[0]
    if adj_lac is not None:
        for c in candidates:
            try:
                if int(c.get('lac')) == int(adj_lac):
                    return c
            except (TypeError, ValueError):
                continue
    return candidates[0] if candidates else None


def _sector_map_key(sector: dict[str, Any], meta: dict[str, Any] | None) -> str:
    if meta and meta.get('cell_name'):
        return _norm_key(meta['cell_name'])
    if sector.get('cell_name'):
        return _norm_key(sector['cell_name'])
    if sector.get('segment_name'):
        return _norm_key(sector['segment_name'])
    return _norm_key(sector.get('dn'))


def build_map_payload(
    sectors: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    bsc_id: str = '',
    area: str = '',
    issue: str = 'all',
    vendor: str = 'all',
    overshoot_km: float = DEFAULT_OVERSHOOT_KM,
    ncl_limit: int = NCL_HARD_LIMIT,
) -> dict[str, Any]:
    """Join snapshot to metadata and classify adjacency audits."""
    index = load_cells_2g_index()
    want_bsc = (bsc_id or '').strip()
    want_area = (area or '').strip().lower()
    want_issue = (issue or 'all').strip().lower()
    want_vendor = (vendor or 'all').strip().lower()

    sector_by_dn: dict[str, dict[str, Any]] = {}
    map_sectors: list[dict[str, Any]] = []

    for sector in sectors:
        sec_vendor = str(sector.get('vendor') or 'nokia').strip().lower()
        if want_vendor not in ('all', '*', '') and sec_vendor != want_vendor:
            continue
        if want_bsc and want_bsc.lower() not in ('all', '*') and str(sector.get('bsc_id') or '') != want_bsc:
            continue
        meta = resolve_source_meta(sector, index)
        if not meta:
            continue
        if want_area and want_area not in ('all', '*'):
            if _norm_key(meta.get('area')) != _norm_key(want_area):
                continue
        key = _sector_map_key(sector, meta)
        bcch = sector.get('bcch')
        if bcch is None and meta.get('bcch') is not None:
            try:
                bcch = int(meta['bcch'])
            except (TypeError, ValueError):
                bcch = None
        row = {
            'dn': sector['dn'],
            'key': key,
            'cell_name': meta.get('cell_name') or sector.get('cell_name'),
            'segment_name': sector.get('segment_name') or '',
            'site_id': meta.get('site_id') or '',
            'site_name': meta.get('site_name') or '',
            'bsc_id': sector.get('bsc_id') or '',
            'cell_id': sector.get('cell_id'),
            'bcch': bcch,
            'lat': meta['lat'],
            'lng': meta['lng'],
            'azimuth': meta.get('azimuth'),
            'area': meta.get('area') or '',
            'band': meta.get('frequency_band') or '',
            'vendor': sec_vendor or meta.get('vendor') or 'nokia',
        }
        sector_by_dn[sector['dn']] = row
        map_sectors.append(row)

    # Outgoing counts for NCL limit (all edges from active sectors, even if target unresolved).
    out_count: Counter[str] = Counter()
    for edge in edges:
        src = edge.get('source_dn') or edge.get('bts_dn')
        if src in sector_by_dn:
            out_count[src] += 1

    # Pair keys for bidirectional check (resolved endpoints only).
    directed: set[tuple[str, str]] = set()
    map_edges_raw: list[dict[str, Any]] = []

    for edge in edges:
        src_dn = edge.get('source_dn') or edge.get('bts_dn')
        src = sector_by_dn.get(src_dn)
        if not src:
            continue
        tgt = resolve_target_meta(int(edge['adj_ci']), edge.get('adj_lac'), index)
        if not tgt or tgt.get('lat') is None or tgt.get('lng') is None:
            continue
        tgt_key = _norm_key(tgt.get('cell_name'))
        if not tgt_key:
            continue
        dist = haversine_km(src['lat'], src['lng'], float(tgt['lat']), float(tgt['lng']))
        src_bcch = src.get('bcch')
        tgt_bcch = edge.get('bcch_frequency')
        if tgt_bcch is None and tgt.get('bcch') is not None:
            try:
                tgt_bcch = int(tgt['bcch'])
            except (TypeError, ValueError):
                tgt_bcch = None
        co_channel = (
            src_bcch is not None
            and tgt_bcch is not None
            and int(src_bcch) == int(tgt_bcch)
        )
        overshoot = dist > float(overshoot_km)
        ncl_overflow = out_count.get(src_dn, 0) > int(ncl_limit)
        directed.add((src['key'], tgt_key))
        map_edges_raw.append({
            'dn': edge.get('dn') or '',
            'source_dn': src_dn,
            'source_key': src['key'],
            'source_name': src['cell_name'],
            'source_lat': src['lat'],
            'source_lng': src['lng'],
            'source_bcch': src_bcch,
            'target_key': tgt_key,
            'target_name': tgt.get('cell_name') or '',
            'target_lat': float(tgt['lat']),
            'target_lng': float(tgt['lng']),
            'target_bcch': tgt_bcch,
            'target_ci': edge.get('adj_ci'),
            'target_lac': edge.get('adj_lac'),
            'distance_km': round(dist, 3),
            'co_channel': co_channel,
            'overshoot': overshoot,
            'ncl_overflow': ncl_overflow,
            'ncl_count': out_count.get(src_dn, 0),
        })

    # Directionality
    for row in map_edges_raw:
        reverse = (row['target_key'], row['source_key']) in directed
        row['bidirectional'] = reverse
        row['unidirectional'] = not reverse
        flags = []
        if row['unidirectional']:
            flags.append('unidirectional')
        if row['overshoot']:
            flags.append('overshoot')
        if row['ncl_overflow']:
            flags.append('ncl_overflow')
        if row['co_channel']:
            flags.append('co_channel')
        row['issues'] = flags
        # Primary severity for coloring
        if row['co_channel']:
            row['severity'] = 'co_channel'
        elif row['ncl_overflow'] or row['overshoot']:
            row['severity'] = 'overshoot'
        elif row['unidirectional']:
            row['severity'] = 'unidirectional'
        else:
            row['severity'] = 'ok'

    filtered_edges = map_edges_raw
    if want_issue and want_issue not in ('all', '*', ''):
        if want_issue == 'ok':
            filtered_edges = [e for e in map_edges_raw if not e['issues']]
        else:
            filtered_edges = [e for e in map_edges_raw if want_issue in e['issues']]

    # Keep sectors that appear in filtered edges or all if issue=all
    if want_issue and want_issue not in ('all', '*', ''):
        keep_keys = set()
        for e in filtered_edges:
            keep_keys.add(e['source_key'])
            keep_keys.add(e['target_key'])
        map_sectors = [s for s in map_sectors if s['key'] in keep_keys]

    counts = Counter()
    for e in map_edges_raw:
        if e['unidirectional']:
            counts['unidirectional'] += 1
        if e['overshoot']:
            counts['overshoot'] += 1
        if e['ncl_overflow']:
            counts['ncl_overflow'] += 1
        if e['co_channel']:
            counts['co_channel'] += 1
        if not e['issues']:
            counts['ok'] += 1

    areas = sorted({s['area'] for s in map_sectors if s.get('area')})
    bscs = sorted({s['bsc_id'] for s in map_sectors if s.get('bsc_id')})

    return {
        'sectors': map_sectors,
        'edges': filtered_edges,
        'counts': {
            'sectors': len(map_sectors),
            'edges': len(filtered_edges),
            'edges_total': len(map_edges_raw),
            **dict(counts),
        },
        'filters': {
            'areas': areas,
            'bscs': bscs,
            'vendors': ['all', 'nokia', 'huawei'],
            'issues': ['all', 'unidirectional', 'overshoot', 'ncl_overflow', 'co_channel', 'ok'],
            'overshoot_km': overshoot_km,
            'ncl_limit': ncl_limit,
        },
    }


def list_bcch_options() -> list[int]:
    """Distinct integer BCCH (ARFCN) values from metadata.db cells_2g with coordinates."""
    conn = connect_metadata()
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT CAST(bcch AS INTEGER) AS bcch
            FROM cells_2g
            WHERE bcch IS NOT NULL
              AND TRIM(CAST(bcch AS TEXT)) <> ''
              AND lat IS NOT NULL
              AND long IS NOT NULL
            ORDER BY CAST(bcch AS INTEGER)
            """
        ).fetchall()
    except Exception:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass

    out: list[int] = []
    seen: set[int] = set()
    for row in rows:
        raw = row[0] if not hasattr(row, 'keys') else row['bcch']
        try:
            val = int(raw)
        except (TypeError, ValueError):
            continue
        if val in seen:
            continue
        seen.add(val)
        out.append(val)
    return out


def build_bcch_map_payload(selected_bcch: int) -> dict[str, Any]:
    """Cells on selected BCCH and ±1 adjacent channels for co-channel map overlay."""
    selected = int(selected_bcch)
    lower = selected - 1
    upper = selected + 1
    roles = {selected: 'selected', lower: 'lower', upper: 'upper'}

    conn = connect_metadata()
    try:
        rows = conn.execute(
            """
            SELECT
                cell_name,
                site_id,
                site_name,
                vendor,
                CAST(bcch AS INTEGER) AS bcch,
                CAST(lat AS REAL) AS lat,
                CAST(long AS REAL) AS lng,
                CAST(azimuth AS REAL) AS azimuth,
                frequency_band
            FROM cells_2g
            WHERE CAST(bcch AS INTEGER) IN (?, ?, ?)
              AND lat IS NOT NULL
              AND long IS NOT NULL
            """,
            (lower, selected, upper),
        ).fetchall()
    except Exception:
        rows = []
    finally:
        try:
            conn.close()
        except Exception:
            pass

    cells: list[dict[str, Any]] = []
    counts = {'selected': 0, 'lower': 0, 'upper': 0}
    for row in rows:
        if hasattr(row, 'keys'):
            item = {k: row[k] for k in row.keys()}
        else:
            continue
        try:
            bcch = int(item.get('bcch'))
        except (TypeError, ValueError):
            continue
        role = roles.get(bcch)
        if not role:
            continue
        lat = _safe_float(item.get('lat'))
        lng = _safe_float(item.get('lng'))
        if lat is None or lng is None:
            continue
        cells.append({
            'cell_name': str(item.get('cell_name') or '').strip(),
            'site_id': str(item.get('site_id') or '').strip(),
            'site_name': str(item.get('site_name') or '').strip(),
            'vendor': str(item.get('vendor') or '').strip(),
            'bcch': bcch,
            'lat': lat,
            'lng': lng,
            'azimuth': _safe_float(item.get('azimuth')),
            'frequency_band': str(item.get('frequency_band') or '').strip(),
            'role': role,
        })
        counts[role] += 1

    return {
        'selected': selected,
        'lower': lower,
        'upper': upper,
        'cells': cells,
        'counts': counts,
    }
