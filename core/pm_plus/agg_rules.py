"""Per-counter / per-family aggregation rules for PM Plus.

Resolution order:
1. Counter override (dim_counter.time_agg / nw_agg when override flags set)
2. Family default (agg_rule_family)
3. Catalog seed on dim_counter
4. SUM (NONE maps to SUM)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from core.pm_plus.db import connect, execute, fetchall, fetchone, qident
from core.pm_plus.schema import init_schema

SIMPLE_RULES = frozenset({"SUM", "AVG", "MAX", "MIN"})


def normalize_agg_rule(raw: str | None) -> str:
    """Map Nokia catalog text → SUM|AVG|MAX|MIN (NONE→SUM; unknown→SUM)."""
    text = (raw or "").strip()
    if not text:
        return "SUM"
    low = text.lower()
    if low in ("none", "n/a", "na", "-"):
        return "SUM"
    if low == "sum":
        return "SUM"
    if low in ("avg", "average", "mean"):
        return "AVG"
    if low == "max":
        return "MAX"
    if low == "min":
        return "MIN"
    # Exotic dB / DECODE formulas — safe default until specialized
    if low.startswith("sum") or "sum(" in low:
        return "SUM"
    if "avg(" in low or low.startswith("avg"):
        return "AVG"
    if low.startswith("max") or "max(" in low:
        return "MAX"
    if low.startswith("min") or "min(" in low:
        return "MIN"
    return "SUM"


@dataclass
class AggParts:
    """Running aggregates for rule-aware fold."""

    sum_value: float = 0.0
    weight: float = 0.0  # sample_count
    min_value: float | None = None
    max_value: float | None = None
    family: str = ""
    vendor: str = "nokia"

    def add(self, value: float | None, weight: float = 1.0) -> None:
        if value is None:
            return
        w = float(weight) if weight else 1.0
        self.sum_value += float(value) * w
        self.weight += w
        self.min_value = float(value) if self.min_value is None else min(self.min_value, float(value))
        self.max_value = float(value) if self.max_value is None else max(self.max_value, float(value))

    def finish(self, rule: str) -> tuple[float | None, int]:
        rule = normalize_agg_rule(rule)
        if self.weight <= 0 and self.min_value is None:
            return None, 0
        sc = int(self.weight) if self.weight else 0
        if rule == "AVG":
            if self.weight <= 0:
                return None, 0
            return self.sum_value / self.weight, sc
        if rule == "MAX":
            return self.max_value, sc
        if rule == "MIN":
            return self.min_value, sc
        # SUM
        # For SUM inputs that were already period totals, weight should be 1 per part
        # (we still added value*weight — callers should pass weight=1 for SUM parts)
        return self.sum_value if self.weight else None, sc


def finish_sum_parts(parts: AggParts, rule: str) -> tuple[float | None, int]:
    """Like AggParts.finish but SUM uses unweighted sum of values.

    Callers adding SUM parts must use add(value, weight=1).
    """
    return parts.finish(rule)


def get_family_rules(*, ne_type: str = "") -> list[dict]:
    init_schema()
    t = qident("agg_rule_family")
    with connect() as conn:
        if ne_type:
            return fetchall(
                conn,
                f"SELECT family, ne_type, time_agg, nw_agg, enabled, updated_at "
                f"FROM {t} WHERE ne_type=? OR ne_type='' ORDER BY family",
                (ne_type.upper(),),
            )
        return fetchall(
            conn,
            f"SELECT family, ne_type, time_agg, nw_agg, enabled, updated_at "
            f"FROM {t} ORDER BY family, ne_type",
        )


def upsert_family_rule(
    *,
    family: str,
    time_agg: str,
    nw_agg: str,
    ne_type: str = "",
    enabled: bool = True,
) -> dict:
    init_schema()
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    t = qident("agg_rule_family")
    ta = normalize_agg_rule(time_agg)
    na = normalize_agg_rule(nw_agg)
    ne = (ne_type or "").upper()
    with connect() as conn:
        execute(
            conn,
            f"INSERT INTO {t} (family, ne_type, time_agg, nw_agg, enabled, updated_at) "
            f"VALUES (?,?,?,?,?,?) "
            f"ON CONFLICT(family, ne_type) DO UPDATE SET "
            f"time_agg=excluded.time_agg, nw_agg=excluded.nw_agg, "
            f"enabled=excluded.enabled, updated_at=excluded.updated_at",
            (family, ne, ta, na, 1 if enabled else 0, now),
        )
        conn.commit()
    return {"family": family, "ne_type": ne, "time_agg": ta, "nw_agg": na, "enabled": enabled}


def set_counter_override(
    *,
    counter_id: str,
    time_agg: str | None = None,
    nw_agg: str | None = None,
    clear: bool = False,
) -> dict:
    init_schema()
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    t = qident("dim_counter")
    with connect() as conn:
        row = fetchone(conn, f"SELECT * FROM {t} WHERE counter_id=?", (counter_id,))
        if not row:
            execute(
                conn,
                f"INSERT INTO {t} (counter_id, vendor, family, display_name, agg_rule, "
                f"time_agg, nw_agg, time_agg_override, nw_agg_override, updated_at) "
                f"VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    counter_id,
                    "nokia",
                    "",
                    counter_id,
                    "SUM",
                    normalize_agg_rule(time_agg) if time_agg else "SUM",
                    normalize_agg_rule(nw_agg) if nw_agg else "SUM",
                    0 if clear else (1 if time_agg else 0),
                    0 if clear else (1 if nw_agg else 0),
                    now,
                ),
            )
        elif clear:
            execute(
                conn,
                f"UPDATE {t} SET time_agg_override=0, nw_agg_override=0, updated_at=? "
                f"WHERE counter_id=?",
                (now, counter_id),
            )
        else:
            sets = ["updated_at=?"]
            params: list = [now]
            if time_agg is not None:
                sets.append("time_agg=?")
                params.append(normalize_agg_rule(time_agg))
                sets.append("time_agg_override=1")
                sets.append("agg_rule=?")
                params.append(normalize_agg_rule(time_agg))
            if nw_agg is not None:
                sets.append("nw_agg=?")
                params.append(normalize_agg_rule(nw_agg))
                sets.append("nw_agg_override=1")
            params.append(counter_id)
            execute(conn, f"UPDATE {t} SET {', '.join(sets)} WHERE counter_id=?", tuple(params))
        conn.commit()
    return {"counter_id": counter_id, "ok": True, "cleared": clear}


def resolve_time_agg(counter_id: str, family: str = "", ne_type: str = "") -> str:
    """Effective time aggregation rule for a counter."""
    init_schema()
    with connect() as conn:
        crow = fetchone(
            conn,
            f"SELECT time_agg, time_agg_override, family, agg_rule FROM {qident('dim_counter')} "
            f"WHERE counter_id=?",
            (counter_id,),
        )
        if crow and int(crow["time_agg_override"] or 0) == 1 and crow.get("time_agg"):
            return normalize_agg_rule(crow["time_agg"])
        fam = family or (crow.get("family") if crow else "") or ""
        if fam:
            frow = fetchone(
                conn,
                f"SELECT time_agg FROM {qident('agg_rule_family')} "
                f"WHERE family=? AND (ne_type=? OR ne_type='') "
                f"ORDER BY CASE WHEN ne_type=? THEN 0 ELSE 1 END LIMIT 1",
                (fam, (ne_type or "").upper(), (ne_type or "").upper()),
            )
            if frow and frow.get("time_agg"):
                return normalize_agg_rule(frow["time_agg"])
        if crow and crow.get("time_agg"):
            return normalize_agg_rule(crow["time_agg"])
        if crow and crow.get("agg_rule"):
            return normalize_agg_rule(crow["agg_rule"])
    return "SUM"


def load_time_agg_map(counter_ids: Iterable[str] | None = None) -> dict[str, str]:
    """Bulk map counter_id → time_agg for rollup loops."""
    init_schema()
    with connect() as conn:
        if counter_ids:
            ids = list(counter_ids)
            out: dict[str, str] = {}
            chunk = 500
            for i in range(0, len(ids), chunk):
                part = ids[i : i + chunk]
                ph = ",".join("?" * len(part))
                rows = fetchall(
                    conn,
                    f"SELECT counter_id, time_agg, time_agg_override, family, agg_rule "
                    f"FROM {qident('dim_counter')} WHERE counter_id IN ({ph})",
                    tuple(part),
                )
                for r in rows:
                    out[r["counter_id"]] = r
            # resolve with family table
            families = {
                r["family"]
                for r in out.values()
                if isinstance(r, dict) and r.get("family")
            }
            fam_rules = {}
            if families:
                # load all family rules (small)
                for fr in fetchall(
                    conn,
                    f"SELECT family, ne_type, time_agg FROM {qident('agg_rule_family')}",
                ):
                    fam_rules.setdefault(fr["family"], []).append(fr)
            resolved = {}
            for cid, r in out.items():
                if int(r.get("time_agg_override") or 0) == 1 and r.get("time_agg"):
                    resolved[cid] = normalize_agg_rule(r["time_agg"])
                    continue
                fam = r.get("family") or ""
                hit = None
                for fr in fam_rules.get(fam) or []:
                    if not fr.get("ne_type"):
                        hit = fr["time_agg"]
                if hit:
                    resolved[cid] = normalize_agg_rule(hit)
                else:
                    resolved[cid] = normalize_agg_rule(r.get("time_agg") or r.get("agg_rule") or "SUM")
            for cid in ids:
                resolved.setdefault(cid, "SUM")
            return resolved

        rows = fetchall(
            conn,
            f"SELECT counter_id, time_agg, time_agg_override, family, agg_rule "
            f"FROM {qident('dim_counter')}",
        )
        fam_rules = {}
        for fr in fetchall(
            conn,
            f"SELECT family, ne_type, time_agg FROM {qident('agg_rule_family')}",
        ):
            fam_rules.setdefault(fr["family"], []).append(fr)
        resolved = {}
        for r in rows:
            cid = r["counter_id"]
            if int(r.get("time_agg_override") or 0) == 1 and r.get("time_agg"):
                resolved[cid] = normalize_agg_rule(r["time_agg"])
                continue
            hit = None
            for fr in fam_rules.get(r.get("family") or "") or []:
                if not fr.get("ne_type"):
                    hit = fr["time_agg"]
            resolved[cid] = normalize_agg_rule(
                hit or r.get("time_agg") or r.get("agg_rule") or "SUM"
            )
        return resolved
