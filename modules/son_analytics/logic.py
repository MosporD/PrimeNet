"""SON recommendation engine — KPI clusters plus offline ML scores."""

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


def _ml():
    from modules.son_analytics.ml.infer import mean_anomaly, ml_status, score_map, top_cause

    return ml_status, score_map, top_cause, mean_anomaly


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


def _cluster_payload(
    *,
    key: str,
    title: str,
    summary: str,
    cells: list[dict],
    category: str,
    severity: str,
    extra_evidence: dict | None = None,
    scores: dict | None = None,
) -> dict:
    _status, _smap, top_cause, mean_anomaly = _ml()
    cell_names = [str(c.get("cell_name") or "") for c in cells if c.get("cell_name")]
    vendors: dict[str, int] = defaultdict(int)
    categories: dict[str, int] = defaultdict(int)
    locations = []
    for cell_row in cells:
        vendors[str(cell_row.get("vendor") or "—")] += 1
        categories[str(cell_row.get("category") or "KPI")] += 1
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
    primary_vendor = max(vendors.items(), key=lambda item: item[1])[0] if vendors else "—"
    avg_change = (
        sum(float(c.get("change_pct") or 0) for c in cells) / len(cells) if cells else 0.0
    )
    anomaly = mean_anomaly(cell_names, scores or {})
    cause_mix: dict[str, float] = defaultdict(float)
    for name in cell_names:
        row = (scores or {}).get(str(name).lower())
        if not row:
            continue
        for k, v in (row.get("cause_probs") or {}).items():
            cause_mix[k] += float(v or 0)
    if cause_mix:
        total = sum(cause_mix.values()) or 1.0
        cause_mix = {k: round(v / total, 3) for k, v in cause_mix.items()}
    top, top_p = top_cause(cause_mix)
    evidence = {
        "pm_scope": PM_DATA_SCOPE,
        "benchmark": "daily_vs_7day_avg",
        "cell_count": len(cells),
        "avg_change_pct": round(avg_change, 2),
        "avg_anomaly_score": round(anomaly, 2),
        "cause_probs": dict(cause_mix),
        "top_cause": top,
        "top_cause_p": round(top_p, 3),
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
                "anomaly_score": ((scores or {}).get(str(c.get("cell_name") or "").lower()) or {}).get("anomaly_score"),
            }
            for c in cells[:20]
        ],
    }
    if extra_evidence:
        evidence.update(extra_evidence)
    return {
        "id": _rec_id(category.lower(), key, str(len(cells))),
        "category": category,
        "severity": severity,
        "title": title,
        "summary": summary,
        "technology": cells[0].get("technology") if cells else "4G",
        "vendor": primary_vendor,
        "area": primary_area_for_cells(cell_names, get_cell_area_map()),
        "cells": cell_names,
        "anomaly_score": round(anomaly, 2),
        "evidence": evidence,
        "links": [
            {"label": "Network Health", "url": "/network-health"},
            {"label": "Network Map", "url": "/network-map"},
        ],
    }


