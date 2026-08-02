"""Load the committed Nokia counter/KPI dictionaries into warehouse dimensions.

Sources (already in the repo, measured 99.2 % counter coverage on the sample):
  modules/performance_dictionary/data/nokia_performance/counters/4G.json
  modules/performance_dictionary/data/nokia_performance/kpis.json

``Logical Type`` maps to the per-counter aggregation rule that drives both the
merge SQL and the query-time finalisation:
  SUM  — additive events (also Denominator);   AVG — sum stored, / n_present
  MAX / MIN — extreme over the bucket;         CUM — monotonic, delta first
  LAST — point-in-time sample
"""

from __future__ import annotations

import json
import os
import re

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_NOKIA_DIR = os.path.join(
    _REPO_ROOT, "modules", "performance_dictionary", "data", "nokia_performance"
)

_RULE_MAP = {
    "sum": "SUM",
    "denominator": "SUM",
    "average": "AVG",
    "max": "MAX",
    "min": "MIN",
    "cumulative": "CUM",
    "current": "LAST",
}

_MID_RE = re.compile(r"^M(\d+)C(\d+)$")


def counter_mid(native_id: str) -> int | None:
    """M8007C1 -> 8007. The measurement id is the robust family join key."""
    m = _MID_RE.match(native_id or "")
    return int(m.group(1)) if m else None


def column_name(native_id: str) -> str:
    """Postgres column for a counter: lowercase alnum/underscore, leading letter."""
    col = re.sub(r"[^a-z0-9_]", "_", str(native_id).strip().lower())
    if not col or not col[0].isalpha():
        col = "c_" + col
    return col[:63]


def agg_rule(logical_type: str) -> str:
    return _RULE_MAP.get((logical_type or "").strip().lower(), "SUM")


def load_nokia_counters(technology: str = "4G") -> dict[str, dict]:
    """native_id -> {rule, unit, family_name, mid, display, netact, version}."""
    path = os.path.join(_NOKIA_DIR, "counters", f"{technology}.json")
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    out: dict[str, dict] = {}
    for entry in raw.values():
        cid = str(entry.get("Counter ID") or "").strip()
        if not cid:
            continue
        unit = str(entry.get("Unit") or "").strip()
        rule = agg_rule(entry.get("Logical Type") or "")
        out[cid] = {
            "native_id": cid,
            "mid": counter_mid(cid),
            "rule": rule,
            # bytes/bit counters overflow real's 24-bit mantissa when summed
            # over long windows; store those as double precision.
            "wide": unit.lower() in ("bytes", "byte", "bit", "bits"),
            "unit": unit,
            "family_name": str(entry.get("Measurement Name") or "").strip(),
            "display": str(entry.get("Network Element Name") or "").strip(),
            "netact": str(entry.get("NetAct Name") or "").strip(),
            "version": str(entry.get("Counter Version") or "").strip(),
        }
    return out


_FORMULA_KEY = "KPI Formula (with Counter IDs)"


def load_nokia_kpis(technology: str = "4G") -> list[dict]:
    path = os.path.join(_NOKIA_DIR, "kpis.json")
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    out = []
    for key, entry in raw.items():
        tech = str(entry.get("Technology") or key.split("|")[0]).strip()
        if not tech.startswith(technology):
            continue
        formula = str(entry.get(_FORMULA_KEY) or "").strip()
        if not formula:
            continue
        out.append({
            "kpi_id": str(entry.get("KPI ID") or "").strip(),
            "name": str(entry.get("KPI Name") or "").strip(),
            "kpi_class": str(entry.get("KPI Class") or "").strip(),
            "unit": str(entry.get("Unit") or "").strip(),
            "formula": formula,
            "object_levels": str(entry.get("Object Summary Levels") or "").strip(),
            "time_levels": str(entry.get("Time Summary Levels") or "").strip(),
        })
    return out
