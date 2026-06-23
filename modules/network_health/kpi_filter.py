"""Exclude percentage / ratio / rate KPIs from Network Health (absolute counters only)."""

from __future__ import annotations

import re

# Literal markers in PM column titles.
_PCT_MARKERS = (
    "%",
    "(%)",
    "percent",
    "percentage",
)

# Word / phrase patterns (telecom PM naming).
_PCT_REGEXES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bratio\b",
        r"\brate\b",
        r"\bsr\b",  # success rate (RAB SR, HO SR, …)
        r"\bcdr\b",
        r"\bcssr\b",
        r"success\s+rate",
        r"drop\s+rate",
        r"failure\s+rate",
        r"blocking\s+rate",
        r"congestion\s+rate",
        r"rej\s+rate",
        r"usage\s+rate",
        r"utilization",
        r"\bavailability\b",
        r"occupancy",
        r"share\b",  # PRB share, load share
        r"\bproportion\b",
        r"\bfraction\b",
    )
)


def is_percentage_kpi(column_name: str) -> bool:
    """
    True if the KPI is a rate, ratio, percentage, SR, or similar normalized metric.

    Network Health compares raw daily values to a 7-day average; %/rate KPIs are excluded
    because averaging percentages across cells/days is misleading.
    """
    name = str(column_name or "").strip()
    if not name:
        return True
    if name.startswith("%"):
        return True
    low = name.lower()
    for marker in _PCT_MARKERS:
        if marker in low:
            return True
    for rx in _PCT_REGEXES:
        if rx.search(name):
            return True
    return False


def filter_absolute_kpis(columns: list[str]) -> list[str]:
    """Keep only non-percentage KPI column names, preserving order."""
    return [c for c in columns if not is_percentage_kpi(c)]
