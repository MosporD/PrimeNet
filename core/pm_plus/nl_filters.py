"""Natural-language → editable filter chips for Performance Explorer Plus.

Never executes SQL. Compiles to chips + optional KPI formula hint only.
"""

from __future__ import annotations

import re
from typing import Any


_RAT = re.compile(r"\b(2g|3g|4g|5g|lte|nr)\b", re.I)
_VENDOR = re.compile(r"\b(nokia|huawei|ericsson)\b", re.I)
_SITE = re.compile(r"\bsite\s*[:=]?\s*([A-Za-z0-9_\-]+)", re.I)
_CELL = re.compile(r"\bcell(?:s)?\s*[:=]?\s*([A-Za-z0-9_\-,;\s]+)", re.I)
_KPI_HINTS = [
    (re.compile(r"\bavail(?:ability)?\b", re.I), "availability", "M8005C0 / M8005C1"),
    (re.compile(r"\bcssr|setup\s*success\b", re.I), "cssr", None),
    (re.compile(r"\bcdr|drop\b", re.I), "cdr", None),
    (re.compile(r"\bthroughput|tput\b", re.I), "throughput", None),
    (re.compile(r"\bprb|utilization|util\b", re.I), "prb_util", None),
]


def compile_nl_to_filters(text: str) -> dict[str, Any]:
    """Return chips + formula hint. Client must apply chips manually."""
    raw = str(text or "").strip()
    chips: list[dict[str, str]] = []
    formula_hint = ""

    if not raw:
        return {
            "chips": [],
            "formula_hint": "",
            "note": "Empty query — no chips.",
            "executed_sql": False,
        }

    m = _VENDOR.search(raw)
    if m:
        chips.append({"type": "vendor", "label": f"vendor={m.group(1).title()}", "value": m.group(1).title()})

    m = _RAT.search(raw)
    if m:
        rat = m.group(1).upper()
        if rat == "LTE":
            rat = "4G"
        if rat == "NR":
            rat = "5G"
        chips.append({"type": "technology", "label": f"rat={rat}", "value": rat})

    m = _SITE.search(raw)
    if m:
        chips.append({"type": "site", "label": f"site={m.group(1)}", "value": m.group(1)})

    m = _CELL.search(raw)
    if m:
        cells = [c.strip() for c in re.split(r"[,;\s]+", m.group(1)) if c.strip()]
        for cell in cells[:20]:
            chips.append({"type": "cell", "label": f"cell={cell}", "value": cell})

    for pattern, name, formula in _KPI_HINTS:
        if pattern.search(raw):
            chips.append({"type": "kpi", "label": f"kpi≈{name}", "value": name})
            if formula and not formula_hint:
                formula_hint = formula

    return {
        "chips": chips,
        "formula_hint": formula_hint,
        "note": "Chips are suggestions only — review and apply in the UI. No SQL was executed.",
        "executed_sql": False,
        "source_text": raw,
    }
