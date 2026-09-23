"""Campaigns — the unit of work for the marketing function.

A campaign ties together an audience, one or more offers, a channel mix, a
budget, a schedule, and a holdout group. The readiness check below is the gate
that stops a half-built campaign reaching approval.
"""

from __future__ import annotations

from .. import audit, config, providers
from ..db import cursor, rows_to_dicts
from . import catalog, consent, segments
from .common import (
    ValidationError,
    check_date_order,
    clean,
    clean_or_none,
    normalise_code,
    now_iso,
    parse_date,
    parse_number,
    require_choice,
)

ENTITY = "campaign"


def _decorate(row: dict) -> dict:
    state = row.get("state") or "draft"
    meta = config.CAMPAIGN_STATES.get(state, {})
    row["state_label"] = meta.get("label", state)
    row["state_tone"] = meta.get("tone", "neutral")
    row["objective_label"] = config.CAMPAIGN_OBJECTIVES.get(
        row.get("objective") or "", row.get("objective") or ""
    )
    row["editable"] = state not in config.CAMPAIGN_LOCKED_STATES
    return row


def list_campaigns(
    *, state: str | None = None, objective: str | None = None, query: str | None = None
) -> list[dict]:
    sql = (
        "SELECT c.*, s.name AS segment_name, "
        "(SELECT COUNT(*) FROM campaign_channel cc WHERE cc.campaign_id = c.id) AS channel_count, "
        "(SELECT COUNT(*) FROM campaign_offer co WHERE co.campaign_id = c.id) AS offer_count "
        "FROM campaign c LEFT JOIN segment s ON s.id = c.segment_id"
    )
    where, params = [], []
    if state:
        where.append("c.state = ?")
        params.append(state)
    if objective:
        where.append("c.objective = ?")
        params.append(objective)
    text = clean(query, 80)
    if text:
        where.append("(c.name LIKE ? OR c.code LIKE ? OR c.description LIKE ?)")
        params += [f"%{text}%"] * 3
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY CASE c.state WHEN 'running' THEN 0 WHEN 'scheduled' THEN 1 "
    sql += "WHEN 'in_review' THEN 2 WHEN 'approved' THEN 3 WHEN 'draft' THEN 4 ELSE 5 END, "
    sql += "IFNULL(c.starts_on, '9999-12-31'), c.name COLLATE NOCASE"
    with cursor() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_decorate(row) for row in rows_to_dicts(rows)]


def get_campaign(campaign_id: int) -> dict | None:
    with cursor() as conn:
        row = conn.execute(
            "SELECT c.*, s.name AS segment_name FROM campaign c "
            "LEFT JOIN segment s ON s.id = c.segment_id WHERE c.id = ?",
            (campaign_id,),
        ).fetchone()
        if not row:
            return None
        campaign = _decorate(dict(row))
        campaign["channels"] = rows_to_dicts(
            conn.execute(
                "SELECT * FROM campaign_channel WHERE campaign_id = ? ORDER BY channel",
                (campaign_id,),
            ).fetchall()
        )
        campaign["offers"] = rows_to_dicts(
            conn.execute(
                "SELECT o.* FROM campaign_offer co JOIN offer o ON o.id = co.offer_id "
                "WHERE co.campaign_id = ? ORDER BY o.name COLLATE NOCASE",
                (campaign_id,),
            ).fetchall()
        )
    for channel in campaign["channels"]:
        channel["channel_label"] = config.CHANNELS.get(channel["channel"], {}).get(
            "label", channel["channel"]
        )
    campaign["channel_keys"] = [c["channel"] for c in campaign["channels"]]
    return campaign


