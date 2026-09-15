"""High-level case services: open from issue, refresh evidence/scorecard, morning bulk."""

from __future__ import annotations

from typing import Any

from core.cases import correlator, impact, identity, scorecard, selection, store


CLUSTER_CHECKLIST = {
    "availability_ok": False,
    "cssr_ok": False,
    "cdr_ok": False,
    "alarms_cleared": False,
    "map_location_ok": False,
    "notes": "",
}


def open_case_from_issue(issue: dict, *, actor: str = "", refresh: bool = True) -> dict:
    """Persist a detector/SON issue as an optimization case."""
    issue = issue or {}
    cells = identity.expand_cell_list(issue.get("cells") or [])
    if isinstance(issue.get("cells"), str):
        cells = identity.expand_cell_list(
            [c.strip() for c in str(issue.get("cells")).replace(";", ",").split(",") if c.strip()]
        )

    sel = selection.normalize_selection(
        {
            "kind": "cells",
            "cells": cells,
            "sites": [issue["site_id"]] if issue.get("site_id") else [],
            "label": issue.get("title") or "",
            "source": issue.get("module") or issue.get("source_module") or "issue",
        }
    )

    # Energy tagging
    category = str(issue.get("category") or "")
    module = str(issue.get("module") or issue.get("source_module") or "")
    if "sleep" in module.lower() or "energy" in category.lower():
        category = category or "Energy Opportunity"

    checklist = issue.get("checklist")
    if str(issue.get("case_type") or "").lower() in ("cluster", "cluster_acceptance"):
        checklist = dict(CLUSTER_CHECKLIST)
        checklist.update(issue.get("checklist") or {})

    impact_pack = impact.compute_impact_score(
        severity=str(issue.get("severity") or "Medium"),
        score=float(issue.get("score") or 0),
        cells=cells,
        evidence=issue.get("evidence") if isinstance(issue.get("evidence"), dict) else {},
    )

    payload: dict[str, Any] = {
        "title": issue.get("title") or "Optimization case",
        "summary": issue.get("summary") or "",
        "severity": issue.get("severity") or "Medium",
        "score": issue.get("score") or 0,
        "impact_score": impact_pack["impact_score"],
        "category": category,
        "source_module": module,
        "source_issue_id": issue.get("id") or issue.get("source_issue_id") or "",
        "source_url": issue.get("source_url") or "",
        "vendor": issue.get("vendor") or "",
        "technology": issue.get("technology") or "",
        "area": issue.get("area") or "",
        "site_id": issue.get("site_id") or "",
        "ticket_id": issue.get("ticket_id") or "",
        "recommendation": issue.get("recommendation") or "",
        "proposed_change": issue.get("proposed_change") or "",
        "execution_ref": issue.get("execution_ref") or "",
        "cells": cells,
        "selection": sel,
        "checklist": checklist or {},
        "evidence": {
            "source_issue": issue.get("evidence") or issue,
            "impact": impact_pack,
            "energy_gates": issue.get("energy_gates") or {},
        },
        "owner": actor or "",
        "created_by": actor or "",
    }

    case = store.create_case(payload, actor=actor)
    if refresh:
        case = refresh_case_evidence(case["case_id"], actor=actor)
    return case


def open_cases_from_morning_report(
    issues: list[dict],
    *,
    actor: str = "",
    severities: tuple[str, ...] = ("Critical", "High"),
    limit: int = 25,
    dedupe_days: int = 7,
) -> dict:
    """Bulk-open draft cases from Morning Report issues (Critical/High by default)."""
    created: list[dict] = []
    skipped: list[dict] = []
    allowed = {s.lower() for s in severities}
    for issue in issues or []:
        if len(created) >= limit:
            break
        sev = str(issue.get("severity") or "").lower()
        if allowed and sev not in allowed:
            skipped.append({"id": issue.get("id"), "reason": "severity_filter"})
            continue
        sid = str(issue.get("id") or issue.get("source_issue_id") or "").strip()
        if sid:
            existing = store.find_by_source_issue(sid, within_days=dedupe_days)
            if existing:
                skipped.append({"id": sid, "reason": "deduped", "case_id": existing.get("case_id")})
                continue
        issue = dict(issue)
        issue.setdefault("source_url", "/radio-morning-report")
        issue.setdefault("module", issue.get("module") or "Radio Morning Report")
        case = open_case_from_issue(issue, actor=actor, refresh=True)
        created.append({"case_id": case["case_id"], "title": case["title"], "source_issue_id": sid})
    return {
        "created": created,
        "skipped": skipped,
        "created_count": len(created),
        "skipped_count": len(skipped),
    }


