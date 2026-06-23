"""SON recommendation engine — KPI + geographic clusters (development stage)."""



from __future__ import annotations



import hashlib

import time

from collections import defaultdict

from datetime import datetime, timezone



from modules.network_health.config import CATEGORY_PRESETS



from . import config as cfg

from .area_helpers import (

    get_cell_area_map,

    get_cell_location_map,

    normalize_area,

    primary_area_for_cells,

    recommendation_matches_area,

)

from .pm_helpers import PM_DATA_SCOPE, collect_degraded_cells



_SON_CACHE: dict[str, dict] = {}





def _utc_now_iso() -> str:

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()





def _rec_id(*parts: str) -> str:

    raw = "|".join(str(p) for p in parts)

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]





def _severity_rank(sev: str) -> int:

    s = str(sev or "").lower()

    if s == "high":

        return 0

    if s == "medium":

        return 1

    if s == "low":

        return 2

    return 3





def _attach_location_context(rows: list[dict]) -> list[dict]:

    area_map = get_cell_area_map()

    loc_map = get_cell_location_map()

    enriched: list[dict] = []

    for row in rows:

        cell = str(row.get("cell_name") or "").strip()

        item = dict(row)

        item["area"] = area_map.get(cell, "")

        loc = loc_map.get(cell) or {}

        item["latitude"] = loc.get("latitude")

        item["longitude"] = loc.get("longitude")

        item["site_id"] = loc.get("site_id")

        enriched.append(item)

    return enriched





def _build_geo_cluster_recommendations(degraded: list[dict]) -> list[dict]:

    """Group degraded cells by geographic area when enough cells correlate."""

    by_area: dict[str, dict[str, dict]] = defaultdict(dict)



    for row in degraded:

        area = str(row.get("area") or "").strip()

        if not area:

            continue

        cell = str(row.get("cell_name") or "").strip()

        if not cell:

            continue

        existing = by_area[area].get(cell)

        if not existing or float(row.get("change_pct") or 0) > float(existing.get("change_pct") or 0):

            by_area[area][cell] = row



    out: list[dict] = []

    for area, cell_map in by_area.items():

        cells = list(cell_map.values())

        if len(cells) < cfg.SON_MIN_CLUSTER_CELLS:

            continue



        cells.sort(key=lambda x: -float(x.get("change_pct") or 0))

        categories: dict[str, int] = defaultdict(int)

        vendors: dict[str, int] = defaultdict(int)

        for cell_row in cells:

            categories[str(cell_row.get("category") or "KPI")] += 1

            vendors[str(cell_row.get("vendor") or "—")] += 1



        avg_change = sum(float(c.get("change_pct") or 0) for c in cells) / len(cells)

        top_category = max(categories.items(), key=lambda item: item[1])[0]

        primary_vendor = max(vendors.items(), key=lambda item: item[1])[0]

        severity = "High" if len(cells) >= 5 or avg_change >= 15 else "Medium"



        locations = []

        for cell_row in cells[:25]:

            lat = cell_row.get("latitude")

            lng = cell_row.get("longitude")

            if lat is None or lng is None:

                continue

            locations.append({

                "cell_name": cell_row.get("cell_name"),

                "latitude": lat,

                "longitude": lng,

                "category": cell_row.get("category"),

                "change_pct": cell_row.get("change_pct"),

            })



        cell_names = [str(c.get("cell_name") or "") for c in cells if c.get("cell_name")]

        out.append({

            "id": _rec_id("cluster", area, top_category, str(len(cells))),

            "category": "Cluster",

            "severity": severity,

            "title": f"Area degradation — {area} ({len(cells)} cells)",

            "summary": (

                f"{len(cells)} cells in {area} degraded vs the prior "

                f"{cells[0].get('history_days', 7)}-day average on daily PM KPIs. "

                f"Top issue: {top_category}."

            ),

            "technology": cells[0].get("technology") or "4G",

            "vendor": primary_vendor,

            "area": area,

            "cells": cell_names,

            "evidence": {

                "pm_scope": PM_DATA_SCOPE,

                "benchmark": "daily_vs_7day_avg",

                "area": area,

                "cell_count": len(cells),

                "avg_change_pct": round(avg_change, 2),

                "categories": dict(categories),

                "locations": locations,

                "cells_detail": [

                    {

                        "cell_name": c.get("cell_name"),

                        "category": c.get("category"),

                        "kpi_column": c.get("kpi_column"),

                        "today_value": c.get("today_value"),

                        "week_avg": c.get("week_avg"),

                        "change_pct": c.get("change_pct"),

                        "latest_day": c.get("latest_day"),

                        "latitude": c.get("latitude"),

                        "longitude": c.get("longitude"),

                    }

                    for c in cells[:20]

                ],

            },

            "links": [

                {"label": "Network Health", "url": "/network-health"},

                {"label": "Network Map", "url": "/network-map"},

            ],

        })



    out.sort(

        key=lambda x: (

            _severity_rank(x.get("severity", "")),

            -len(x.get("cells") or []),

            -float((x.get("evidence") or {}).get("avg_change_pct") or 0),

        )

    )

    return out[: cfg.SON_TOP_CLUSTERS]





