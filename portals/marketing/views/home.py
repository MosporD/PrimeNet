"""Portal overview — what needs attention, and what is not yet connected."""

from __future__ import annotations

from datetime import date, timedelta

from .. import config, providers
from ..access import login_required
from ..repositories import campaigns, catalog, consent, segments
from .blueprint import marketing_bp, render


@marketing_bp.route("/")
@login_required
def overview():
    campaign_states = campaigns.counts_by_state()
    offer_states = catalog.counts_by_state()

    today = date.today()
    horizon = (today + timedelta(days=30)).isoformat()
    upcoming = [
        c for c in campaigns.calendar_entries(today.isoformat(), horizon)
        if c["state"] in ("scheduled", "running", "approved")
    ]

    awaiting = campaigns.list_campaigns(state="in_review")
    offers_awaiting = catalog.list_offers(state="in_review")

    # Draft campaigns that cannot yet be submitted — the real "what do I do next".
    blocked = []
    for row in campaigns.list_campaigns(state="draft"):
        detail = campaigns.get_campaign(row["id"])
        if not detail:
            continue
        status = campaigns.readiness(detail)
        if not status["ready"]:
            blocked.append({"campaign": detail, "missing": status["blocking_open"]})

    return render(
        "marketing/overview.html",
        active="overview",
        stats={
            "campaigns_total": sum(campaign_states.values()),
            "campaigns_running": campaign_states.get("running", 0),
            "campaigns_draft": campaign_states.get("draft", 0),
            "offers_live": offer_states.get("live", 0),
            "offers_total": sum(offer_states.values()),
            "segments": len(segments.list_segments()),
            "suppressed": consent.suppression_count(),
            "policies": len([p for p in consent.list_policies(active_only=True)]),
        },
        campaign_states=campaign_states,
        upcoming=upcoming,
        awaiting=awaiting,
        offers_awaiting=offers_awaiting,
        blocked=blocked[:5],
        blocked_total=len(blocked),
        provider_status=providers.status(),
        msisdn_normalised=config.msisdn_normalisation_active(),
    )
