"""
Pipeline path helpers.

Canonical folder taxonomy:
- raw/{vendor}/{domain}/{2g|3g|4g|5g}/{timeframe}/  — PM exports (one RAT per folder)
- raw/{vendor}/{domain}/all/{timeframe}/  — legacy / Huawei staging only
- databases/{domain}/{vendor}/{technology}/{timeframe}/
"""

from __future__ import annotations

import os


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_ROOT = os.path.join(PROJECT_ROOT, "raw")
DATABASES_ROOT = os.path.join(PROJECT_ROOT, "databases")

VENDORS = ("nokia", "huawei", "metadata")
DOMAINS = ("cells", "groups", "neighbors", "metadata", "admin")
TECHNOLOGIES = ("2g", "3g", "4g", "5g", "all")
PM_RATS = ("2g", "3g", "4g", "5g")  # per-RAT folders under cells/groups
TIMEFRAMES = ("hourly", "daily", "snapshot")


def raw_path(vendor: str, domain: str, technology: str, timeframe: str) -> str:
    return os.path.join(
        RAW_ROOT,
        str(vendor).strip().lower(),
        str(domain).strip().lower(),
        str(technology).strip().lower(),
        str(timeframe).strip().lower(),
    )


def db_path(domain: str, vendor: str, technology: str, timeframe: str, filename: str) -> str:
    return os.path.join(
        DATABASES_ROOT,
        str(domain).strip().lower(),
        str(vendor).strip().lower(),
        str(technology).strip().lower(),
        str(timeframe).strip().lower(),
        filename,
    )


def iter_pm_raw_paths(vendor: str, domain: str, scope: str):
    """Yield (technology, path) for PM cell/group raw storage (per-RAT folders)."""
    for tech in PM_RATS:
        yield tech, raw_path(vendor, domain, tech, scope)


def pm_raw_paths_flat(vendor: str, domain: str, scope: str) -> list[str]:
    return [p for _, p in iter_pm_raw_paths(vendor, domain, scope)]


def ensure_taxonomy_dirs() -> None:
    """Create the canonical folder tree for easier local discoverability."""
    for v in VENDORS:
        for d in DOMAINS:
            for t in TECHNOLOGIES:
                for tf in TIMEFRAMES:
                    os.makedirs(raw_path(v, d, t, tf), exist_ok=True)
