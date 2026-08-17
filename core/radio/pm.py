"""PM/KPI helper recipes for radio insight modules."""

from __future__ import annotations

from modules.network_health import config as nh_config
from modules.network_health.logic import get_kpi_cells, list_kpi_columns
from modules.son_analytics.pm_helpers import PM_DATA_SCOPE, collect_degraded_cells


VENDORS = ["nokia", "huawei"]
RATS = ["2G", "3G", "4G-FDD", "4G-TDD", "5G"]

KPI_RECIPES: dict[str, dict] = {
    "utilization": {
        "direction": "higher_worse",
        "aliases": [
            "DL PRB Usage Rate(%)",
            "UL PRB Usage Rate(%)",
            "E-UTRAN Avg PRB usage per TTI DL",
            "PRB util PDSCH",
            "PRB util PUSCH",
            "PRB",
            "Utilization",
            "TCH availability ratio",
        ],
    },
    "users": {
        "direction": "higher_worse",
        "aliases": [
            "Average User Number",
            "Active Users",
            "RRC Connected Users",
            "User Number",
            "Users",
            "Avg act UEs DL",
            "Average number of simultaneous HSDPA users",
            "Avg nr act UEs data buff DRBs DL",
            "NSA Avg nr user",
        ],
    },
    "traffic": {
        "direction": "higher_worse",
        "aliases": [
            "Traffic Volume",
            "Payload",
            "Data Volume",
            "DL Traffic",
            "UL Traffic",
            "PDCP SDU Volume, DL (GB)",
            "MAC SDU data vol trans DL DTCH",
        ],
    },
    "throughput": {
        "direction": "lower_worse",
        "aliases": [
            "User Throughput",
            "Average Throughput",
            "DL Throughput",
            "Cell Throughput",
            "Avg PDCP cell thp DL (Mbps)",
            "HSDPA Cell thp",
            "Act cell MAC thp PDSCH",
            "Sched user thp DL",
        ],
    },
    "mobility": nh_config.CATEGORY_PRESETS["Mobility"],
    "accessibility": nh_config.CATEGORY_PRESETS["Accessibility"],
    "retainability": nh_config.CATEGORY_PRESETS["Retainability"],
    "interference": nh_config.CATEGORY_PRESETS["Interference"],
}


def pm_technology(rat: str) -> str:
    return nh_config.pm_technology_for_rat(rat)


def _norm(text: str) -> str:
    return "".join(ch for ch in str(text or "").lower() if ch.isalnum())


def resolve_kpi(vendor: str, rat: str, recipe: str) -> str | None:
    columns = list_kpi_columns(vendor, rat)
    if not columns:
        return None
    aliases = KPI_RECIPES.get(recipe, {}).get("aliases") or []
    lower = {str(c).strip().lower(): c for c in columns}
    for alias in aliases:
        hit = lower.get(str(alias).strip().lower())
        if hit:
            return hit
    norm_cols = {_norm(c): c for c in columns}
    for alias in aliases:
        hit = norm_cols.get(_norm(alias))
        if hit:
            return hit
    alias_norms = [_norm(a) for a in aliases if _norm(a)]
    for col in columns:
        c_norm = _norm(col)
        if any(a in c_norm or c_norm in a for a in alias_norms):
            return col
    return None


def top_kpi_rows(
    *,
    recipe: str,
    vendor: str = "all",
    rat: str = "all",
    top_n: int = 100,
    sort_mode: str = "increased",
) -> list[dict]:
    vendors = VENDORS if vendor in ("", "all", None) else [vendor]
    rats = RATS if rat in ("", "all", None) else [rat]
    out: list[dict] = []
    for v in vendors:
        for r in rats:
            if (v, r) in nh_config.PRECALC_SKIP_COMBOS:
                continue
            kpi = resolve_kpi(v, r, recipe)
            if not kpi:
                continue
            rows = get_kpi_cells(kpi, vendor=v, rat=r, sort_mode=sort_mode, top_n=top_n)
            for row in rows:
                item = dict(row)
                item["vendor"] = item.get("vendor") or v.title()
                item["rat"] = r
                item["technology"] = r
                item["kpi"] = kpi
                item["recipe"] = recipe
                out.append(item)
    return out[: max(1, top_n)]


def degraded_cells(vendor: str = "all", technology: str = "4G", limit: int = 200) -> list[dict]:
    rows = collect_degraded_cells(
        nh_config.CATEGORY_PRESETS,
        vendor=vendor,
        technology=technology,
        scope=PM_DATA_SCOPE,
        lookback_days=nh_config.WOW_LOOKBACK_DAYS,
        min_history_days=nh_config.WOW_MIN_HISTORY_DAYS,
        degradation_pct=nh_config.WOW_DEGRADATION_PCT,
        min_absolute_delta=nh_config.WOW_MIN_ABSOLUTE_DELTA,
    )
    rows.sort(key=lambda r: -abs(float(r.get("change_pct") or 0)))
    return rows[: max(1, limit)]

