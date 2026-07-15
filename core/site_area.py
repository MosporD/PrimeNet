"""
Canonical site_id → area routing for PM area tables and geo filters.

================================================================================
COMPLETE GUIDE — how to place a cell/site into an area PM table
================================================================================

1) Normalize the site id (NetAct / long ids only)
   - If numeric length is 5+ and value >= 60000 → subtract 60000
     e.g. 64415 → 4415
   - Else if numeric length is 5+ and value >= 50000 → subtract 50000
     e.g. 53306 → 3306, 50308 → 308
   - Do NOT strip short UL ids like 6001 / 6400 (already 4 digits)

2) Manual overrides (sites with no cell area and no lat/lng)
   - 6008 → North Jordan
   - 6068, 6069 → South Jordan
   - 6074 → North Jordan
   - 6086, 6150, 6484, 6485 → South Jordan
   - 9999 → South Amman

3) Else derive from cluster map
   - cluster = int(site_id) // 100
   - area = CLUSTER_AREA[cluster]
   - This covers normal site numbering (1xx … 59xx, 65xx, …)

4) Else (UL blocks 60xx–64xx and any other gap)
   - Take the dominant non-blank ``area`` from metadata cell tables for that
     site_id (cells_2g / 3g / 4g / 5g).
   - Cell inventory may store short names — canonicalize:
       North → North Jordan
       Zarqa → East Jordan
   - Cell ``cluster`` on those rows is the geographic cluster (e.g. 14), not
     the UL id block (60). Prefer the area field; cluster is a fallback.

5) Final areas used for table naming (stable set)
   East Amman | East Jordan | North Jordan | South Amman | South Jordan | West Amman
   (+ Unknown for cells that cannot be routed)

Example PM table name:
   4G_CELLS_HOURLY__WEST_AMMAN
   slug = area.upper().replace(" ", "_")

Rollout (preferred — no bulk migration):
   - New hourly/daily loads write ONLY to area partitions.
   - APIs dual-read: area partition (new) + legacy monotable (history).
   - After one full retention window, monotable is empty/stale → drop it
     and read area tables only.
   - Optional: scripts/migrate_pm_to_area_tables.py can still backfill early.
================================================================================
"""

from __future__ import annotations

import re
import time
from collections import Counter
from typing import Any

from db.runtime import connect_metadata, execute_query

# Cluster = floor(canonical_site_id / 100) → area (same map as network map / performance).
CLUSTER_AREA: dict[int, str] = {
    3: "East Amman",
    13: "East Amman",
    17: "East Amman",
    21: "East Amman",
    23: "East Amman",
    27: "East Amman",
    48: "East Amman",
    49: "East Amman",
    50: "East Amman",
    51: "East Amman",
    52: "East Amman",
    54: "East Amman",
    10: "East Jordan",
    11: "East Jordan",
    19: "East Jordan",
    28: "East Jordan",
    31: "East Jordan",
    42: "East Jordan",
    43: "East Jordan",
    47: "East Jordan",
    1: "South Amman",
    6: "South Amman",
    9: "South Amman",
    18: "South Amman",
    30: "South Amman",
    36: "South Amman",
    38: "South Amman",
    39: "South Amman",
    53: "South Amman",
    57: "South Amman",
    59: "South Amman",
    7: "South Jordan",
    8: "South Jordan",
    12: "South Jordan",
    15: "South Jordan",
    33: "South Jordan",
    41: "South Jordan",
    58: "South Jordan",
    2: "West Amman",
    5: "West Amman",
    16: "West Amman",
    20: "West Amman",
    22: "West Amman",
    25: "West Amman",
    26: "West Amman",
    32: "West Amman",
    35: "West Amman",
    40: "West Amman",
    55: "West Amman",
    56: "West Amman",
    4: "North Jordan",
    14: "North Jordan",
    24: "North Jordan",
    29: "North Jordan",
    34: "North Jordan",
    37: "North Jordan",
    44: "North Jordan",
    45: "North Jordan",
    46: "North Jordan",
    65: "North Jordan",
}