def _validate(form: dict, *, existing: dict | None = None) -> dict:
    errors: dict[str, str] = {}
    data: dict = {}

    try:
        data["code"] = normalise_code(form.get("code"))
    except ValidationError as exc:
        errors.update(exc.errors)

    name = clean(form.get("name"), 120)
    if len(name) < 3:
        errors["name"] = "Give the campaign a name of at least 3 characters."
    data["name"] = name

    try:
        data["objective"] = require_choice(
            form.get("objective"), config.CAMPAIGN_OBJECTIVES, "objective"
        )
    except ValidationError as exc:
        errors.update(exc.errors)

    data["description"] = clean_or_none(form.get("description"), 2000)
    data["owner"] = clean_or_none(form.get("owner"), 120)
    data["budget_currency"] = clean(form.get("budget_currency"), 8).upper() or None

    segment_raw = clean(form.get("segment_id"), 12)
    if segment_raw:
        if not segment_raw.isdigit() or not segments.get_segment(int(segment_raw)):
            errors["segment_id"] = "Choose an existing segment."
        else:
            data["segment_id"] = int(segment_raw)
    else:
        data["segment_id"] = None

    try:
        data["budget_amount"] = parse_number(form.get("budget_amount"), "budget_amount", minimum=0)
    except ValidationError as exc:
        errors.update(exc.errors)

    try:
        holdout = parse_number(form.get("holdout_pct"), "holdout_pct", minimum=0, maximum=50)
        data["holdout_pct"] = 0.0 if holdout is None else holdout
    except ValidationError as exc:
        errors.update(exc.errors)

    for field in ("starts_on", "ends_on"):
        try:
            data[field] = parse_date(form.get(field), field)
        except ValidationError as exc:
            errors.update(exc.errors)

    if errors:
        raise ValidationError(errors)

    check_date_order(
        data.get("starts_on"), data.get("ends_on"), "ends_on",
        "The end date cannot fall before the start date.",
    )

    with cursor() as conn:
        clash = conn.execute(
            "SELECT id FROM campaign WHERE code = ? AND id != ?",
            (data["code"], (existing or {}).get("id", 0)),
        ).fetchone()
    if clash:
        raise ValidationError({"code": "Another campaign already uses this code."})

    return data


_FIELDS = (
    "code", "name", "objective", "description", "segment_id", "holdout_pct",
    "budget_amount", "budget_currency", "starts_on", "ends_on", "owner",
)


def create_campaign(form: dict, user) -> int:
    data = _validate(form)
    stamp = now_iso()
    columns = ", ".join(_FIELDS) + ", state, created_at, created_by, updated_at, updated_by"
    placeholders = ", ".join(["?"] * (len(_FIELDS) + 5))
    values = [data.get(f) for f in _FIELDS] + ["draft", stamp, user.username, stamp, user.username]
    with cursor() as conn:
        cur = conn.execute(f"INSERT INTO campaign ({columns}) VALUES ({placeholders})", values)
        campaign_id = int(cur.lastrowid)
        audit.record(
            "campaign.created",
            actor=user.username,
            actor_role=user.role,
            entity_type=ENTITY,
            entity_id=campaign_id,
            summary=f"Created campaign {data['code']} — {data['name']}",
            conn=conn,
        )
    return campaign_id


def update_campaign(campaign_id: int, form: dict, user) -> None:
    existing = get_campaign(campaign_id)
    if not existing:
        raise ValidationError({"_": "That campaign no longer exists."})
    if not existing["editable"]:
        raise ValidationError(
            {"_": f"A {existing['state_label'].lower()} campaign cannot be edited."}
        )
    data = _validate(form, existing=existing)
    assignments = ", ".join(f"{f} = ?" for f in _FIELDS)
    values = [data.get(f) for f in _FIELDS] + [now_iso(), user.username, campaign_id]
    with cursor() as conn:
        conn.execute(
            f"UPDATE campaign SET {assignments}, updated_at = ?, updated_by = ? WHERE id = ?",
            values,
        )
        audit.record(
            "campaign.updated",
            actor=user.username,
            actor_role=user.role,
            entity_type=ENTITY,
            entity_id=campaign_id,
            summary=f"Updated campaign {existing['code']}",
            conn=conn,
        )


