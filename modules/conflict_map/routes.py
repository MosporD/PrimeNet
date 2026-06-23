"""
Conflict map UI and APIs (PCI reuse by distance + azimuth vs. bearing).
"""

from __future__ import annotations

import io
from datetime import datetime
from xml.sax.saxutils import escape as xml_escape

from flask import Blueprint, jsonify, render_template, request, send_file

from modules.reports.routes import _coord_key, _elevation_for_points, format_user, get_current_user, login_required

from .logic import (
    DEFAULT_CONFLICT_STRICTNESS,
    _safe_float,
    apply_strictness_to_pairs,
    conflict_strictness_profiles_public,
    get_cached_conflict_base,
    get_cached_conflict_pairs,
    kmlline_style_id,
    normalize_conflict_tech,
    normalize_strictness,
    wedge_polygon_coords,
)

conflict_map_bp = Blueprint(
    'conflict_map',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/conflict_map/static',
)


@conflict_map_bp.route('/conflict-map')
@login_required
def conflict_map_page():
    user = get_current_user()
    return render_template('conflict_map.html', user=format_user(user))


@conflict_map_bp.route('/api/conflict-map/data')
@login_required
def pci_conflicts_map_data():
    technology = str(request.args.get('technology', '4G') or '4G')
    strictness = normalize_strictness(request.args.get('strictness', DEFAULT_CONFLICT_STRICTNESS))
    risk = str(request.args.get('risk', 'all') or 'all').strip().lower()
    area_values = [str(v).strip() for v in request.args.getlist('area') if str(v).strip()]
    if not area_values:
        single = str(request.args.get('area', 'all') or 'all').strip()
        if single:
            area_values = [single]
    area_set = {v for v in area_values if v.lower() != 'all'}
    band = str(request.args.get('band', 'all') or 'all').strip()
    include_elevation = str(request.args.get('include_elevation', '0')).strip().lower() in ('1', 'true', 'yes', 'on')
    tech_req, base_rows, generated_at, refreshed = get_cached_conflict_base(technology, force_refresh=False)
    rows = apply_strictness_to_pairs(base_rows, strictness)

    def _row_match(r):
        if risk in ('high', 'medium', 'low') and str(r.get('risk', '')).lower() != risk:
            return False
        if area_set:
            area_a = str(r.get('a_area') or '')
            area_b = str(r.get('b_area') or '')
            if (area_a not in area_set) and (area_b not in area_set):
                return False
        if band.lower() != 'all':
            band_a = str(r.get('a_band') or '')
            band_b = str(r.get('b_band') or '')
            if band not in (band_a, band_b):
                return False
        return True

    filtered = [dict(r) for r in rows if _row_match(r)]
    areas = sorted({str(v) for r in base_rows for v in (r.get('a_area'), r.get('b_area')) if v})
    bands = sorted({str(v) for r in base_rows for v in (r.get('a_band'), r.get('b_band')) if v})

    if include_elevation and filtered:
        pts = []
        for r in filtered:
            if r.get('a_lat') is not None and r.get('a_lng') is not None:
                pts.append((float(r['a_lat']), float(r['a_lng'])))
            if r.get('b_lat') is not None and r.get('b_lng') is not None:
                pts.append((float(r['b_lat']), float(r['b_lng'])))
        elev_map = _elevation_for_points(pts)
        for r in filtered:
            a_e = (
                elev_map.get(_coord_key(float(r['a_lat']), float(r['a_lng'])))
                if r.get('a_lat') is not None and r.get('a_lng') is not None
                else None
            )
            b_e = (
                elev_map.get(_coord_key(float(r['b_lat']), float(r['b_lng'])))
                if r.get('b_lat') is not None and r.get('b_lng') is not None
                else None
            )
            r['a_elevation_m'] = a_e
            r['b_elevation_m'] = b_e
            if a_e is not None and b_e is not None:
                r['elevation_delta_m'] = round(float(a_e) - float(b_e), 1)
            else:
                r['elevation_delta_m'] = None

    return jsonify(
        {
            'success': True,
            'technology': tech_req,
            'strictness': strictness,
            'candidate_total': len(base_rows),
            'total': len(rows),
            'filtered_total': len(filtered),
            'filters': {
                'areas': areas,
                'bands': bands,
                'risk': ['High', 'Medium', 'Low'],
                'strictness_profiles': conflict_strictness_profiles_public(),
                'strictness_default': DEFAULT_CONFLICT_STRICTNESS,
            },
            'cache': {
                'generated_at': generated_at.isoformat() + 'Z' if generated_at else None,
                'refreshed': refreshed,
            },
            'include_elevation': include_elevation,
            'rows': filtered,
        }
    )


