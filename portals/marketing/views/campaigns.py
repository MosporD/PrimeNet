"""Campaign screens: list, detail with readiness, calendar."""

from __future__ import annotations

from datetime import date, timedelta

from flask import abort, flash, redirect, request, url_for

from .. import audit, config
from ..access import current_user, require_permission
from ..repositories import ValidationError, campaigns, catalog, segments
from .blueprint import flash_errors, marketing_bp, render


def _month_bounds(value: str | None) -> tuple[date, date, str]:
    today = date.today()
    try:
        year, month = (int(p) for p in (value or "").split("-", 1))
        first = date(year, month, 1)
    except (ValueError, TypeError):
        first = today.replace(day=1)
    nxt = date(first.year + (first.month == 12), (first.month % 12) + 1, 1)
    return first, nxt - timedelta(days=1), first.strftime("%Y-%m")


@marketing_bp.route("/campaigns")
@require_permission(config.P_CAMPAIGN_VIEW)
def campaign_list():
    state = (request.args.get("state") or "").strip() or None
    objective = (request.args.get("objective") or "").strip() or None
    query = (request.args.get("q") or "").strip()
    return render(
        "marketing/campaign_list.html",
        active="campaigns",
        campaigns=campaigns.list_campaigns(state=state, objective=objective, query=query),
        counts=campaigns.counts_by_state(),
        filters={"state": state or "", "objective": objective or "", "q": query},
    )


@marketing_bp.route("/campaigns/calendar")
@require_permission(config.P_CAMPAIGN_VIEW)
def campaign_calendar():
    first, last, key = _month_bounds(request.args.get("month"))
    prev_month = (first - timedelta(days=1)).strftime("%Y-%m")
    next_month = (last + timedelta(days=1)).strftime("%Y-%m")
    entries = campaigns.calendar_entries(first.isoformat(), last.isoformat())
    for entry in entries:
        start = max(date.fromisoformat(entry["starts_on"]), first)
        end = min(date.fromisoformat(entry["ends_on"]), last)
        entry["bar_start"] = start.day
        entry["bar_span"] = (end - start).days + 1
        entry["clipped_left"] = date.fromisoformat(entry["starts_on"]) < first
        entry["clipped_right"] = date.fromisoformat(entry["ends_on"]) > last
    return render(
        "marketing/calendar.html",
        active="calendar",
        entries=entries,
        month_key=key,
        month_label=first.strftime("%B %Y"),
        days=last.day,
        prev_month=prev_month,
        next_month=next_month,
    )


@marketing_bp.route("/campaigns/new", methods=["GET", "POST"])
@require_permission(config.P_CAMPAIGN_EDIT)
def campaign_new():
    form = request.form.to_dict() if request.method == "POST" else {"holdout_pct": "10"}
    if request.method == "POST":
        try:
            campaign_id = campaigns.create_campaign(form, current_user())
            flash("Campaign created. Add channels and offers to make it ready.", "success")
            return redirect(url_for("marketing_portal.campaign_detail", campaign_id=campaign_id))
        except ValidationError as exc:
            flash_errors(exc.errors)
    return render(
        "marketing/campaign_form.html",
        active="campaigns",
        campaign=form,
        mode="new",
        segment_options=segments.list_segments(),
    )


@marketing_bp.route("/campaigns/<int:campaign_id>")
@require_permission(config.P_CAMPAIGN_VIEW)
def campaign_detail(campaign_id: int):
    campaign = campaigns.get_campaign(campaign_id)
    if not campaign:
        abort(404)
    user = current_user()
    segment = segments.get_segment(campaign["segment_id"]) if campaign.get("segment_id") else None
    return render(
        "marketing/campaign_detail.html",
        active="campaigns",
        campaign=campaign,
        segment=segment,
        estimate=segments.estimate_size(segment["definition"]) if segment else None,
        readiness=campaigns.readiness(campaign),
        metrics=campaigns.metrics(campaign_id),
        transitions=campaigns.available_transitions(campaign, user),
        offer_options=catalog.sellable_offers(),
        history=audit.recent(50, entity_type=campaigns.ENTITY, entity_id=campaign_id),
    )


@marketing_bp.route("/campaigns/<int:campaign_id>/edit", methods=["GET", "POST"])
@require_permission(config.P_CAMPAIGN_EDIT)
def campaign_edit(campaign_id: int):
    campaign = campaigns.get_campaign(campaign_id)
    if not campaign:
        abort(404)
    if request.method == "POST":
        form = request.form.to_dict()
        try:
            campaigns.update_campaign(campaign_id, form, current_user())
            flash("Campaign updated.", "success")
            return redirect(url_for("marketing_portal.campaign_detail", campaign_id=campaign_id))
        except ValidationError as exc:
            flash_errors(exc.errors)
            campaign = {**campaign, **form}
    return render(
        "marketing/campaign_form.html",
        active="campaigns",
        campaign=campaign,
        mode="edit",
        segment_options=segments.list_segments(),
    )


@marketing_bp.route("/campaigns/<int:campaign_id>/channels", methods=["POST"])
@require_permission(config.P_CAMPAIGN_EDIT)
def campaign_channels(campaign_id: int):
    submitted = [
        {
            "channel": channel,
            "template_ref": request.form.get(f"template_ref__{channel}"),
            "send_window": request.form.get(f"send_window__{channel}"),
            "notes": request.form.get(f"notes__{channel}"),
        }
        for channel in request.form.getlist("channel")
    ]
    try:
        campaigns.set_channels(campaign_id, submitted, current_user())
        flash("Channel mix saved.", "success")
    except ValidationError as exc:
        flash_errors(exc.errors)
    return redirect(url_for("marketing_portal.campaign_detail", campaign_id=campaign_id))


@marketing_bp.route("/campaigns/<int:campaign_id>/offers", methods=["POST"])
@require_permission(config.P_CAMPAIGN_EDIT)
def campaign_offers(campaign_id: int):
    try:
        campaigns.set_offers(campaign_id, request.form.getlist("offer_id"), current_user())
        flash("Offers saved.", "success")
    except ValidationError as exc:
        flash_errors(exc.errors)
    return redirect(url_for("marketing_portal.campaign_detail", campaign_id=campaign_id))


@marketing_bp.route("/campaigns/<int:campaign_id>/transition", methods=["POST"])
@require_permission(config.P_CAMPAIGN_EDIT)
def campaign_transition(campaign_id: int):
    try:
        campaigns.transition_campaign(
            campaign_id,
            (request.form.get("to_state") or "").strip(),
            current_user(),
            request.form.get("note") or "",
        )
        flash("Campaign status updated.", "success")
    except ValidationError as exc:
        flash_errors(exc.errors)
    return redirect(url_for("marketing_portal.campaign_detail", campaign_id=campaign_id))
