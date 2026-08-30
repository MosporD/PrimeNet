"""Network Health Scorecard logic — precomputed KPI tables plus category targets."""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

from core.radio.scoring import bounded_score, breached_threshold, score_vs_preset
from modules.son_analytics.area_helpers import (
    as_cluster_int,
    cell_in_area,
    cell_in_cluster,
    cell_in_rat,
    clusters_for_area,
    get_cell_area_map,
    get_cell_location_map,
    get_cell_technology_map,
    normalize_area,
    resolve_cell_cluster,
)
from modules.son_analytics.pm_helpers import (
    PM_DATA_SCOPE,
    _cell_kpi_hourly_series,
    _single_cell_daily_kpi_series,
    _table_columns,
    collect_all_kpi_benchmarks,
    collect_degraded_cells,
    parse_pm_timestamp,
    resolve_kpi_column,
    vendor_pm_sources,
)

from . import config as cfg

_HEALTH_CACHE: dict[str, dict] = {}
_KPI_CACHE: dict[str, object] = {"_ts": 0.0, "data": {}}
_TREND_CACHE: dict[str, tuple[float, dict]] = {}
_TABLE_CACHE: dict[str, tuple[float, dict[str, list[dict]]]] = {}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _infer_rnc(cell_name: str, site_name: str = "") -> str:
    text = str(cell_name or "")
    m = re.search(r"RNC[-\s]?(\d+)", text, re.I)
    if m:
        return f"RNC{m.group(1)}"
    site = str(site_name or "").strip()
    if site:
        return site
    return ""


def _metadata_rat_filter(rat: str) -> str | None:
    return cfg.metadata_technology_for_rat(rat)


def _enrich_benchmark_rows(
    rows: list[dict],
    *,
    area: str = "",
    cluster: int | None = None,
    rat: str = "",
) -> list[dict]:
    cell_map = get_cell_area_map()
    loc_map = get_cell_location_map()
    tech_map = get_cell_technology_map()
    meta_rat = _metadata_rat_filter(rat)
    enriched: list[dict] = []

    for row in rows:
        cell = str(row.get("cell_name") or "").strip()
        if area and not cell_in_area(cell, area, cell_map):
            continue
        if not cell_in_cluster(cell, cluster, loc_map):
            continue
        if meta_rat and not cell_in_rat(cell, meta_rat, tech_map):
            continue

        loc = loc_map.get(cell) or {}
        item = dict(row)
        item["area"] = cell_map.get(cell, loc.get("area") or "")
        item["cluster"] = resolve_cell_cluster(cell, loc)
        item["site_id"] = loc.get("site_id")
        item["rnc"] = str(loc.get("controller") or "").strip() or _infer_rnc(
            cell, str(loc.get("site_name") or "")
        )
        item["pm_data_scope"] = PM_DATA_SCOPE
        item["value"] = row.get("today_value")
        item["benchmark"] = "daily_vs_7day_avg"
        item["pre"] = row.get("week_avg")
        item["post"] = row.get("today_value")
        cat_name = str(row.get("category") or "")
        preset = cfg.CATEGORY_PRESETS.get(cat_name) or {}
        if not preset:
            matched = cfg.match_category(str(row.get("kpi_column") or row.get("kpi") or ""))
            preset = cfg.CATEGORY_PRESETS.get(matched or "", {})
        prior_score = item.get("score")
        item.update(_threshold_fields(item.get("post"), preset))
        if prior_score is not None:
            item["score"] = prior_score
        elif item.get("score") is None:
            item["score"] = item.get("target_score") or round(abs(float(row.get("delta") or 0)), 3)
        enriched.append(item)

    return enriched


def _backfill_row_meta(rows: list[dict]) -> list[dict]:
    """Fill cluster / RNC-BSC on precalc rows (store currently writes those as NULL)."""
    if not rows:
        return rows
    loc_map = get_cell_location_map()
    for row in rows:
        cell = str(row.get("cell_name") or "").strip()
        loc = loc_map.get(cell) or {}
        row["cluster"] = as_cluster_int(row.get("cluster")) or resolve_cell_cluster(cell, loc)
        if not str(row.get("rnc") or "").strip():
            row["rnc"] = str(loc.get("controller") or "").strip()
        if not str(row.get("area") or "").strip():
            row["area"] = str(loc.get("area") or "")
    return rows


