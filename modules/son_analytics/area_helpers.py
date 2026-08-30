"""Cell → area mapping for SON / Health filters (cluster-derived)."""

from __future__ import annotations

import re
import time

from db.runtime import connect_metadata, execute_query
from modules.reports.metadata_helpers import _metadata_inventory_union_sql

_CELL_SITE_PREFIX_RE = re.compile(r"^(\d{3,6})")

_CLUSTER_AREA = {
    3: "East Amman", 13: "East Amman", 17: "East Amman", 21: "East Amman",
    23: "East Amman", 27: "East Amman", 48: "East Amman", 49: "East Amman",
    50: "East Amman", 51: "East Amman", 52: "East Amman", 54: "East Amman",
    10: "East Jordan", 11: "East Jordan", 19: "East Jordan", 28: "East Jordan",
    31: "East Jordan", 42: "East Jordan", 43: "East Jordan", 47: "East Jordan",
    1: "South Amman", 6: "South Amman", 9: "South Amman", 18: "South Amman",
    30: "South Amman", 36: "South Amman", 38: "South Amman", 39: "South Amman",
    53: "South Amman", 57: "South Amman", 59: "South Amman",
    7: "South Jordan", 8: "South Jordan", 12: "South Jordan", 15: "South Jordan",
    33: "South Jordan", 41: "South Jordan", 58: "South Jordan",
    2: "West Amman", 5: "West Amman", 16: "West Amman", 20: "West Amman",
    22: "West Amman", 25: "West Amman", 26: "West Amman", 32: "West Amman",
    35: "West Amman", 40: "West Amman", 55: "West Amman", 56: "West Amman",
    4: "North Jordan", 14: "North Jordan", 24: "North Jordan", 29: "North Jordan",
    34: "North Jordan", 37: "North Jordan", 44: "North Jordan", 45: "North Jordan",
    46: "North Jordan", 65: "North Jordan",
}

_CELL_AREA_CACHE: dict[str, object] = {"_ts": 0.0, "map": {}}
_CACHE_TTL_SECONDS = 3600


def list_areas() -> list[str]:
    return sorted(set(_CLUSTER_AREA.values()))


def clusters_for_area(area: str | None = None) -> list[int]:
    """Cluster ids (site_id // 100) optionally filtered by area name."""
    if not area:
        return sorted(_CLUSTER_AREA.keys())
    return sorted(cid for cid, a in _CLUSTER_AREA.items() if a == area)


def cluster_from_site_id(site_id) -> int | None:
    try:
        return int(float(str(site_id).strip())) // 100
    except (TypeError, ValueError):
        return None


def as_cluster_int(value) -> int | None:
    """Coerce metadata cluster values like 12, 12.0, '12.0' to int."""
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def cluster_from_cell_name(cell_name: str) -> int | None:
    m = _CELL_SITE_PREFIX_RE.match(str(cell_name or "").strip())
    if not m:
        return None
    return int(m.group(1)) // 100


def resolve_cell_cluster(cell_name: str, loc: dict | None = None) -> int | None:
    info = loc or {}
    return (
        as_cluster_int(info.get("cluster"))
        or cluster_from_site_id(info.get("site_id"))
        or cluster_from_cell_name(cell_name)
    )


def normalize_area(value: str | None) -> str:
    v = str(value or "").strip()
    if not v or v.lower() == "all":
        return ""
    return v


def derive_area_from_site_id(site_id) -> str | None:
    try:
        cluster = int(site_id) // 100
    except (TypeError, ValueError):
        return None
    return _CLUSTER_AREA.get(cluster)


def _resolve_area(site_id, meta_area) -> str | None:
    area = str(meta_area or "").strip()
    if area:
        return area
    return derive_area_from_site_id(site_id)


def get_cell_area_map(*, force_refresh: bool = False) -> dict[str, str]:
    now = time.time()
    if (
        not force_refresh
        and _CELL_AREA_CACHE.get("map")
        and (now - float(_CELL_AREA_CACHE.get("_ts", 0))) < _CACHE_TTL_SECONDS
    ):
        return dict(_CELL_AREA_CACHE["map"])

    out: dict[str, str] = {}
    conn = connect_metadata()
    try:
        union_sql = _metadata_inventory_union_sql(conn)
        rows = execute_query(
            conn,
            f"""
            SELECT DISTINCT cell_name, site_id, area
            FROM ({union_sql}) v
            WHERE cell_name IS NOT NULL AND TRIM(cell_name) != ''
            """,
        ).fetchall()
        for row in rows:
            cell = str(row["cell_name"] or "").strip()
            area = _resolve_area(row["site_id"], row["area"])
            if cell and area:
                out[cell] = area
    except Exception:
        pass
    finally:
        conn.close()

    _CELL_AREA_CACHE["_ts"] = now
    _CELL_AREA_CACHE["map"] = out
    return dict(out)