def _build_geo_cluster_recommendations(degraded: list[dict], scores: dict[str, dict] | None = None) -> list[dict]:
    """Group degraded cells by spatial ML cluster when present, else by area."""
    scores = scores or {}
    by_key: dict[str, dict[str, dict]] = defaultdict(dict)
    key_meta: dict[str, dict] = {}

    for row in degraded:
        cell = str(row.get("cell_name") or "").strip()
        if not cell:
            continue
        ml = scores.get(cell.lower()) or {}
        spatial_id = str(ml.get("spatial_cluster_id") or "").strip()
        if spatial_id:
            key = f"spatial:{spatial_id}"
            key_meta[key] = {
                "spatial_cluster_id": spatial_id,
                "spatial_coherence": ml.get("spatial_coherence") or "",
                "area": str(row.get("area") or ""),
            }
        else:
            area = str(row.get("area") or "").strip()
            if not area:
                continue
            key = f"area:{area}"
            key_meta[key] = {"area": area, "spatial_cluster_id": "", "spatial_coherence": ""}
        existing = by_key[key].get(cell)
        if not existing or float(row.get("change_pct") or 0) > float(existing.get("change_pct") or 0):
            by_key[key][cell] = row

    out: list[dict] = []
    for key, cell_map in by_key.items():
        cells = list(cell_map.values())
        if len(cells) < cfg.SON_MIN_CLUSTER_CELLS:
            continue
        cells.sort(key=lambda x: -float(x.get("change_pct") or 0))
        meta = key_meta.get(key) or {}
        avg_change = sum(float(c.get("change_pct") or 0) for c in cells) / len(cells)
        severity = "High" if len(cells) >= 5 or avg_change >= 15 else "Medium"
        coherence = meta.get("spatial_coherence") or ""
        area = meta.get("area") or cells[0].get("area") or ""
        label = area or key
        if coherence:
            title = f"{coherence.capitalize()} degradation — {label} ({len(cells)} cells)"
        else:
            title = f"Area degradation — {label} ({len(cells)} cells)"
        hist = cells[0].get("history_days", 7)
        summary = (
            f"{len(cells)} cells in {label} degraded vs the prior {hist}-day average on daily PM KPIs."
        )
        if coherence:
            summary += f" Spatial pattern: {coherence}."
        rec = _cluster_payload(
            key=key,
            title=title,
            summary=summary,
            cells=cells,
            category="Cluster",
            severity=severity,
            extra_evidence={
                "area": area,
                "spatial_cluster_id": meta.get("spatial_cluster_id") or "",
                "spatial_coherence": coherence,
            },
            scores=scores,
        )
        rec["area"] = area
        out.append(rec)

    out.sort(
        key=lambda x: (
            _severity_rank(x.get("severity", "")),
            -float(x.get("anomaly_score") or 0),
            -len(x.get("cells") or []),
            -float((x.get("evidence") or {}).get("avg_change_pct") or 0),
        )
    )
    return out[: cfg.SON_TOP_CLUSTERS]


def _build_anomaly_recommendations(
    degraded: list[dict],
    scores: dict[str, dict],
    clustered_cells: set[str],
) -> list[dict]:
    from modules.son_analytics.ml import config as ml_cfg
    from modules.son_analytics.ml.infer import top_cause

    degraded_names = {str(r.get("cell_name") or "").strip().lower() for r in degraded}
    loc_map = get_cell_location_map()
    area_map = get_cell_area_map()
    out: list[dict] = []
    ranked = sorted(
        scores.values(),
        key=lambda r: -float(r.get("anomaly_score") or 0),
    )
    for row in ranked:
        cell = str(row.get("cell_name") or "").strip()
        if not cell:
            continue
        key = cell.lower()
        score = float(row.get("anomaly_score") or 0)
        if score < ml_cfg.ANOMALY_MIN_SCORE:
            continue
        if key in clustered_cells:
            continue
        loc = loc_map.get(cell) or {}
        cause, p = top_cause(row.get("cause_probs") or {})
        missed_by_wow = key not in degraded_names
        severity = "High" if score >= 90 else "Medium"
        title = f"Anomalous cell — {cell}"
        summary = (
            f"Behavior is unusual vs this cell's own {ml_cfg.LOOKBACK_DAYS}-day pattern "
            f"(anomaly {score:.0f}/100)."
        )
        if missed_by_wow:
            summary += " Week-over-week rules did not flag it (slow drift or always-bad)."
        if cause:
            summary += f" Likely cause: {cause} ({p:.0%})."
        top_kpis = row.get("top_kpis") or []
        out.append({
            "id": _rec_id("anomaly", cell, str(row.get("day") or "")),
            "category": "Anomaly",
            "severity": severity,
            "title": title,
            "summary": summary,
            "technology": row.get("rat") or "4G",
            "vendor": row.get("vendor") or "—",
            "area": area_map.get(cell) or loc.get("area") or "",
            "cells": [cell],
            "anomaly_score": score,
            "evidence": {
                "anomaly_score": score,
                "top_kpis": top_kpis,
                "cause_probs": row.get("cause_probs") or {},
                "model": row.get("model_name"),
                "fallback_used": bool(row.get("fallback_used")),
                "missed_by_wow": missed_by_wow,
                "day": row.get("day"),
                "latitude": loc.get("latitude"),
                "longitude": loc.get("longitude"),
            },
            "links": [
                {"label": "Network Health", "url": "/network-health"},
                {"label": "Sleeping Cells", "url": "/sleeping-cells"},
                {"label": "Capacity Hotspots", "url": "/capacity-hotspots"},
            ],
        })
        if len(out) >= 80:
            break
    return out