def _slim_table_row(row: dict) -> dict:
    return {
        "cell_name": row.get("cell_name"),
        "pre": row.get("pre"),
        "post": row.get("post"),
        "delta": row.get("delta"),
        "area": row.get("area"),
        "cluster": row.get("cluster"),
        "rnc": row.get("rnc"),
        "vendor": row.get("vendor"),
        "breached": row.get("breached"),
        "vs_threshold": row.get("vs_threshold"),
        "threshold_bad": row.get("threshold_bad"),
        "direction": row.get("direction"),
        "score": row.get("score"),
        "category": row.get("category"),
    }


def _threshold_fields(value: object, preset: dict | None) -> dict:
    if not preset:
        return {}
    target_score = score_vs_preset(value, preset)
    return {
        "direction": preset.get("direction"),
        "threshold_bad": preset.get("threshold_bad"),
        "breached": breached_threshold(
            value,
            direction=str(preset.get("direction") or "higher_worse"),
            threshold_bad=preset.get("threshold_bad"),
        ),
        "vs_threshold": _vs_threshold_delta(value, preset),
        "target_score": target_score,
        "score": target_score,
    }


def _vs_threshold_delta(value: object, preset: dict) -> float | None:
    try:
        val = float(value)
        thr = float(preset.get("threshold_bad"))
    except (TypeError, ValueError):
        return None
    if str(preset.get("direction") or "").strip().lower() == "lower_worse":
        return round(val - thr, 3)
    return round(val - thr, 3)


def _annotate_threshold_rows(rows: list[dict], kpi: str) -> list[dict]:
    cat = cfg.match_category(kpi)
    preset = cfg.CATEGORY_PRESETS.get(cat or "", {})
    if not preset:
        return rows
    out: list[dict] = []
    for row in rows:
        item = dict(row)
        post = item.get("post") if item.get("post") is not None else item.get("today_value")
        fields = _threshold_fields(post, preset)
        fields["category"] = cat
        wow = 0.0
        if item.get("degraded"):
            wow = min(30.0, abs(float(item.get("change_pct") or item.get("delta") or 0)) * 0.4)
        fields["score"] = bounded_score(fields.get("target_score") or 0, wow)
        item.update(fields)
        out.append(item)
    return out


def _match_kpi_name(available: list[str], hint: str) -> str | None:
    """Resolve a KPI hint to an available PM column name."""
    needle = str(hint or "").strip().lower()
    if not needle:
        return None
    for col in available:
        if col.lower() == needle:
            return col
    for col in available:
        c = col.lower()
        if needle in c or c in needle:
            return col
    return None


def _category_preset_aliases() -> list[str]:
    aliases: list[str] = []
    for preset in cfg.CATEGORY_PRESETS.values():
        for alias in preset.get("aliases") or []:
            name = str(alias or "").strip()
            if name:
                aliases.append(name)
    return aliases


def resolve_precompute_kpis(all_kpis: list[str]) -> list[str]:
    """Pick a bounded shortlist of KPIs to pre-calculate for fast initial load."""
    if not all_kpis:
        return []

    hints: list[str] = []
    hints.extend(cfg.PRECOMPUTE_KPI_NAMES)
    hints.extend(_category_preset_aliases())

    chosen: list[str] = []
    seen: set[str] = set()
    max_n = max(1, int(cfg.PRECOMPUTE_KPI_MAX))

    for hint in hints:
        if len(chosen) >= max_n:
            break
        match = _match_kpi_name(all_kpis, hint)
        if match and match not in seen:
            seen.add(match)
            chosen.append(match)

    for kpi in all_kpis:
        if len(chosen) >= max_n:
            break
        if kpi not in seen:
            seen.add(kpi)
            chosen.append(kpi)

    return chosen


