"""
Editable KPI mapping configuration for Performance UI.

Edit this file directly to control:
- KPI category tabs
- KPI display labels shown to users
- metadata KPIs to hide from KPI selectors/charts
"""

from __future__ import annotations

import json
from pathlib import Path


# Optional bootstrap source generated from your spreadsheet.
# You can keep using it, or ignore it and maintain only the overrides below.
_BOOTSTRAP_JSON = Path(__file__).resolve().parent / "static" / "kpi_categories.json"


# ---- Edit these dictionaries/sets directly ---------------------------------
# Exact KPI name from raw data -> category name
KPI_CATEGORY_OVERRIDES: dict[str, str] = {
    # "RRC Setup Success Rate(%)": "Accessibility",
}

# Exact KPI name from raw data -> user-facing label
KPI_DISPLAY_NAME_OVERRIDES: dict[str, str] = {
    # "RRC Setup Success Rate(%)": "RRC Setup SR (%)",
}

# KPIs considered metadata/identifiers and hidden from KPI selector/charts
META_KPI_OVERRIDES: set[str] = {
    # "Cell ID",
}


def _load_bootstrap() -> tuple[dict[str, str], dict[str, str], set[str]]:
    if not _BOOTSTRAP_JSON.exists():
        return {}, {}, set()
    try:
        raw = json.loads(_BOOTSTRAP_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}, {}, set()

    categories = {
        str(k).strip(): str(v).strip()
        for k, v in (raw.get("categories") or {}).items()
        if str(k).strip() and str(v).strip()
    }
    display_names = {
        str(k).strip(): str(v).strip()
        for k, v in (raw.get("display_names") or {}).items()
        if str(k).strip() and str(v).strip()
    }
    meta = {
        str(k).strip()
        for k in (raw.get("meta_kpis") or [])
        if str(k).strip()
    }
    return categories, display_names, meta


def get_kpi_mapping_payload() -> dict:
    """
    Return mapping payload consumed by frontend.
    Rule: if no display label exists for a KPI, frontend uses raw KPI name.
    """
    categories, display_names, meta = _load_bootstrap()

    categories.update({k.strip(): v.strip() for k, v in KPI_CATEGORY_OVERRIDES.items() if k.strip() and v.strip()})
    display_names.update({k.strip(): v.strip() for k, v in KPI_DISPLAY_NAME_OVERRIDES.items() if k.strip() and v.strip()})
    meta.update({k.strip() for k in META_KPI_OVERRIDES if k.strip()})

    return {
        "categories": categories,
        "display_names": display_names,
        "meta_kpis": sorted(meta),
    }