def _build_topology_recommendations(scores: dict[str, dict], clustered_cells: set[str]) -> list[dict]:
    from modules.son_analytics.ml import config as ml_cfg

    loc_map = get_cell_location_map()
    area_map = get_cell_area_map()
    out: list[dict] = []
    ranked = sorted(scores.values(), key=lambda r: -float(r.get("graph_score") or 0))
    for row in ranked:
        cell = str(row.get("cell_name") or "").strip()
        g = float(row.get("graph_score") or 0)
        if not cell or g < ml_cfg.TOPOLOGY_MIN_SCORE:
            continue
        if cell.lower() in clustered_cells:
            continue
        loc = loc_map.get(cell) or {}
        out.append({
            "id": _rec_id("topology", cell, str(row.get("day") or "")),
            "category": "Topology",
            "severity": "High" if g >= 80 else "Medium",
            "title": f"Neighbor-graph outlier — {cell}",
            "summary": (
                f"Handover neighborhood is inconsistent with this cell's KPI embedding "
                f"(graph score {g:.0f}/100). Check missing neighbors, distance, or HO SR."
            ),
            "technology": row.get("rat") or "4G",
            "vendor": row.get("vendor") or "—",
            "area": area_map.get(cell) or loc.get("area") or "",
            "cells": [cell],
            "anomaly_score": float(row.get("anomaly_score") or 0),
            "evidence": {
                "graph_score": g,
                "anomaly_score": row.get("anomaly_score"),
                "cause_probs": row.get("cause_probs") or {},
                "model": row.get("model_name"),
            },
            "links": [
                {"label": "Neighbor Quality", "url": "/neighbor-quality"},
                {"label": "Mobility Explorer", "url": "/mobility-explorer"},
            ],
        })
        if len(out) >= 40:
            break
    return out


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

    ml_status, score_map, _top_cause, _mean = _ml()
    status = ml_status()
    scores = score_map() if status.get("available") else {}

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
    clusters = _build_geo_cluster_recommendations(degraded, scores)

    clustered_cells: set[str] = set()
    for rec in clusters:
        cells = rec.get("cells") or []
        clustered_cells.update(str(c).strip().lower() for c in cells)
        if not rec.get("area"):
            rec["area"] = primary_area_for_cells(cells, get_cell_area_map())

    anomalies = _build_anomaly_recommendations(degraded, scores, clustered_cells) if scores else []
    topology = _build_topology_recommendations(scores, clustered_cells) if scores else []
    recommendations = clusters + anomalies + topology
    recommendations.sort(
        key=lambda x: (
            _severity_rank(x.get("severity", "")),
            -float(x.get("anomaly_score") or 0),
            -len(x.get("cells") or []),
        )
    )

    payload = {
        "generated_at": _utc_now_iso(),
        "stage": "ml" if status.get("available") else "rules",
        "pm_data_scope": PM_DATA_SCOPE,
        "benchmark": "daily_vs_7day_avg",
        "ml": {
            "available": bool(status.get("available")),
            "built_at": status.get("built_at"),
            "latest_day": status.get("latest_day"),
            "score_count": status.get("score_count") or 0,
            "is_stale": bool(status.get("is_stale")),
            "disabled": bool(status.get("disabled")),
        },
        "summary": {
            "cluster": len(clusters),
            "anomaly": len(anomalies),
            "topology": len(topology),
            "degraded_cells": len(degraded),
            "total": len(recommendations),
        },
        "recommendations": recommendations,
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
    counts = {
        "cluster": 0,
        "anomaly": 0,
        "topology": 0,
        "degraded_cells": int((payload.get("summary") or {}).get("degraded_cells") or 0),
    }
    for r in rows:
        key = str(r.get("category") or "").lower()
        if key in counts:
            counts[key] += 1
    counts["total"] = total
    return counts