# Sites with no cell-area and no coordinates — assigned manually.
MANUAL_SITE_AREAS: dict[str, str] = {
    "6008": "North Jordan",   # Jarash Festival Mobilecar
    "6068": "South Jordan",   # Karak Hashmiah Entrance
    "6069": "South Jordan",   # Tafilah Mansoura
    "6074": "North Jordan",   # Jarash Souf Elementary Sch
    "6086": "South Jordan",   # Wadi Rum Event
    "6150": "South Jordan",   # Tal Rumman Event
    "6484": "South Jordan",   # Ayla Event Stage 1
    "6485": "South Jordan",   # Aqaba Conference IBS Event
    "9999": "South Amman",    # Nokia Zain HQ
}

# Cell inventory short names → canonical areas used for table partitions.
_AREA_ALIASES: dict[str, str] = {
    "north": "North Jordan",
    "north jordan": "North Jordan",
    "zarqa": "East Jordan",
    "east jordan": "East Jordan",
    "east amman": "East Amman",
    "west amman": "West Amman",
    "south amman": "South Amman",
    "south jordan": "South Jordan",
}

CANONICAL_AREAS: tuple[str, ...] = (
    "East Amman",
    "East Jordan",
    "North Jordan",
    "South Amman",
    "South Jordan",
    "West Amman",
)

# Rows that cannot be routed (no metadata / no cluster map) land here.
UNKNOWN_AREA = "Unknown"

_CELL_AREA_SOURCES: tuple[tuple[str, str], ...] = (
    ("cells_2g", "site_id"),
    ("cells_3g", "nodeb_id"),
    ("cells_4g_fdd", "enb_id_actual"),
    ("cells_4g_tdd", "enb_id_actual"),
    ("cells_5g", "gnb_id_actual"),
)

_INDEX_CACHE: dict[str, Any] = {"_ts": 0.0, "map": {}}
_CELL_INDEX_CACHE: dict[str, Any] = {"_ts": 0.0, "map": {}}
_CACHE_TTL_SEC = 3600.0
_SITE_FROM_CELL_RE = re.compile(r"^(\d+)")


def canonicalize_area(value: str | None) -> str | None:
    """Normalize inventory / alias area names to the canonical PM partition set."""
    raw = str(value or "").strip()
    if not raw:
        return None
    mapped = _AREA_ALIASES.get(raw.lower())
    if mapped:
        return mapped
    # Title-case fallback if already one of the canonical labels.
    title = " ".join(part.capitalize() for part in raw.replace("_", " ").split())
    if title in CANONICAL_AREAS:
        return title
    return None


def normalize_site_id(site_id: Any) -> str:
    """
    Strip NetAct 5xxxx/6xxxx prefixes. Leaves short ids (e.g. UL 6001) untouched.
    """
    token = str(site_id or "").strip()
    if not token.isdigit():
        return token
    # Prefer digit-only form without leading zeros for cluster math, but keep
    # original length check on the trimmed token.
    value = int(token)
    if len(token) >= 5 and value >= 60000:
        return str(value - 60000)
    if len(token) >= 5 and value >= 50000:
        return str(value - 50000)
    # Drop leading zeros for consistency (0801 → 801) when purely numeric.
    return str(value)


def cluster_from_site_id(site_id: Any) -> int | None:
    canon = normalize_site_id(site_id)
    try:
        return int(canon) // 100
    except (TypeError, ValueError):
        return None


def derive_area_from_cluster_map(site_id: Any) -> str | None:
    cluster = cluster_from_site_id(site_id)
    if cluster is None:
        return None
    return CLUSTER_AREA.get(cluster)


def area_table_slug(area: str) -> str:
    """Filesystem/SQL-safe suffix: 'West Amman' → 'WEST_AMMAN'."""
    canon = canonicalize_area(area) or str(area or "").strip()
    slug = re.sub(r"[^A-Za-z0-9]+", "_", canon.upper()).strip("_")
    return slug or "UNKNOWN"


