"""Build cell-day KPI matrices (z-scored per cell) for SON ML."""

from __future__ import annotations

import math
import statistics

from modules.network_health.config import CATEGORY_PRESETS
from modules.son_analytics.area_helpers import get_cell_area_map, get_cell_location_map
from modules.son_analytics.pm_helpers import (
    PM_DATA_SCOPE,
    _cell_daily_kpi_series,
    resolve_kpi_column,
    vendor_pm_sources,
)

from . import config as cfg


def _guess_layer(cell_name: str) -> str:
    token = str(cell_name or "").upper()
    for layer in ("L18+", "L18", "L21", "L26", "L9", "L8", "L7"):
        if layer in token:
            return layer
    return ""


def _mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 1.0
    mu = statistics.fmean(values)
    if len(values) < 2:
        return mu, 1.0
    sd = statistics.pstdev(values)
    return mu, sd if sd > 1e-9 else 1.0


def _worse_z(raw: float, mu: float, sd: float, direction: str) -> float:
    z = (raw - mu) / sd
    if direction == "lower_worse":
        return -z
    return z


def build_cell_days(
    vendor: str,
    rat: str = cfg.TECHNOLOGY,
    *,
    lookback_days: int = cfg.LOOKBACK_DAYS,
) -> list[dict]:
    """One row per cell-day with raw KPIs and per-cell worse-direction z-scores."""
    series_by_cat: dict[str, dict[str, list[tuple[str, float]]]] = {}
    directions: dict[str, str] = {}
    vkey = (vendor or "").strip().lower()
    for cat, preset in CATEGORY_PRESETS.items():
        if cat not in cfg.KPI_CATEGORIES:
            continue
        directions[cat] = str(preset.get("direction") or "higher_worse")
        merged: dict[str, list[tuple[str, float]]] = {}
        for _vlabel, db_path, table in vendor_pm_sources(vkey, rat, PM_DATA_SCOPE):
            col = resolve_kpi_column(db_path, table, list(preset.get("aliases") or []))
            if not col:
                continue
            part = _cell_daily_kpi_series(
                db_path, table, col, lookback_days=lookback_days,
            )
            for cell, series in part.items():
                if cell not in merged or len(series) > len(merged[cell]):
                    merged[cell] = series
        series_by_cat[cat] = merged

    cells: set[str] = set()
    for mapping in series_by_cat.values():
        cells.update(mapping.keys())

    loc_map = get_cell_location_map()
    area_map = get_cell_area_map()
    rows: list[dict] = []

    for cell in cells:
        per_cat_days: dict[str, dict[str, float]] = {}
        stats: dict[str, tuple[float, float]] = {}
        for cat in cfg.KPI_CATEGORIES:
            series = series_by_cat.get(cat, {}).get(cell) or []
            if len(series) < cfg.MIN_HISTORY_DAYS:
                continue
            values = [v for _d, v in series]
            stats[cat] = _mean_std(values)
            per_cat_days[cat] = {d: v for d, v in series}

        if len(stats) < 2:
            continue

        days: set[str] = set()
        for mapping in per_cat_days.values():
            days.update(mapping.keys())

        loc = loc_map.get(cell) or {}
        area = area_map.get(cell) or loc.get("area") or ""
        site_id = loc.get("site_id")
        layer = _guess_layer(cell)

        for day in sorted(days):
            kpis: dict[str, float] = {}
            zmap: dict[str, float] = {}
            for cat in cfg.KPI_CATEGORIES:
                if cat not in per_cat_days or day not in per_cat_days[cat]:
                    continue
                raw = per_cat_days[cat][day]
                mu, sd = stats[cat]
                kpis[cat] = raw
                zmap[cat] = _worse_z(raw, mu, sd, directions.get(cat, "higher_worse"))
            if len(kpis) < 2:
                continue
            lat = loc.get("latitude")
            lng = loc.get("longitude")
            try:
                lat_f = float(lat) if lat is not None else None
                lng_f = float(lng) if lng is not None else None
            except (TypeError, ValueError):
                lat_f = lng_f = None
            if lat_f is not None and (not math.isfinite(lat_f)):
                lat_f = None
            if lng_f is not None and (not math.isfinite(lng_f)):
                lng_f = None
            rows.append({
                "cell_name": cell,
                "vendor": vkey,
                "rat": rat,
                "day": day,
                "kpis": kpis,
                "z": zmap,
                "latitude": lat_f,
                "longitude": lng_f,
                "area": area,
                "site_id": site_id,
                "layer": layer,
            })
    return rows


def latest_rows(cell_days: list[dict]) -> list[dict]:
    best: dict[str, dict] = {}
    for row in cell_days:
        cell = row["cell_name"]
        existing = best.get(cell)
        if not existing or str(row["day"]) > str(existing["day"]):
            best[cell] = row
    return list(best.values())


def feature_matrix(rows: list[dict]) -> tuple[list[str], list[list[float]]]:
    """Fixed-order numeric features for sklearn (NaNs → 0)."""
    names = list(cfg.KPI_CATEGORIES) + [
        "nbr_count",
        "nbr_ho_attempts",
        "nbr_ho_sr",
        "nbr_distance_km",
        "nbr_missing_recip",
    ]
    matrix: list[list[float]] = []
    for row in rows:
        z = row.get("z") or {}
        vec: list[float] = []
        for cat in cfg.KPI_CATEGORIES:
            try:
                vec.append(float(z.get(cat) or 0.0))
            except (TypeError, ValueError):
                vec.append(0.0)
        for key in (
            "nbr_count",
            "nbr_ho_attempts",
            "nbr_ho_sr",
            "nbr_distance_km",
            "nbr_missing_recip",
        ):
            try:
                val = row.get(key)
                vec.append(0.0 if val is None else float(val))
            except (TypeError, ValueError):
                vec.append(0.0)
        matrix.append(vec)
    return names, matrix
