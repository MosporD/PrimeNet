"""Authenticated elevation lookup API."""

from __future__ import annotations

from functools import wraps

from flask import Blueprint, jsonify, request, redirect, url_for

from core.elevation import coord_key, elevation_for_point, elevation_for_points, is_in_jordan, normalize_coord
from database_enhanced import get_user_by_session

elevation_bp = Blueprint("elevation", __name__)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get("session_token")
        if not token:
            return redirect(url_for("auth.login_page"))
        user = get_user_by_session(token)
        if not user:
            return redirect(url_for("auth.login_page"))
        request.current_user = user
        return f(*args, **kwargs)

    return decorated


@elevation_bp.route("/api/elevation", methods=["GET"])
@login_required
def get_elevation():
    norm = normalize_coord(request.args.get("lat"), request.args.get("lng"))
    if not norm:
        return jsonify({"success": False, "error": "Invalid latitude/longitude"}), 400
    lat, lng = norm
    if not is_in_jordan(lat, lng):
        return jsonify({"success": False, "error": "Coordinate is outside Jordan bounds"}), 400

    elevation_m = elevation_for_point(lat, lng)
    return jsonify(
        {
            "success": True,
            "lat": lat,
            "lng": lng,
            "coord_key": coord_key(lat, lng),
            "elevation_m": elevation_m,
            "source": "cache_or_open_meteo",
        }
    )


@elevation_bp.route("/api/elevation/batch", methods=["POST"])
@login_required
def get_elevation_batch():
    payload = request.get_json(silent=True) or {}
    raw_points = payload.get("points") or []
    if not isinstance(raw_points, list):
        return jsonify({"success": False, "error": "points must be a list"}), 400

    points: list[tuple[float, float]] = []
    rejected = 0
    for item in raw_points[:1000]:
        if isinstance(item, dict):
            norm = normalize_coord(item.get("lat"), item.get("lng"))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            norm = normalize_coord(item[0], item[1])
        else:
            norm = None
        if not norm:
            rejected += 1
            continue
        lat, lng = norm
        if not is_in_jordan(lat, lng):
            rejected += 1
            continue
        points.append((lat, lng))

    result = elevation_for_points(points)
    rows = [
        {
            "lat": lat,
            "lng": lng,
            "coord_key": coord_key(lat, lng),
            "elevation_m": result.get(coord_key(lat, lng)),
        }
        for lat, lng in points
    ]
    return jsonify(
        {
            "success": True,
            "count": len(rows),
            "rejected": rejected,
            "elevations": rows,
        }
    )
