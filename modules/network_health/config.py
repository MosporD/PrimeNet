"""KPI presets for Network Health Scorecard (development stage)."""

from __future__ import annotations

import os

# Five RAT options (matches network map / metadata taxonomy).
RAT_OPTIONS: list[dict] = [
    {"key": "2G", "label": "2G", "pm_technology": "2G"},
    {"key": "3G", "label": "3G", "pm_technology": "3G"},
    {"key": "4G-FDD", "label": "4G FDD", "pm_technology": "4G", "metadata_technology": "4G-FDD"},
    {"key": "4G-TDD", "label": "4G TDD", "pm_technology": "4G", "metadata_technology": "4G-TDD"},
    {"key": "5G", "label": "5G", "pm_technology": "5G"},
]

VENDOR_OPTIONS: list[dict] = [
    {"key": "nokia", "label": "Nokia"},
    {"key": "huawei", "label": "Huawei"},
]

# Vendor×RAT combos with no PM daily table (skip precalc build).
PRECALC_SKIP_COMBOS: frozenset[tuple[str, str]] = frozenset({("huawei", "5G")})

DEFAULT_RAT = "3G"
DEFAULT_VENDOR = "nokia"
DEFAULT_TOP_N = 200
CACHE_TTL_SECONDS = 3600

# Daily value vs previous 7-day average (excluding latest day)
WOW_LOOKBACK_DAYS = 7
WOW_MIN_HISTORY_DAYS = 3
WOW_DEGRADATION_PCT = 5.0
WOW_MIN_ABSOLUTE_DELTA = 0.5
WOW_NO_CHANGE_THRESHOLD = 0.5

# Table pre-calculation: cron builds SQLite store; UI reads from DB (no PM scan on page load).
PRECOMPUTE_KPI_MAX = 16

# Exclude % / ratio / rate KPIs from picker and precalc (absolute counters only).
EXCLUDE_PERCENTAGE_KPIS = os.environ.get(
    "NH_EXCLUDE_PERCENTAGE_KPIS", "1"
).strip().lower() not in ("0", "false", "no")

# Cron job precomputes all KPIs with PM data (not just the shortlist).
PRECOMPUTE_CRON_ALL_KPIS = True

# Allow on-demand PM scan in the web app if store is missing (off by default).
PRECOMPUTE_ALLOW_RUNTIME_BUILD = os.environ.get(
    "NH_PRECALC_RUNTIME_BUILD", ""
).strip().lower() in ("1", "true", "yes")

# Scheduled build: hour/minute (UTC server local time; default 30 min after daily PM pull hour).
def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


PRECALC_CRON_HOUR = _env_int("NH_PRECALC_HOUR", -1)  # -1 = use DAILY_PULL_HOUR + 1
PRECALC_CRON_MINUTE = _env_int("NH_PRECALC_MINUTE", 30)

# Optional explicit KPI names/aliases to prioritize in shortlist builds (partial match).
PRECOMPUTE_KPI_NAMES: list[str] = []

# Legacy category presets (SON Analytics compatibility)
CATEGORY_PRESETS: dict[str, dict] = {
    "Retainability": {
        "direction": "higher_worse",
        "tab_label": "Call Drops",
        "aliases": [
            "E-UTRAN E-RAB DR, RAN View",
            "E-UTRAN E-RAB Drop Ratio, User Perspective",
            "Call Drop Rate (All)(%)",
            "Call DR",
            "AMR Call Drop Ratio(%)",
        ],
        "threshold_bad": 2.0,
    },
    "Accessibility": {
        "direction": "lower_worse",
        "tab_label": "Availability",
        "aliases": [
            "RRC Setup Success Rate(%)",
            "E-RAB Setup Success Rate (ALL)(%)",
            "E-UTRAN E-RAB stp SR",
            "CSSR(%)",
        ],
        "threshold_bad": 98.0,
    },
    "Mobility": {
        "direction": "lower_worse",
        "tab_label": "SHO Failures",
        "aliases": [
            "Handover Success Rate(%)",
            "E-UTRAN Intra-Freq HO SR",
            "E-UTRAN Inter-Freq HO SR",
            "Intra-Freq HO Success Rate(%)",
        ],
        "threshold_bad": 95.0,
    },
    "Interference": {
        "direction": "higher_worse",
        "tab_label": "Average RTWP",
        "aliases": [
            "L.UL.Interference.Avg(dBm)",
            "LTE_AVG_Interference",
            "VS.MeanRTWP(dBm)",
            "Average RTWP",
        ],
        "threshold_bad": -95.0,
    },
    "Utilization": {
        "direction": "higher_worse",
        "tab_label": "PRB Usage",
        "aliases": [
            "DL PRB Usage Rate(%)",
            "E-UTRAN Avg PRB usage per TTI DL",
            "PRB util PDSCH",
            "UL PRB Usage Rate(%)",
        ],
        "threshold_bad": 80.0,
    },
}

DEFAULT_TECHNOLOGY = DEFAULT_RAT


def rat_config(rat_key: str) -> dict | None:
    key = str(rat_key or "").strip()
    for item in RAT_OPTIONS:
        if item["key"] == key:
            return item
    return None


def pm_technology_for_rat(rat_key: str) -> str:
    cfg = rat_config(rat_key)
    if cfg:
        return str(cfg.get("pm_technology") or cfg["key"])
    return str(rat_key or "4G")


def metadata_technology_for_rat(rat_key: str) -> str | None:
    cfg = rat_config(rat_key)
    if not cfg:
        return None
    return cfg.get("metadata_technology") or cfg["key"]