def pm_area_table_name(base_table: str, area: str) -> str:
    """e.g. 4G_CELLS_HOURLY + West Amman → 4G_CELLS_HOURLY__WEST_AMMAN"""
    return f"{base_table}__{area_table_slug(area)}"


def base_pm_table_name(table: str) -> str:
    """Strip area suffix: 4G_CELLS_HOURLY__WEST_AMMAN → 4G_CELLS_HOURLY."""
    name = str(table or "").strip()
    if "__" in name:
        return name.split("__", 1)[0]
    return name


def is_pm_partition_of(table: str, base_table: str) -> bool:
    """True for the monotable or any ``base__AREA`` partition."""
    t = str(table or "")
    b = str(base_table or "")
    if not t or not b:
        return False
    return t == b or t.startswith(f"{b}__")


def preferred_pm_table(base_table: str, site_id: Any, *, index: dict[str, str] | None = None) -> str:
    """
    Area partition name for a site. Unresolved sites → ``…__UNKNOWN``.
    Callers should fall back to the monotable if the partition is missing.
    """
    area = resolve_site_area(site_id, index=index) or UNKNOWN_AREA
    return pm_area_table_name(base_table, area)


def list_pm_partition_tables(existing_tables: list[str] | tuple[str, ...], base_table: str) -> list[str]:
    """Return monotable + area partitions for ``base_table`` (monotable first if present)."""
    matches = [t for t in existing_tables if is_pm_partition_of(t, base_table)]
    matches.sort(key=lambda n: (0 if n == base_table else 1, n))
    return matches


def site_id_from_cell_name(cell_name: Any) -> str | None:
    """Best-effort site id from a PM/metadata cell label (leading digits)."""
    m = _SITE_FROM_CELL_RE.match(str(cell_name or "").strip())
    return normalize_site_id(m.group(1)) if m else None


def _manual_area(site_id: Any) -> str | None:
    canon = normalize_site_id(site_id)
    raw = str(site_id or "").strip()
    return MANUAL_SITE_AREAS.get(canon) or MANUAL_SITE_AREAS.get(raw)


def _load_cell_site_area_votes() -> dict[str, Counter[str]]:
    votes: dict[str, Counter[str]] = {}
    conn = connect_metadata()
    try:
        for table, col in _CELL_AREA_SOURCES:
            sql = f"""
                SELECT TRIM(CAST({col} AS TEXT)) AS sid,
                       TRIM(COALESCE(area, '')) AS area,
                       COUNT(*) AS n
                FROM {table}
                WHERE NULLIF(TRIM(CAST({col} AS TEXT)), '') IS NOT NULL
                  AND NULLIF(TRIM(area), '') IS NOT NULL
                GROUP BY 1, 2
            """
            try:
                rows = execute_query(conn, sql, []).fetchall()
            except Exception:
                continue
            for row in rows:
                sid = normalize_site_id(row["sid"] if isinstance(row, dict) else row[0])
                area_raw = row["area"] if isinstance(row, dict) else row[1]
                n = int((row["n"] if isinstance(row, dict) else row[2]) or 0)
                area = canonicalize_area(str(area_raw or ""))
                if not sid or not area:
                    continue
                votes.setdefault(sid, Counter())[area] += n
    finally:
        conn.close()
    return votes


