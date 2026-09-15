"""Conflict + golden-rule gates before Case approval."""

from __future__ import annotations

import re
from typing import Any

from core.cases import identity, store
from core.cases.config import STATES


_TOKEN = re.compile(r"[a-z0-9_]{3,}")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(str(text or "").lower()))


OPENISH = frozenset({"open", "assigned", "proposed", "approved", "executed", "verifying"})


def find_conflicts(case: dict, *, limit: int = 10) -> list[dict]:
    """Other open cases overlapping cells with similar proposed_change tokens."""
    cells = case.get("cells") or []
    if not cells:
        return []
    mine = _tokens(str(case.get("proposed_change") or case.get("title") or ""))
    case_id = str(case.get("case_id") or "")
    hits: list[dict] = []
    # Scan recent open cases (bounded)
    for other in store.list_cases(limit=200):
        if other.get("case_id") == case_id:
            continue
        if other.get("state") not in OPENISH:
            continue
        other_cells = other.get("cells") or []
        overlap = False
        for a in cells:
            for b in other_cells:
                if identity.cells_match(a, b):
                    overlap = True
                    break
            if overlap:
                break
        if not overlap:
            continue
        theirs = _tokens(str(other.get("proposed_change") or other.get("title") or ""))
        shared = mine & theirs if mine and theirs else set()
        # Cell overlap alone is enough to flag; token overlap strengthens
        hits.append(
            {
                "case_id": other.get("case_id"),
                "title": other.get("title"),
                "state": other.get("state"),
                "shared_tokens": sorted(shared)[:8],
                "reason": "cell_overlap_and_change" if shared else "cell_overlap",
            }
        )
        if len(hits) >= limit:
            break
    return hits


def check_golden_rules(proposed_change: str, *, vendor: str = "", technology: str = "") -> dict[str, Any]:
    """
    Best-effort CM Audit rule check.
    Returns {ok, checked, violations, note}.
    """
    text = str(proposed_change or "").strip()
    if not text:
        return {"ok": True, "checked": False, "violations": [], "note": "No proposed_change to check."}
    try:
        from core.radio import cm_store
    except Exception as exc:
        return {"ok": True, "checked": False, "violations": [], "note": f"CM store unavailable: {exc}"}

    try:
        rules = cm_store.list_rules() if hasattr(cm_store, "list_rules") else []
    except Exception as exc:
        return {"ok": True, "checked": False, "violations": [], "note": f"Rules unavailable: {exc}"}

    if not rules:
        return {"ok": True, "checked": False, "violations": [], "note": "No golden rules configured."}

    violations: list[dict] = []
    text_l = text.lower()
    for rule in rules:
        param = str(rule.get("parameter") or rule.get("param") or "").strip()
        if not param:
            continue
        if param.lower() not in text_l:
            continue
        baseline = rule.get("baseline")
        # If proposed text mentions parameter with a value differing from baseline, flag
        if baseline is not None and str(baseline).lower() not in text_l:
            violations.append(
                {
                    "parameter": param,
                    "baseline": baseline,
                    "rule_version": rule.get("version"),
                    "message": f"Proposed change mentions {param} but does not match golden baseline {baseline}.",
                }
            )
    return {
        "ok": len(violations) == 0,
        "checked": True,
        "violations": violations,
        "note": "ok" if not violations else f"{len(violations)} golden-rule concern(s)",
    }


def assert_can_approve(case: dict, *, override_note: str = "") -> None:
    """Raise store.CaseError if approval should be blocked."""
    conflicts = find_conflicts(case)
    # Hard block only when cell overlap AND similar proposed_change keywords
    hard = [c for c in conflicts if c.get("shared_tokens")]
    if hard and not str(override_note or "").strip():
        ids = ", ".join(str(c.get("case_id")) for c in hard[:3])
        raise store.CaseError(
            f"Conflict guard: overlapping open case(s) with similar change keywords: {ids}. "
            "Add override_note to approve anyway."
        )
    gate = check_golden_rules(
        str(case.get("proposed_change") or ""),
        vendor=str(case.get("vendor") or ""),
        technology=str(case.get("technology") or ""),
    )
    if gate.get("checked") and not gate.get("ok") and not str(override_note or "").strip():
        raise store.CaseError(
            f"Golden-rule gate failed: {gate.get('note')}. "
            "Add override_note to approve anyway."
        )