@conflict_map_bp.route('/api/conflict-map/refresh', methods=['POST'])
@login_required
def refresh_conflict_map_data():
    payload = request.get_json(silent=True) or {}
    tech_req = str(payload.get('technology', 'all') or 'all').strip().upper()
    targets = ['3G', '4G', '5G'] if tech_req == 'ALL' else [normalize_conflict_tech(tech_req)]
    out = {}
    for t in targets:
        _, base_rows, generated_at, _ = get_cached_conflict_base(t, force_refresh=True)
        out[t] = {
            'candidate_pairs': len(base_rows),
            'generated_at': generated_at.isoformat() + 'Z',
        }
    return jsonify({'success': True, 'refreshed': out})


@conflict_map_bp.route('/api/conflict-map/export-kml')
@login_required
def export_conflict_map_kml():
    technology = str(request.args.get('technology', '4G') or '4G')
    strictness = normalize_strictness(request.args.get('strictness', DEFAULT_CONFLICT_STRICTNESS))
    risk = str(request.args.get('risk', 'all') or 'all').strip().lower()
    area_values = [str(v).strip() for v in request.args.getlist('area') if str(v).strip()]
    if not area_values:
        single = str(request.args.get('area', 'all') or 'all').strip()
        if single:
            area_values = [single]
    area_set = {v for v in area_values if v.lower() != 'all'}
    band = str(request.args.get('band', 'all') or 'all').strip()
    tech_req, rows, _, _ = get_cached_conflict_pairs(technology, strictness, force_refresh=False)

    def _row_match(r):
        if risk in ('high', 'medium', 'low') and str(r.get('risk', '')).lower() != risk:
            return False
        if area_set:
            area_a = str(r.get('a_area') or '')
            area_b = str(r.get('b_area') or '')
            if (area_a not in area_set) and (area_b not in area_set):
                return False
        if band.lower() != 'all':
            band_a = str(r.get('a_band') or '')
            band_b = str(r.get('b_band') or '')
            if band not in (band_a, band_b):
                return False
        return True

    filtered = [r for r in rows if _row_match(r)]
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
        f'<name>{xml_escape(f"Conflict_Map_{tech_req}_{strictness}")}</name>',
        '<Style id="risk-high"><LineStyle><color>ff2b2bc0</color><width>3</width></LineStyle><PolyStyle><color>552b2bc0</color></PolyStyle></Style>',
        '<Style id="risk-medium"><LineStyle><color>ff12a3f3</color><width>3</width></LineStyle><PolyStyle><color>5512a3f3</color></PolyStyle></Style>',
        '<Style id="risk-low"><LineStyle><color>ffb98029</color><width>3</width></LineStyle><PolyStyle><color>55b98029</color></PolyStyle></Style>',
    ]

    for idx, r in enumerate(filtered, start=1):
        a_lat, a_lng = _safe_float(r.get('a_lat')), _safe_float(r.get('a_lng'))
        b_lat, b_lng = _safe_float(r.get('b_lat')), _safe_float(r.get('b_lng'))
        if None in (a_lat, a_lng, b_lat, b_lng):
            continue
        style_id = kmlline_style_id(r.get('risk'))
        name = xml_escape(f"{r.get('risk', 'Risk')} | {r.get('pci', '')} | {r.get('a_site', '')} -> {r.get('b_site', '')}")
        desc = xml_escape(
            f"Technology: {r.get('technology', '-')}\n"
            f"Distance(km): {r.get('distance_km', '-')}\n"
            f"A: {r.get('a_name', '')} ({r.get('a_site', '')})\n"
            f"B: {r.get('b_name', '')} ({r.get('b_site', '')})"
        )
        parts.append(
            f'<Placemark><name>{name}</name><description>{desc}</description>'
            f'<styleUrl>#{style_id}</styleUrl><LineString><tessellate>1</tessellate><coordinates>{a_lng},{a_lat},0 {b_lng},{b_lat},0</coordinates></LineString></Placemark>'
        )

        for side in ('a', 'b'):
            wpts = wedge_polygon_coords(r.get(f'{side}_lat'), r.get(f'{side}_lng'), r.get(f'{side}_az'))
            if not wpts:
                continue
            coords = ' '.join(f'{lng},{lat},0' for lat, lng in wpts)
            pname = xml_escape(f"Wedge {idx}-{side.upper()} {r.get(f'{side}_name', '')}")
            parts.append(
                f'<Placemark><name>{pname}</name><styleUrl>#{style_id}</styleUrl>'
                f'<Polygon><outerBoundaryIs><LinearRing><coordinates>{coords}</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>'
            )

    parts.append('</Document></kml>')
    payload = '\n'.join(parts).encode('utf-8')
    return send_file(
        io.BytesIO(payload),
        as_attachment=True,
        download_name=f'Conflict_Map_{tech_req}_{strictness}_{datetime.now().strftime("%Y%m%d_%H%M")}.kml',
        mimetype='application/vnd.google-earth.kml+xml',
    )