def get_precomputed_table(
    vendor: str,
    rat: str,
    *,
    kpi: str | None = None,
    slim: bool = True,
) -> dict:
    """Read pre/post/delta from SQLite.

    Per cell per KPI: pre = mean of prior 7 daily values, post = latest day,
    delta = post - pre. Batch job writes nh_cell_row; UI loads one KPI at a time.
    """
    from .precalc_store import get_build_meta, load_kpi_rows, load_precalc_meta

    meta_pack = load_precalc_meta(vendor, rat)
    if meta_pack:
        row_count = int(meta_pack.get("row_count") or 0)
        has_rows = bool(meta_pack.get("has_rows"))
        out: dict = {
            "tables": {},
            "precomputed_kpis": list(meta_pack.get("precomputed_kpis") or []),
            "total_kpi_count": int(meta_pack.get("total_kpi_count") or 0),
            "precalc_ready": has_rows,
            "precalc_empty": not has_rows,
            "precalc_stale": bool(meta_pack.get("is_stale")),
            "precalc_built_at": meta_pack.get("built_at"),
            "precalc_row_count": row_count,
        }
        if kpi:
            rows = load_kpi_rows(vendor, rat, kpi)
            if slim:
                rows = [_slim_table_row(r) for r in rows]
            out["tables"] = {kpi: rows}
        return out

    meta = get_build_meta(vendor, rat)
    stale = bool(meta and meta.get("is_stale"))

    if cfg.PRECOMPUTE_ALLOW_RUNTIME_BUILD:
        return _compute_precomputed_table_runtime(vendor, rat, slim=slim)

    return {
        "tables": {},
        "precomputed_kpis": [],
        "total_kpi_count": len(list_kpi_columns(vendor, rat)),
        "precalc_ready": False,
        "precalc_stale": stale,
        "precalc_built_at": meta.get("built_at") if meta else None,
    }


def _compute_precomputed_table_runtime(
    vendor: str,
    rat: str,
    *,
    slim: bool = True,
) -> dict:
    """Fallback: compute in-process (slow; disabled unless NH_PRECALC_RUNTIME_BUILD=1)."""
    cache_key = f"{vendor}|{rat}|shortlist"
    now = time.time()
    cached = _TABLE_CACHE.get(cache_key)
    if cached and (now - cached[0]) < cfg.CACHE_TTL_SECONDS:
        payload = cached[1]
        tables = payload.get("tables") or {}
        if slim:
            tables = {k: [_slim_table_row(r) for r in v] for k, v in tables.items()}
        out = {
            "tables": tables,
            "precomputed_kpis": list(payload.get("precomputed_kpis") or []),
            "total_kpi_count": int(payload.get("total_kpi_count") or 0),
            "precalc_ready": True,
            "precalc_runtime": True,
        }
        return out

    all_kpis = list_kpi_columns(vendor, rat)
    if not all_kpis:
        empty = {
            "tables": {},
            "precomputed_kpis": [],
            "total_kpi_count": 0,
            "precalc_ready": False,
        }
        _TABLE_CACHE[cache_key] = (now, empty)
        return empty

    kpi_columns = resolve_precompute_kpis(all_kpis)
    pm_tech = cfg.pm_technology_for_rat(rat)
    raw = collect_all_kpi_benchmarks(
        kpi_columns,
        vendor=vendor,
        technology=pm_tech,
        scope=PM_DATA_SCOPE,
        lookback_days=cfg.WOW_LOOKBACK_DAYS,
        min_history_days=cfg.WOW_MIN_HISTORY_DAYS,
        no_change_threshold=cfg.WOW_NO_CHANGE_THRESHOLD,
    )

    tables: dict[str, list[dict]] = {}
    for kpi, rows in raw.items():
        tables[kpi] = _enrich_benchmark_rows(rows, rat=rat)

    payload = {
        "tables": tables,
        "precomputed_kpis": kpi_columns,
        "total_kpi_count": len(all_kpis),
    }
    _TABLE_CACHE[cache_key] = (now, payload)

    out_tables = payload["tables"]
    if slim:
        out_tables = {k: [_slim_table_row(r) for r in v] for k, v in out_tables.items()}
    return {
        "tables": out_tables,
        "precomputed_kpis": kpi_columns,
        "total_kpi_count": len(all_kpis),
        "precalc_ready": True,
        "precalc_runtime": True,
    }


