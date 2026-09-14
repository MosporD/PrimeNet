"""High-level case services: open from issue, refresh evidence/scorecard."""

from __future__ import annotations

from typing import Any

from core.cases import correlator, scorecard, selection, store


def open_case_from_issue(issue: dict, *, actor: str = "", refresh: bool = True) -> dict:
    """Persist a detector/SON issue as an optimization case."""
    issue = issue or {}
    cells = issue.get("cells") or []
    if isinstance(cells, str):
        cells = [c.strip() for c in cells.replace(";", ",").split(",") if c.strip()]

    sel = selection.normalize_selection(
        {
            "kind": "cells",
            "cells": cells,
            "sites": [issue["site_id"]] if issue.get("site_id") else [],
            "label": issue.get("title") or "",
            "source": issue.get("module") or issue.get("source_module") or "issue",
        }
    )

    payload: dict[str, Any] = {
        "title": issue.get("title") or "Optimization case",
        "summary": issue.get("summary") or "",
        "severity": issue.get("severity") or "Medium",
        "score": issue.get("score") or 0,
        "category": issue.get("category") or "",
        "source_module": issue.get("module") or issue.get("source_module") or "",
        "source_issue_id": issue.get("id") or issue.get("source_issue_id") or "",
        "source_url": issue.get("source_url") or "",
        "vendor": issue.get("vendor") or "",
        "technology": issue.get("technology") or "",
        "area": issue.get("area") or "",
        "site_id": issue.get("site_id") or "",
        "recommendation": issue.get("recommendation") or "",
        "proposed_change": issue.get("proposed_change") or "",
        "execution_ref": issue.get("execution_ref") or "",
        "cells": cells,
        "selection": sel,
        "evidence": {"source_issue": issue.get("evidence") or issue},
        "owner": actor or "",
        "created_by": actor or "",
    }

    case = store.create_case(payload, actor=actor)
    if refresh:
        case = refresh_case_evidence(case["case_id"], actor=actor)
    return case


def refresh_case_evidence(case_id: str, *, actor: str = "", include_alarms: bool = True) -> dict:
    case = store.get_case(case_id)
    if not case:
        raise store.CaseError(f"Case not found: {case_id}")

    pack = correlator.correlate_evidence(
        cells=case.get("cells") or [],
        vendor=case.get("vendor") or "",
        technology=case.get("technology") or "",
        area=case.get("area") or "",
        title=case.get("title") or "",
        seed_evidence=(case.get("evidence") or {}).get("source_issue"),
        include_alarms=include_alarms,
    )
    card = scorecard.build_scorecard(
        cells=case.get("cells") or [],
        evidence=(case.get("evidence") or {}).get("source_issue") or {},
        facts=pack.get("facts") or [],
        execution_ref=case.get("execution_ref") or "",
    )
    merged_evidence = dict(case.get("evidence") or {})
    merged_evidence["correlator"] = {
        "generated_at": pack.get("generated_at"),
        "fact_counts": pack.get("fact_counts"),
        "confidence": pack.get("confidence"),
        "facts": pack.get("facts"),
    }
    return store.update_case(
        case_id,
        {
            "evidence": merged_evidence,
            "narrative": pack.get("narrative") or "",
            "scorecard": card,
        },
        actor=actor,
    )


def refresh_case_scorecard(case_id: str, *, actor: str = "") -> dict:
    case = store.get_case(case_id)
    if not case:
        raise store.CaseError(f"Case not found: {case_id}")
    facts = ((case.get("evidence") or {}).get("correlator") or {}).get("facts") or []
    card = scorecard.build_scorecard(
        cells=case.get("cells") or [],
        evidence=(case.get("evidence") or {}).get("source_issue") or {},
        facts=facts,
        execution_ref=case.get("execution_ref") or "",
    )
    return store.set_scorecard(case_id, card, actor=actor)