def get_cell_location_map(*, force_refresh: bool = False) -> dict[str, dict]:
    """Return cell_name -> {latitude, longitude, area, site_id}."""
    now = time.time()
    cache_key = "_loc_v3"
    if (
        not force_refresh
        and _CELL_AREA_CACHE.get(cache_key)
        and (now - float(_CELL_AREA_CACHE.get("_loc_ts", 0))) < _CACHE_TTL_SECONDS
    ):
        return dict(_CELL_AREA_CACHE[cache_key])

    area_map = get_cell_area_map(force_refresh=force_refresh)
    out: dict[str, dict] = {}
    conn = connect_metadata()
    try:
        union_sql = _metadata_inventory_union_sql(conn)
        rows = execute_query(
            conn,
            f"""
            SELECT DISTINCT cell_name, site_id, latitude, longitude, cluster, controller
            FROM ({union_sql}) v
            WHERE cell_name IS NOT NULL AND TRIM(cell_name) != ''
            """,
        ).fetchall()
        for row in rows:
            cell = str(row["cell_name"] or "").strip()
            if not cell:
                continue
            lat = row["latitude"]
            lng = row["longitude"]
            try:
                lat_f = float(lat) if lat is not None else None
                lng_f = float(lng) if lng is not None else None
            except (TypeError, ValueError):
                lat_f = lng_f = None
            site_id = row["site_id"]
            cluster = resolve_cell_cluster(cell, {"cluster": row["cluster"], "site_id": site_id})
            controller = str(row["controller"] or "").strip()
            existing = out.get(cell)
            if existing:
                if existing.get("cluster") is None and cluster is not None:
                    existing["cluster"] = cluster
                if not existing.get("controller") and controller:
                    existing["controller"] = controller
                if existing.get("site_id") in (None, "") and site_id not in (None, ""):
                    existing["site_id"] = site_id
                if existing.get("latitude") is None and lat_f is not None:
                    existing["latitude"] = lat_f
                    existing["longitude"] = lng_f
                continue
            out[cell] = {
                "latitude": lat_f,
                "longitude": lng_f,
                "area": area_map.get(cell, ""),
                "site_id": site_id,
                "cluster": cluster,
                "controller": controller,
            }
    except Exception:
        pass
    finally:
        conn.close()

    _CELL_AREA_CACHE["_loc_ts"] = now
    _CELL_AREA_CACHE[cache_key] = out
    return dict(out)


def primary_area_for_cells(cells: list[str], cell_map: dict[str, str]) -> str:
    for cell in cells:
        area = cell_map.get(str(cell or "").strip())
        if area:
            return area
    return ""


def cell_in_area(cell_name: str, area: str, cell_map: dict[str, str]) -> bool:
    if not area:
        return True
    key = str(cell_name or "").strip()
    return cell_map.get(key) == area


def cell_in_cluster(cell_name: str, cluster: int | None, loc_map: dict[str, dict]) -> bool:
    if cluster is None:
        return True
    key = str(cell_name or "").strip()
    info = loc_map.get(key) or {}
    got = resolve_cell_cluster(key, info)
    if got is None:
        return False
    return got == int(cluster)


def get_cell_technology_map(*, force_refresh: bool = False) -> dict[str, str]:
    """Return cell_name -> technology label (2G, 3G, 4G-FDD, 4G-TDD, 5G)."""
    cache_key = "_tech"
    now = time.time()
    if (
        not force_refresh
        and _CELL_AREA_CACHE.get(cache_key)
        and (now - float(_CELL_AREA_CACHE.get("_tech_ts", 0))) < _CACHE_TTL_SECONDS
    ):
        return dict(_CELL_AREA_CACHE[cache_key])

    out: dict[str, str] = {}
    conn = connect_metadata()
    try:
        union_sql = _metadata_inventory_union_sql(conn)
        rows = execute_query(
            conn,
            f"""
            SELECT DISTINCT cell_name, technology
            FROM ({union_sql}) v
            WHERE cell_name IS NOT NULL AND TRIM(cell_name) != ''
            """,
        ).fetchall()
        for row in rows:
            cell = str(row["cell_name"] or "").strip()
            tech = str(row["technology"] or "").strip()
            if cell and tech:
                out[cell] = tech
    except Exception:
        pass
    finally:
        conn.close()

    _CELL_AREA_CACHE["_tech_ts"] = now
    _CELL_AREA_CACHE[cache_key] = out
    return dict(out)


def cell_in_rat(cell_name: str, rat: str | None, tech_map: dict[str, str]) -> bool:
    if not rat:
        return True
    key = str(cell_name or "").strip()
    cell_tech = tech_map.get(key)
    if not cell_tech:
        return True
    rat_norm = str(rat).strip()
    if rat_norm in ("4G-FDD", "4G-TDD"):
        return cell_tech == rat_norm
    pm_rat = rat_norm
    if pm_rat == "4G":
        return cell_tech in ("4G-FDD", "4G-TDD", "4G")
    return cell_tech == pm_rat


def recommendation_matches_area(rec: dict, area: str, cell_map: dict[str, str]) -> bool:
    if not area:
        return True
    if str(rec.get("area") or "") == area:
        return True
    for cell in rec.get("cells") or []:
        if cell_in_area(str(cell), area, cell_map):
            return True
    ev = rec.get("evidence") or {}
    if str(ev.get("a_area") or "") == area or str(ev.get("b_area") or "") == area:
        return True
    return False