def build_all_recommendations(*, force_refresh: bool = False) -> dict:

    cache_key = "all"

    now = time.time()

    cached = _SON_CACHE.get(cache_key)

    if (

        not force_refresh

        and cached

        and (now - float(cached.get("_ts", 0))) < cfg.CACHE_TTL_SECONDS

    ):

        return cached["payload"]



    from modules.network_health import config as nh_cfg



    degraded = collect_degraded_cells(

        CATEGORY_PRESETS,

        vendor="all",

        technology="4G",

        scope=PM_DATA_SCOPE,

        lookback_days=nh_cfg.WOW_LOOKBACK_DAYS,

        min_history_days=nh_cfg.WOW_MIN_HISTORY_DAYS,

        degradation_pct=nh_cfg.WOW_DEGRADATION_PCT,

        min_absolute_delta=nh_cfg.WOW_MIN_ABSOLUTE_DELTA,

    )

    degraded = _attach_location_context(degraded)

    clusters = _build_geo_cluster_recommendations(degraded)



    for rec in clusters:

        cells = rec.get("cells") or []

        if not rec.get("area"):

            rec["area"] = primary_area_for_cells(cells, get_cell_area_map())



    payload = {

        "generated_at": _utc_now_iso(),

        "stage": "development",

        "pm_data_scope": PM_DATA_SCOPE,

        "benchmark": "daily_vs_7day_avg",

        "summary": {

            "cluster": len(clusters),

            "degraded_cells": len(degraded),

            "total": len(clusters),

        },

        "recommendations": clusters,

    }

    _SON_CACHE[cache_key] = {"_ts": now, "payload": payload}

    return payload





def filter_recommendations(

    payload: dict,

    *,

    category: str | None = None,

    severity: str | None = None,

    vendor: str | None = None,

    technology: str | None = None,

    area: str | None = None,

    limit: int = 50,

    offset: int = 0,

) -> tuple[list[dict], int]:

    rows = list(payload.get("recommendations") or [])

    cat = (category or "").strip().upper()

    sev = (severity or "").strip().lower()

    ven = (vendor or "").strip().lower()

    tech = (technology or "").strip().upper()

    area_f = normalize_area(area)

    cell_map = get_cell_area_map() if area_f else {}



    if cat and cat != "ALL":

        rows = [r for r in rows if str(r.get("category", "")).upper() == cat]

    if sev and sev != "all":

        rows = [r for r in rows if str(r.get("severity", "")).lower() == sev]

    if ven and ven != "all":

        rows = [r for r in rows if ven in str(r.get("vendor", "")).lower()]

    if tech and tech != "ALL":

        rows = [r for r in rows if tech in str(r.get("technology", "")).upper()]

    if area_f:

        rows = [r for r in rows if recommendation_matches_area(r, area_f, cell_map)]



    total = len(rows)

    start = max(0, offset)

    end = start + max(1, min(limit, 200))

    return rows[start:end], total





def get_recommendation_by_id(payload: dict, rec_id: str) -> dict | None:

    rid = str(rec_id or "").strip()

    for r in payload.get("recommendations") or []:

        if str(r.get("id")) == rid:

            return r

    return None





def filtered_summary(

    payload: dict,

    *,

    category: str | None = None,

    severity: str | None = None,

    vendor: str | None = None,

    technology: str | None = None,

    area: str | None = None,

) -> dict:

    rows, total = filter_recommendations(

        payload,

        category=category,

        severity=severity,

        vendor=vendor,

        technology=technology,

        area=area,

        limit=100000,

        offset=0,

    )

    counts = {"cluster": 0, "degraded_cells": int((payload.get("summary") or {}).get("degraded_cells") or 0)}

    for r in rows:

        key = str(r.get("category") or "").lower()

        if key in counts:

            counts[key] += 1

        elif key == "cluster":

            counts["cluster"] += 1

    counts["total"] = total

    return counts