def build_site_area_index(*, force_refresh: bool = False) -> dict[str, str]:
    """
    Full site_id → canonical area map for routing PM rows into area tables.

    Priority per site: manual override → cluster map → dominant cell-table area.
    """
    now = time.time()
    cached = _INDEX_CACHE.get("map") or {}
    if (
        not force_refresh
        and cached
        and (now - float(_INDEX_CACHE.get("_ts") or 0.0)) < _CACHE_TTL_SEC
    ):
        return dict(cached)

    index: dict[str, str] = {}

    # Seed from all sites in metadata via cluster map / manual overrides.
    conn = connect_metadata()
    try:
        rows = execute_query(
            conn,
            "SELECT site_id FROM sites WHERE NULLIF(TRIM(CAST(site_id AS TEXT)), '') IS NOT NULL",
            [],
        ).fetchall()
        site_ids = [
            normalize_site_id(r["site_id"] if isinstance(r, dict) else r[0])
            for r in rows
        ]
    finally:
        conn.close()

    cell_votes = _load_cell_site_area_votes()

    for sid in site_ids:
        if not sid:
            continue
        manual = _manual_area(sid)
        if manual:
            index[sid] = manual
            continue
        mapped = derive_area_from_cluster_map(sid)
        if mapped:
            index[sid] = mapped
            continue
        votes = cell_votes.get(sid)
        if votes:
            index[sid] = votes.most_common(1)[0][0]

    # Ensure every manual entry is present even if missing from sites.
    for sid, area in MANUAL_SITE_AREAS.items():
        index[normalize_site_id(sid)] = area

    # Sites that only appear in cells (edge) still get a vote-based area.
    for sid, votes in cell_votes.items():
        if sid not in index and votes:
            index[sid] = votes.most_common(1)[0][0]

    _INDEX_CACHE["map"] = index
    _INDEX_CACHE["_ts"] = now
    return dict(index)


def resolve_site_area(site_id: Any, *, index: dict[str, str] | None = None) -> str | None:
    """Resolve one site_id to a canonical area (fast path for query routing)."""
    canon = normalize_site_id(site_id)
    if not canon:
        return None
    manual = _manual_area(canon)
    if manual:
        return manual
    mapped = derive_area_from_cluster_map(canon)
    if mapped:
        return mapped
    lookup = index if index is not None else build_site_area_index()
    return lookup.get(canon)


def build_cell_area_index(*, force_refresh: bool = False) -> dict[str, str]:
    """
    lower(trim(cell_name)) → canonical area for PM row routing.

    Built from metadata cell tables + ``resolve_site_area``.
    """
    now = time.time()
    cached = _CELL_INDEX_CACHE.get("map") or {}
    if (
        not force_refresh
        and cached
        and (now - float(_CELL_INDEX_CACHE.get("_ts") or 0.0)) < _CACHE_TTL_SEC
    ):
        return dict(cached)

    site_index = build_site_area_index(force_refresh=force_refresh)
    out: dict[str, str] = {}
    conn = connect_metadata()
    try:
        for table, site_col in _CELL_AREA_SOURCES:
            sql = f"""
                SELECT TRIM(CAST(cell_name AS TEXT)) AS cell_name,
                       TRIM(CAST({site_col} AS TEXT)) AS site_id
                FROM {table}
                WHERE NULLIF(TRIM(CAST(cell_name AS TEXT)), '') IS NOT NULL
            """
            try:
                rows = execute_query(conn, sql, []).fetchall()
            except Exception:
                continue
            for row in rows:
                cell = str(row["cell_name"] if isinstance(row, dict) else row[0] or "").strip()
                sid = row["site_id"] if isinstance(row, dict) else row[1]
                if not cell:
                    continue
                area = resolve_site_area(sid, index=site_index)
                if not area:
                    area = resolve_site_area(site_id_from_cell_name(cell), index=site_index)
                if area:
                    out[cell.lower()] = area
    finally:
        conn.close()

    _CELL_INDEX_CACHE["map"] = out
    _CELL_INDEX_CACHE["_ts"] = now
    return dict(out)


def resolve_cell_area(
    cell_name: Any,
    *,
    site_id: Any = None,
    cell_index: dict[str, str] | None = None,
    site_index: dict[str, str] | None = None,
) -> str:
    """
    Resolve a PM cell label to a canonical area.

    Order: explicit site_id → cell-name inventory map → leading digits as site_id → Unknown.
    """
    if site_id is not None and str(site_id).strip():
        area = resolve_site_area(site_id, index=site_index)
        if area:
            return area

    key = str(cell_name or "").strip().lower()
    if key:
        lookup = cell_index if cell_index is not None else build_cell_area_index()
        hit = lookup.get(key)
        if hit:
            return hit
        area = resolve_site_area(site_id_from_cell_name(cell_name), index=site_index)
        if area:
            return area
    return UNKNOWN_AREA


def list_canonical_areas() -> list[str]:
    return list(CANONICAL_AREAS)