def list_kpi_columns(vendor: str, rat: str) -> list[str]:
    """KPI column names with PM data for the selected vendor + RAT (daily scope)."""
    cache_key = f"{vendor}|{rat}|nh_kpi_v3"
    now = time.time()
    cached = _KPI_CACHE.get("data") or {}
    if (
        cache_key in cached
        and (now - float(_KPI_CACHE.get("_ts", 0))) < cfg.CACHE_TTL_SECONDS
    ):
        return list(cached[cache_key])

    from modules.performance.routes import (
        _drop_duplicate_kpis,
        _get_pm_cols_for_table,
    )

    pm_tech = cfg.pm_technology_for_rat(rat)
    sources = vendor_pm_sources(vendor, pm_tech, PM_DATA_SCOPE)
    if not sources:
        return []

    merged: list[str] = []
    seen: set[str] = set()
    for _vlabel, db_path, table in sources:
        if not db_path or not table:
            continue
        for col in _get_pm_cols_for_table(db_path, table):
            name = str(col or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            merged.append(name)

    out = _drop_duplicate_kpis(sorted(merged, key=lambda s: s.lower()))
    from .kpi_filter import filter_network_health_kpis, is_metadata_kpi

    out = filter_network_health_kpis(out, exclude_percentage=cfg.EXCLUDE_PERCENTAGE_KPIS)
    if cfg.EXCLUDE_PERCENTAGE_KPIS:
        restored = [
            col for col in merged
            if cfg.match_category(col) and not is_metadata_kpi(col)
        ]
        if restored:
            out = _drop_duplicate_kpis(sorted(set(out) | set(restored), key=lambda s: s.lower()))
    data = dict(cached)
    data[cache_key] = out
    _KPI_CACHE["data"] = data
    _KPI_CACHE["_ts"] = now
    return out


def _pre_post_values(row: dict) -> tuple[float | None, float | None]:
    pre = row.get("pre") if row.get("pre") is not None else row.get("week_avg")
    post = row.get("post") if row.get("post") is not None else row.get("today_value")
    try:
        pre_f = float(pre) if pre is not None else None
    except (TypeError, ValueError):
        pre_f = None
    try:
        post_f = float(post) if post is not None else None
    except (TypeError, ValueError):
        post_f = None
    return pre_f, post_f


def _is_no_change_row(row: dict, *, tolerance: float | None = None) -> bool:
    pre, post = _pre_post_values(row)
    if pre is None or post is None:
        return False
    if tolerance is None:
        return round(pre, 2) == round(post, 2)
    return abs(pre - post) <= tolerance


def _sort_kpi_cell_rows(rows: list[dict], sort_mode: str) -> list[dict]:
    mode = (sort_mode or "increased").strip().lower()
    if mode == "decreased":
        rows.sort(
            key=lambda x: (
                float(x.get("delta") or 0),
                str(x.get("cell_name") or ""),
            )
        )
    elif mode == "no_change":
        rows.sort(
            key=lambda x: (
                0 if _is_no_change_row(x) else 1,
                abs(float(x.get("delta") or 0)),
                str(x.get("cell_name") or ""),
            )
        )
    else:
        rows.sort(
            key=lambda x: (
                -float(x.get("delta") or 0),
                str(x.get("cell_name") or ""),
            )
        )
    return rows


def get_kpi_cells(
    kpi_column: str,
    *,
    vendor: str = "nokia",
    rat: str = "3G",
    area: str = "",
    cluster: int | None = None,
    sort_mode: str | None = None,
    top_n: int = 200,
) -> list[dict]:
    from .precalc_store import load_kpi_rows, load_precalc_meta

    rows: list[dict] = []
    if load_precalc_meta(vendor, rat):
        sql_limit = None if top_n >= 50000 else top_n
        rows = [
            dict(r)
            for r in load_kpi_rows(
                vendor,
                rat,
                kpi_column,
                area=area,
                cluster=None,
                limit=sql_limit if cluster is None else None,
            )
        ]
    elif cfg.PRECOMPUTE_ALLOW_RUNTIME_BUILD:
        cache_key = f"{vendor}|{rat}|shortlist"
        cached = _TABLE_CACHE.get(cache_key)
        tables: dict[str, list[dict]] = {}
        if cached:
            tables = (cached[1] or {}).get("tables") or {}
        if kpi_column in tables:
            rows = [dict(r) for r in tables[kpi_column]]
        else:
            pm_tech = cfg.pm_technology_for_rat(rat)
            raw = collect_all_kpi_benchmarks(
                [kpi_column],
                vendor=vendor,
                technology=pm_tech,
                scope=PM_DATA_SCOPE,
                lookback_days=cfg.WOW_LOOKBACK_DAYS,
                min_history_days=cfg.WOW_MIN_HISTORY_DAYS,
                no_change_threshold=cfg.WOW_NO_CHANGE_THRESHOLD,
            )
            rows = _enrich_benchmark_rows(raw.get(kpi_column, []), rat=rat)

    _backfill_row_meta(rows)
    if area:
        rows = [r for r in rows if str(r.get("area") or "") == area]
    if cluster is not None:
        want = int(cluster)
        rows = [r for r in rows if as_cluster_int(r.get("cluster")) == want]
    rows = _annotate_threshold_rows(rows, kpi_column)
    if (sort_mode or "").strip():
        rows = _sort_kpi_cell_rows(rows, sort_mode)
    else:
        rows.sort(key=lambda x: str(x.get("cell_name") or ""))
    return rows[: max(1, min(50_000, int(top_n or 200)))]


def get_clusters(area: str = "") -> list[int]:
    return clusters_for_area(area or None)


def _linear_trend(values: list[float]) -> list[float]:
    n = len(values)
    if n < 2:
        return list(values)
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(values) / n
    num = sum((xs[i] - x_mean) * (values[i] - y_mean) for i in range(n))
    den = sum((x - x_mean) ** 2 for x in xs) or 1.0
    slope = num / den
    intercept = y_mean - slope * x_mean
    return [round(intercept + slope * x, 2) for x in xs]


def _aggregate_hourly_to_daily(pts: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Average hourly points into daily buckets (oldest first)."""
    buckets: dict[str, list[float]] = {}
    for ts_raw, val in pts:
        day = parse_pm_timestamp(ts_raw)
        if not day:
            continue
        buckets.setdefault(day, []).append(val)
    return sorted((day, sum(vals) / len(vals)) for day, vals in buckets.items())


def _filter_points_last_days(
    pts: list[tuple[str, float]],
    days: int,
) -> list[tuple[str, float]]:
    if not pts or days <= 0:
        return pts

    parsed: list[tuple[datetime, str, float]] = []
    for ts_raw, val in pts:
        day = parse_pm_timestamp(ts_raw)
        if not day:
            continue
        try:
            dt = datetime.strptime(day[:10], "%Y-%m-%d")
        except ValueError:
            continue
        parsed.append((dt, ts_raw, val))
    if not parsed:
        return pts
    latest = max(p[0] for p in parsed)
    cutoff = latest - timedelta(days=int(days))
    return [(ts, val) for dt, ts, val in parsed if dt >= cutoff]


def get_cell_trend_payload(
    cell_name: str,
    kpi_column: str,
    *,
    vendor: str = "nokia",
    rat: str = "3G",
) -> dict | None:
    pm_tech = cfg.pm_technology_for_rat(rat)
    cache_key = f"{vendor}|{rat}|{cell_name}|{kpi_column}"
    now = time.time()
    cached = _TREND_CACHE.get(cache_key)
    if cached and (now - cached[0]) < cfg.CACHE_TTL_SECONDS:
        return dict(cached[1])

    daily_series: list[dict] = []
    hourly_series: list[dict] = []
    resolved_vendor = vendor
    daily_by_day: dict[str, float] = {}
    hourly_by_ts: dict[str, float] = {}

    for vlabel, db_path, table in vendor_pm_sources(vendor, pm_tech, PM_DATA_SCOPE):
        if kpi_column not in _table_columns(db_path, table):
            if not resolve_kpi_column(db_path, table, [kpi_column]):
                continue
        series = _single_cell_daily_kpi_series(
            db_path, table, cell_name, kpi_column, lookback_days=21, fuzzy=False,
        )
        if not series:
            continue
        resolved_vendor = vlabel
        for day, val in series:
            daily_by_day[day] = val

    if not daily_by_day:
        for vlabel, db_path, table in vendor_pm_sources(vendor, pm_tech, PM_DATA_SCOPE):
            series = _single_cell_daily_kpi_series(
                db_path, table, cell_name, kpi_column, lookback_days=21, fuzzy=True,
            )
            if not series:
                continue
            resolved_vendor = vlabel
            for day, val in series:
                daily_by_day[day] = val

    if daily_by_day:
        ordered = sorted(daily_by_day.items())[-21:]
        daily_values = [val for _, val in ordered]
        linear = _linear_trend(daily_values)
        daily_series = [
            {
                "day": day,
                "value": round(val, 2),
                "linear": linear[i] if i < len(linear) else round(val, 2),
            }
            for i, (day, val) in enumerate(ordered)
        ]

    for vlabel, db_path, table in vendor_pm_sources(vendor, pm_tech, "hourly"):
        pts = _cell_kpi_hourly_series(
            db_path, table, cell_name, kpi_column, max_points=336, fuzzy=False,
        )
        if not pts:
            continue
        resolved_vendor = vlabel
        for ts, val in pts:
            hourly_by_ts[ts] = val

    if not hourly_by_ts:
        for vlabel, db_path, table in vendor_pm_sources(vendor, pm_tech, "hourly"):
            pts = _cell_kpi_hourly_series(
                db_path, table, cell_name, kpi_column, max_points=336, fuzzy=True,
            )
            if not pts:
                continue
            resolved_vendor = vlabel
            for ts, val in pts:
                hourly_by_ts[ts] = val

    hourly_pts: list[tuple[str, float]] = sorted(hourly_by_ts.items())

    if hourly_pts:
        if not daily_series:
            daily_pts = _aggregate_hourly_to_daily(hourly_pts)
            daily_pts = daily_pts[-21:]
            d_values = [val for _, val in daily_pts]
            d_linear = _linear_trend(d_values)
            daily_series = [
                {
                    "day": day,
                    "value": round(val, 2),
                    "linear": d_linear[i] if i < len(d_linear) else round(val, 2),
                }
                for i, (day, val) in enumerate(daily_pts)
            ]

        hourly_pts = _filter_points_last_days(hourly_pts, days=8)
        h_values = [val for _, val in hourly_pts]
        h_linear = _linear_trend(h_values)
        hourly_series = [
            {
                "timestamp": ts,
                "value": round(val, 2),
                "linear": h_linear[i] if i < len(h_linear) else round(val, 2),
            }
            for i, (ts, val) in enumerate(hourly_pts)
        ]

    if not daily_series and not hourly_series:
        return None

    payload = {
        "cell_name": cell_name,
        "kpi_column": kpi_column,
        "kpi_label": kpi_column,
        "vendor": resolved_vendor,
        "rat": rat,
        "technology": pm_tech,
        "daily": daily_series,
        "hourly": hourly_series,
    }
    _TREND_CACHE[cache_key] = (now, payload)
    return payload


# Category scorecard (operator threshold_bad per KPI family)
def get_category_scorecard(
    vendor: str,
    rat: str,
    *,
    area: str = "",
    cluster: int | None = None,
    top_n: int = 8,
) -> dict:
    """Worst cells vs operator targets, read from the precalc store when available."""
    columns = list_kpi_columns(vendor, rat)
    categories: list[dict] = []
    summary: dict[str, int] = {}
    by_name: dict[str, list[dict]] = {}
    for cat_name, preset in cfg.CATEGORY_PRESETS.items():
        kpi = None
        for alias in preset.get("aliases") or []:
            kpi = _match_kpi_name(columns, alias)
            if kpi:
                break
        entry: dict = {
            "category": cat_name,
            "tab_label": preset.get("tab_label") or cat_name,
            "direction": preset["direction"],
            "threshold_bad": preset.get("threshold_bad"),
            "kpi": kpi,
            "count": 0,
            "cells": [],
        }
        if kpi:
            rows = get_kpi_cells(
                kpi,
                vendor=vendor,
                rat=rat,
                area=area,
                cluster=cluster,
                top_n=50_000,
            )
            breached = [r for r in rows if r.get("breached")]
            breached.sort(key=lambda r: -float(r.get("score") or 0))
            entry["count"] = len(breached)
            entry["cells"] = [_slim_table_row(r) for r in breached[: max(1, int(top_n or 8))]]
            by_name[cat_name] = entry["cells"]
        else:
            by_name[cat_name] = []
        summary[cat_name] = entry["count"]
        categories.append(entry)
    return {
        "generated_at": _utc_now_iso(),
        "vendor": vendor,
        "rat": rat,
        "pm_data_scope": PM_DATA_SCOPE,
        "benchmark": "vs_operator_threshold",
        "area": area or "all",
        "cluster": cluster,
        "summary": summary,
        "categories": categories,
        "category_cells": by_name,
        "presets": cfg.public_category_presets(),
    }


def _build_category_rankings(
    vendor: str = "all",
    technology: str = "4G",
    top_n: int = 20,
    area: str = "",
) -> dict:
    degraded = collect_degraded_cells(
        cfg.CATEGORY_PRESETS,
        vendor=vendor,
        technology=technology,
        scope=PM_DATA_SCOPE,
        lookback_days=cfg.WOW_LOOKBACK_DAYS,
        min_history_days=cfg.WOW_MIN_HISTORY_DAYS,
        degradation_pct=cfg.WOW_DEGRADATION_PCT,
        min_absolute_delta=cfg.WOW_MIN_ABSOLUTE_DELTA,
    )
    degraded = _enrich_benchmark_rows(degraded, area=area, rat=technology)

    results: dict[str, list[dict]] = {}
    summary: dict[str, int] = {}
    for cat_name in cfg.CATEGORY_PRESETS:
        ranked = [row for row in degraded if row.get("category") == cat_name]
        ranked.sort(key=lambda x: -float(x.get("score") or 0))
        ranked = ranked[: max(1, top_n)]
        results[cat_name] = ranked
        summary[cat_name] = len(ranked)

    return {
        "generated_at": _utc_now_iso(),
        "pm_data_scope": PM_DATA_SCOPE,
        "benchmark": "vs_operator_threshold",
        "benchmark_days": cfg.WOW_LOOKBACK_DAYS,
        "technology": technology,
        "vendor_filter": vendor,
        "area_filter": area or "all",
        "summary": summary,
        "categories": results,
        "presets": cfg.public_category_presets(),
    }


def get_health_payload(
    *,
    vendor: str = "all",
    technology: str = "4G",
    top_n: int = 20,
    area: str | None = None,
    force_refresh: bool = False,
) -> dict:
    area_f = normalize_area(area)
    cache_key = f"{vendor}|{technology}|{top_n}|{area_f or 'all'}"
    now = time.time()
    cached = _HEALTH_CACHE.get(cache_key)
    if (
        not force_refresh
        and cached
        and (now - float(cached.get("_ts", 0))) < cfg.CACHE_TTL_SECONDS
    ):
        return cached["payload"]

    payload = _build_category_rankings(vendor, technology, top_n, area_f)
    _HEALTH_CACHE[cache_key] = {"_ts": now, "payload": payload}
    return payload


def get_worst_cells(
    payload: dict,
    category: str | None = None,
    top_n: int = 20,
) -> list[dict]:
    cats = payload.get("categories") or {}
    cat = (category or "").strip()
    if cat and cat in cats:
        return list(cats[cat])[:top_n]
    merged: list[dict] = []
    for rows in cats.values():
        merged.extend(rows)
    merged.sort(key=lambda x: -float(x.get("score") or 0))
    return merged[:top_n]