def open_complaint_case(
    *,
    ticket_id: str = "",
    site_id: str = "",
    postcode: str = "",
    cells: list[str] | None = None,
    summary: str = "",
    actor: str = "",
) -> dict:
    cells_n = identity.expand_cell_list(cells)
    title = f"Complaint {ticket_id or site_id or postcode or 'intake'}".strip()
    return open_case_from_issue(
        {
            "title": title,
            "summary": summary or f"Complaint intake — site={site_id} postcode={postcode}",
            "category": "Complaint",
            "module": "Complaint Intake",
            "severity": "High",
            "score": 70,
            "cells": cells_n,
            "site_id": site_id,
            "ticket_id": ticket_id,
            "area": postcode,
            "source_url": "/optimization-cases",
            "evidence": {"ticket_id": ticket_id, "postcode": postcode, "site_id": site_id},
        },
        actor=actor,
    )


# Alias used by package exports / API
create_complaint_case = open_complaint_case


def open_energy_case(issue: dict, *, actor: str = "") -> dict:
    """Open an energy/sleeping-cell Case with safety-gate fields in evidence."""
    issue = dict(issue or {})
    issue.setdefault("category", "Energy Opportunity")
    issue.setdefault("module", issue.get("source_module") or "Sleeping Cells")
    issue.setdefault("source_url", "/sleeping-cells")
    gates = issue.get("energy_gates") or {}
    gates.setdefault("traffic_collapsed", True)
    gates.setdefault("cm_active", True)
    gates.setdefault("alarms_checked", bool((issue.get("evidence") or {}).get("alarms")))
    gates.setdefault("safe_to_sleep_candidate", False)
    gates.setdefault("note", "Energy Case — verify alarms and traffic before any sleep/reset action.")
    issue["energy_gates"] = gates
    if not issue.get("title"):
        cells = issue.get("cells") or []
        label = cells[0] if cells else issue.get("site_id") or "cell"
        issue["title"] = f"Energy candidate: {label}"
    return open_case_from_issue(issue, actor=actor, refresh=True)


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
        source_module=case.get("source_module") or "",
    )
    impact_pack = impact.compute_impact_score(
        severity=case.get("severity") or "Medium",
        score=float(case.get("score") or 0),
        cells=case.get("cells") or [],
        evidence=(case.get("evidence") or {}).get("source_issue")
        if isinstance((case.get("evidence") or {}).get("source_issue"), dict)
        else {},
        facts=pack.get("facts") or [],
    )
    card = scorecard.build_scorecard(
        cells=case.get("cells") or [],
        evidence=(case.get("evidence") or {}).get("source_issue") or {},
        facts=pack.get("facts") or [],
        execution_ref=case.get("execution_ref") or "",
        vendor=case.get("vendor") or "",
        technology=case.get("technology") or "",
    )
    merged_evidence = dict(case.get("evidence") or {})
    merged_evidence["correlator"] = {
        "generated_at": pack.get("generated_at"),
        "fact_counts": pack.get("fact_counts"),
        "confidence": pack.get("confidence"),
        "facts": pack.get("facts"),
    }
    merged_evidence["impact"] = impact_pack
    return store.update_case(
        case_id,
        {
            "evidence": merged_evidence,
            "narrative": pack.get("narrative") or "",
            "scorecard": card,
            "impact_score": impact_pack["impact_score"],
        },
        actor=actor,
    )


def refresh_case_scorecard(case_id: str, *, actor: str = "") -> dict:
    case = store.get_case(case_id)
    if not case:
        raise store.CaseError(f"Case not found: {case_id}")
    facts = ((case.get("evidence") or {}).get("correlator") or {}).get("facts") or []
    executed_at = None
    for ev in store.list_events(case_id, limit=30):
        if ev.get("event_type") == "transition" and (ev.get("detail") or {}).get("to") in (
            "executed",
            "verifying",
        ):
            executed_at = ev.get("created_at")
            break
    card = scorecard.build_scorecard(
        cells=case.get("cells") or [],
        evidence=(case.get("evidence") or {}).get("source_issue") or {},
        facts=facts,
        execution_ref=case.get("execution_ref") or "",
        executed_at=executed_at,
        vendor=case.get("vendor") or "",
        technology=case.get("technology") or "",
    )
    # Record treatment when verdict present
    if card.get("verdict") and case.get("execution_ref"):
        try:
            from core.cases import treatments

            treatments.record_outcome(
                title=case.get("recommendation") or case.get("title") or "",
                category=case.get("category") or "",
                verdict=str(card.get("verdict")),
                meta={"case_id": case_id},
            )
        except Exception:
            pass
    return store.set_scorecard(case_id, card, actor=actor)


def pm_deeplink_for_case(case: dict) -> dict:
    """Build Performance deep-link params from case selection + scorecard windows."""
    cells = case.get("cells") or []
    windows = (case.get("scorecard") or {}).get("windows") or {}
    baseline = windows.get("baseline") or {}
    post = windows.get("post") or {}
    return {
        "performance_url": "/performance",
        "performance_plus_url": "/performance-explorer-plus",
        "cells": cells,
        "vendor": case.get("vendor") or "",
        "technology": case.get("technology") or "",
        "start": baseline.get("start") or "",
        "end": post.get("end") or baseline.get("end") or "",
        "selection_hint": "PrimeNetSelection / paste cells into Performance filters",
    }