def set_channels(campaign_id: int, submitted: list[dict], user) -> None:
    campaign = get_campaign(campaign_id)
    if not campaign:
        raise ValidationError({"_": "That campaign no longer exists."})
    if not campaign["editable"]:
        raise ValidationError({"_": "The channel mix is locked once a campaign is scheduled."})

    rows = []
    seen = set()
    for entry in submitted or []:
        channel = clean(entry.get("channel"), 32).lower()
        if not channel or channel in seen:
            continue
        if channel not in config.CHANNELS:
            raise ValidationError({"channels": f"Unknown channel: {channel}"})
        seen.add(channel)
        rows.append(
            (
                campaign_id,
                channel,
                clean_or_none(entry.get("template_ref"), 200),
                clean_or_none(entry.get("send_window"), 120),
                clean_or_none(entry.get("notes"), 500),
            )
        )

    with cursor() as conn:
        conn.execute("DELETE FROM campaign_channel WHERE campaign_id = ?", (campaign_id,))
        if rows:
            conn.executemany(
                "INSERT INTO campaign_channel (campaign_id, channel, template_ref, send_window, notes) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )
        conn.execute(
            "UPDATE campaign SET updated_at = ?, updated_by = ? WHERE id = ?",
            (now_iso(), user.username, campaign_id),
        )
        audit.record(
            "campaign.channels_set",
            actor=user.username,
            actor_role=user.role,
            entity_type=ENTITY,
            entity_id=campaign_id,
            summary=f"{campaign['code']}: channel mix set to {', '.join(sorted(seen)) or 'none'}",
            conn=conn,
        )


def set_offers(campaign_id: int, offer_ids: list[int], user) -> None:
    campaign = get_campaign(campaign_id)
    if not campaign:
        raise ValidationError({"_": "That campaign no longer exists."})
    if not campaign["editable"]:
        raise ValidationError({"_": "The offer list is locked once a campaign is scheduled."})

    allowed = {offer["id"] for offer in catalog.sellable_offers()}
    chosen = []
    for raw in offer_ids or []:
        try:
            offer_id = int(raw)
        except (TypeError, ValueError):
            continue
        if offer_id not in allowed:
            raise ValidationError(
                {"offers": "A campaign can only promote offers that are approved or live."}
            )
        chosen.append(offer_id)

    with cursor() as conn:
        conn.execute("DELETE FROM campaign_offer WHERE campaign_id = ?", (campaign_id,))
        if chosen:
            conn.executemany(
                "INSERT INTO campaign_offer (campaign_id, offer_id) VALUES (?, ?)",
                [(campaign_id, oid) for oid in chosen],
            )
        conn.execute(
            "UPDATE campaign SET updated_at = ?, updated_by = ? WHERE id = ?",
            (now_iso(), user.username, campaign_id),
        )
        audit.record(
            "campaign.offers_set",
            actor=user.username,
            actor_role=user.role,
            entity_type=ENTITY,
            entity_id=campaign_id,
            summary=f"{campaign['code']}: {len(chosen)} offer(s) attached",
            conn=conn,
        )


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------

def readiness(campaign: dict) -> dict:
    """Pre-flight checklist. ``blocking`` items stop a campaign being approved."""
    checks: list[dict] = []

    def add(key: str, label: str, ok: bool, blocking: bool, detail: str = "") -> None:
        checks.append(
            {"key": key, "label": label, "ok": bool(ok), "blocking": blocking, "detail": detail}
        )

    add(
        "audience",
        "An audience segment is selected",
        bool(campaign.get("segment_id")),
        True,
        "Attach a segment so the campaign has a defined target.",
    )
    add(
        "channels",
        "At least one channel is configured",
        bool(campaign.get("channels")),
        True,
        "Add the channels this campaign will run on.",
    )
    add(
        "offers",
        "At least one offer is attached",
        bool(campaign.get("offers")),
        True,
        "Attach an approved or live offer from the catalog.",
    )
    add(
        "schedule",
        "Start and end dates are set",
        bool(campaign.get("starts_on") and campaign.get("ends_on")),
        True,
        "Set the window this campaign runs in.",
    )

    channel_keys = campaign.get("channel_keys") or []
    policies = consent.policies_for_channels(channel_keys)
    add(
        "policy",
        "An active contact policy covers every channel",
        bool(channel_keys) and bool(policies),
        True,
        "No active contact policy governs these channels — frequency caps and quiet hours "
        "would be unenforced.",
    )

    templates_set = all(c.get("template_ref") for c in campaign.get("channels") or [])
    add(
        "templates",
        "Every channel has a creative/template reference",
        bool(campaign.get("channels")) and templates_set,
        False,
        "Reference the approved creative for each channel.",
    )
    add(
        "holdout",
        "A control (holdout) group is set aside",
        float(campaign.get("holdout_pct") or 0) > 0,
        False,
        "Without a holdout, the campaign's uplift cannot be measured — only its raw response.",
    )
    add(
        "budget",
        "A budget is recorded",
        campaign.get("budget_amount") is not None,
        False,
        "Record the budget so cost per acquisition can be reported later.",
    )

    # Network-aware targeting gate (PrimeNet API via NetworkFootprintProvider).
    network_gate = _network_targeting_gate(campaign)
    if network_gate is not None:
        add(**network_gate)

    blocking_open = [c for c in checks if c["blocking"] and not c["ok"]]
    return {
        "checks": checks,
        "ready": not blocking_open,
        "blocking_open": blocking_open,
        "advisory_open": [c for c in checks if not c["blocking"] and not c["ok"]],
        "policies": policies,
        "network": network_gate_context(campaign),
    }


def _segment_uses_network(campaign: dict) -> bool:
    segment = campaign.get("segment")
    if not segment and campaign.get("segment_id"):
        from . import segments as segments_repo

        segment = segments_repo.get_segment(int(campaign["segment_id"]))
    if not segment:
        return False
    sources = segment.get("sources") or []
    return any(s.get("key") == "network" for s in sources)


def _network_targeting_gate(campaign: dict) -> dict | None:
    """Blocking when network rules exist but PrimeNet API is offline; else capacity advisory."""
    if not _segment_uses_network(campaign):
        return None
    footprint = providers.get("network_footprint")
    if not footprint.available():
        return {
            "key": "network_api",
            "label": "Network targeting requires the PrimeNet footprint API",
            "ok": False,
            "blocking": True,
            "detail": (
                "This audience uses Engineering Portal attributes "
                "(coverage / congestion / serviceability). Connect "
                "NEXUS_PRIMENET_API_URL + NEXUS_PORTAL_API_TOKEN, or remove network rules."
            ),
        }
    congested = footprint.congested_sites()
    if not congested.available:
        return {
            "key": "network_capacity",
            "label": "Capacity pressure data is available from PrimeNet",
            "ok": False,
            "blocking": False,
            "detail": congested.reason or "Could not load congested sites.",
        }
    value = congested.value or {}
    site_count = int(value.get("site_count") or len(value.get("sites") or []))
    # Advisory capacity gate: warn when the network is under broad pressure.
    ok = site_count < 25
    return {
        "key": "network_capacity",
        "label": "Capacity gate — congested sites within policy",
        "ok": ok,
        "blocking": False,
        "detail": (
            f"{site_count} congested site(s) reported by PrimeNet Capacity Hotspots. "
            + (
                "Below the soft gate (25) — OK to proceed with awareness."
                if ok
                else "Elevated congestion — prefer non-congested targeting or throttle heavy offers."
            )
        ),
    }


def network_gate_context(campaign: dict) -> dict:
    """Snapshot for campaign detail UI (never invents numbers)."""
    footprint = providers.get("network_footprint")
    ctx = {
        "uses_network_rules": _segment_uses_network(campaign),
        "provider_available": bool(footprint.available()),
    }
    if not footprint.available():
        ctx["reason"] = (
            "PrimeNet network API not connected "
            "(NEXUS_PRIMENET_API_URL / NEXUS_PORTAL_API_TOKEN)."
        )
        return ctx
    bundle = footprint.footprint_bundle()
    if not bundle.available:
        ctx["reason"] = bundle.reason
        return ctx
    data = bundle.value or {}
    tech = data.get("technology_footprint") or {}
    congested = data.get("congested") or {}
    service = data.get("serviceability") or {}
    ctx.update(
        {
            "as_of": bundle.as_of or data.get("as_of"),
            "technologies": (tech.get("technologies") if isinstance(tech, dict) else None) or [],
            "totals": (tech.get("totals") if isinstance(tech, dict) else None) or {},
            "congested_site_count": (
                congested.get("site_count") if isinstance(congested, dict) else None
            ),
            "serviceability_gap_count": (
                service.get("gap_count") if isinstance(service, dict) else None
            ),
            "source": bundle.source,
        }
    )
    return ctx


def available_transitions(campaign: dict, user) -> list[dict]:
    options = config.CAMPAIGN_TRANSITIONS.get(campaign.get("state") or "draft", [])
    return [
        {"to": to, "label": label, "permission": permission}
        for to, label, permission in options
        if user.can(permission)
    ]


def transition_campaign(campaign_id: int, to_state: str, user, note: str = "") -> None:
    campaign = get_campaign(campaign_id)
    if not campaign:
        raise ValidationError({"_": "That campaign no longer exists."})
    allowed = {t["to"]: t for t in available_transitions(campaign, user)}
    if to_state not in allowed:
        raise ValidationError(
            {"_": f"Moving a campaign from {campaign['state_label'].lower()} to that state is not allowed."}
        )
    if to_state in ("in_review", "approved", "scheduled", "running"):
        status = readiness(campaign)
        if not status["ready"]:
            missing = "; ".join(c["label"] for c in status["blocking_open"])
            raise ValidationError({"_": f"The campaign is not ready: {missing}."})

    with cursor() as conn:
        conn.execute(
            "UPDATE campaign SET state = ?, updated_at = ?, updated_by = ? WHERE id = ?",
            (to_state, now_iso(), user.username, campaign_id),
        )
        audit.record(
            "campaign.state_changed",
            actor=user.username,
            actor_role=user.role,
            entity_type=ENTITY,
            entity_id=campaign_id,
            summary=f"{campaign['code']}: {campaign['state']} → {to_state}",
            detail={"from": campaign["state"], "to": to_state, "note": clean(note, 500)},
            conn=conn,
        )


def metrics(campaign_id: int):
    """Delivery/conversion funnel from whichever provider is connected."""
    return providers.get("campaign_metrics").funnel(campaign_id)


def counts_by_state() -> dict[str, int]:
    with cursor() as conn:
        rows = conn.execute("SELECT state, COUNT(*) AS n FROM campaign GROUP BY state").fetchall()
    return {row["state"]: int(row["n"]) for row in rows}


def calendar_entries(start: str, end: str) -> list[dict]:
    """Campaigns whose run window overlaps [start, end]."""
    with cursor() as conn:
        rows = conn.execute(
            "SELECT c.*, s.name AS segment_name FROM campaign c "
            "LEFT JOIN segment s ON s.id = c.segment_id "
            "WHERE c.starts_on IS NOT NULL AND c.ends_on IS NOT NULL "
            "AND c.starts_on <= ? AND c.ends_on >= ? "
            "AND c.state NOT IN ('cancelled') ORDER BY c.starts_on",
            (end, start),
        ).fetchall()
    return [_decorate(row) for row in rows_to_dicts(rows)]
