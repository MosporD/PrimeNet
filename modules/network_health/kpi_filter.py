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


# Static PM identifier columns — not performance KPIs.
_META_LITERAL_DENY = frozenset({
    "plmn name",
    "rnc name",
    "cell name",
    "site name",
    "nodeb name",
    "enodeb name",
    "enb name",
    "gnodeb name",
    "nr name",
    "bts name",
    "wbts name",
    "timestamp",
    "cell_name",
    "site_name",
    "time",
    "date",
})

_META_REGEXES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bplmn\b",
        r"\brnc\s+name\b",
        r"\bcell\s+name\b",
        r"\bsite\s+name\b",
        r"\bnodeb\s+name\b",
        r"\benodeb\s+name\b",
        r"\bintegrity\b",
        r"\bduplex\b",
        r"\bindication\b",
        r"\bindex\b",
    )
)


def is_metadata_kpi(column_name: str) -> bool:
    """True for identifier / dimension columns that are not benchmark KPIs."""
    name = str(column_name or "").strip()
    if not name:
        return True
    low = name.lower()
    if low in _META_LITERAL_DENY:
        return True
    for rx in _META_REGEXES:
        if rx.search(name):
            return True
    return False


def filter_metadata_kpis(columns: list[str]) -> list[str]:
    """Drop metadata / identifier columns, preserving order."""
    return [c for c in columns if not is_metadata_kpi(c)]


def filter_network_health_kpis(columns: list[str], *, exclude_percentage: bool = True) -> list[str]:
    """Benchmark KPIs only: optional %/rate exclusion, always drop metadata identifiers."""
    base = filter_absolute_kpis(columns) if exclude_percentage else list(columns)
    return filter_metadata_kpis(base)
