"""Offer & product catalog.

The catalog is the portal's anchor entity: campaigns reference offers, and the
Sales and Support portals will read them over an API rather than re-declaring
their own plan lists.
"""

from __future__ import annotations

from .. import audit, config
from ..db import cursor, rows_to_dicts
from .common import (
    ValidationError,
    check_date_order,
    clean,
    clean_or_none,
    normalise_code,
    now_iso,
    parse_date,
    parse_int,
    parse_number,
    require_choice,
)

ENTITY = "offer"


def _decorate(row: dict) -> dict:
    state = row.get("state") or "draft"
    meta = config.OFFER_STATES.get(state, {})
    row["state_label"] = meta.get("label", state)
    row["state_tone"] = meta.get("tone", "neutral")
    row["family_label"] = config.OFFER_FAMILIES.get(row.get("family") or "", row.get("family") or "")
    row["editable"] = state not in config.OFFER_LOCKED_STATES
    return row


def list_offers(
    *, state: str | None = None, family: str | None = None, query: str | None = None
) -> list[dict]:
    sql = "SELECT * FROM offer"
    where, params = [], []
    if state:
        where.append("state = ?")
        params.append(state)
    if family:
        where.append("family = ?")
        params.append(family)
    text = clean(query, 80)
    if text:
        where.append("(name LIKE ? OR code LIKE ? OR description LIKE ?)")
        like = f"%{text}%"
        params += [like, like, like]
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY CASE state WHEN 'live' THEN 0 WHEN 'approved' THEN 1 "
    sql += "WHEN 'in_review' THEN 2 WHEN 'draft' THEN 3 ELSE 4 END, name COLLATE NOCASE"
    with cursor() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_decorate(row) for row in rows_to_dicts(rows)]


def get_offer(offer_id: int) -> dict | None:
    with cursor() as conn:
        row = conn.execute("SELECT * FROM offer WHERE id = ?", (offer_id,)).fetchone()
    return _decorate(dict(row)) if row else None


def sellable_offers() -> list[dict]:
    """Offers a campaign is allowed to promote."""
    with cursor() as conn:
        rows = conn.execute(
            "SELECT * FROM offer WHERE state IN ('approved', 'live') ORDER BY name COLLATE NOCASE"
        ).fetchall()
    return [_decorate(row) for row in rows_to_dicts(rows)]


def _validate(form: dict, *, existing: dict | None = None) -> dict:
    errors: dict[str, str] = {}
    data: dict = {}

    try:
        data["code"] = normalise_code(form.get("code"))
    except ValidationError as exc:
        errors.update(exc.errors)

    name = clean(form.get("name"), 120)
    if len(name) < 3:
        errors["name"] = "Give the offer a name of at least 3 characters."
    data["name"] = name

    try:
        data["family"] = require_choice(form.get("family"), config.OFFER_FAMILIES, "family")
    except ValidationError as exc:
        errors.update(exc.errors)

    data["description"] = clean_or_none(form.get("description"), 2000)
    data["eligibility"] = clean_or_none(form.get("eligibility"), 2000)
    data["terms_url"] = clean_or_none(form.get("terms_url"), 300)
    data["owner"] = clean_or_none(form.get("owner"), 120)
    data["price_currency"] = clean(form.get("price_currency"), 8).upper() or None
    data["price_period"] = clean_or_none(form.get("price_period"), 24)

    for field, kwargs in (
        ("price_amount", {"minimum": 0}),
        ("promo_amount", {"minimum": 0}),
    ):
        try:
            data[field] = parse_number(form.get(field), field, **kwargs)
        except ValidationError as exc:
            errors.update(exc.errors)

    try:
        data["commitment_months"] = parse_int(
            form.get("commitment_months"), "commitment_months", minimum=0, maximum=120
        )
    except ValidationError as exc:
        errors.update(exc.errors)

    for field in ("valid_from", "valid_to", "promo_ends_on"):
        try:
            data[field] = parse_date(form.get(field), field)
        except ValidationError as exc:
            errors.update(exc.errors)

    if not errors:
        check_date_order(
            data.get("valid_from"),
            data.get("valid_to"),
            "valid_to",
            "The end date cannot fall before the start date.",
        )
        if data.get("promo_amount") is not None and data.get("price_amount") is None:
            errors["price_amount"] = "Set the standard price before adding a promotional price."
        elif (
            data.get("promo_amount") is not None
            and data.get("price_amount") is not None
            and data["promo_amount"] > data["price_amount"]
        ):
            errors["promo_amount"] = "The promotional price is higher than the standard price."
        if data.get("promo_amount") is not None and not data.get("promo_ends_on"):
            errors["promo_ends_on"] = "A promotional price needs an end date."

    if errors:
        raise ValidationError(errors)

    with cursor() as conn:
        clash = conn.execute(
            "SELECT id FROM offer WHERE code = ? AND id != ?",
            (data["code"], (existing or {}).get("id", 0)),
        ).fetchone()
    if clash:
        raise ValidationError({"code": "Another offer already uses this code."})

    return data


_FIELDS = (
    "code", "name", "family", "description", "price_amount", "price_currency",
    "price_period", "promo_amount", "promo_ends_on", "commitment_months",
    "valid_from", "valid_to", "eligibility", "terms_url", "owner",
)


def create_offer(form: dict, user) -> int:
    data = _validate(form)
    stamp = now_iso()
    columns = ", ".join(_FIELDS) + ", state, created_at, created_by, updated_at, updated_by"
    placeholders = ", ".join(["?"] * (len(_FIELDS) + 5))
    values = [data.get(f) for f in _FIELDS] + [
        "draft", stamp, user.username, stamp, user.username,
    ]
    with cursor() as conn:
        cur = conn.execute(f"INSERT INTO offer ({columns}) VALUES ({placeholders})", values)
        offer_id = int(cur.lastrowid)
        audit.record(
            "offer.created",
            actor=user.username,
            actor_role=user.role,
            entity_type=ENTITY,
            entity_id=offer_id,
            summary=f"Created offer {data['code']} — {data['name']}",
            conn=conn,
        )
    return offer_id


def update_offer(offer_id: int, form: dict, user) -> None:
    existing = get_offer(offer_id)
    if not existing:
        raise ValidationError({"_": "That offer no longer exists."})
    if not existing["editable"]:
        raise ValidationError(
            {"_": f"A {existing['state_label'].lower()} offer cannot be edited. Reopen it as a draft first."}
        )
    data = _validate(form, existing=existing)
    changed = {
        field: {"from": existing.get(field), "to": data.get(field)}
        for field in _FIELDS
        if existing.get(field) != data.get(field)
    }
    assignments = ", ".join(f"{f} = ?" for f in _FIELDS)
    values = [data.get(f) for f in _FIELDS] + [now_iso(), user.username, offer_id]
    with cursor() as conn:
        conn.execute(
            f"UPDATE offer SET {assignments}, updated_at = ?, updated_by = ? WHERE id = ?",
            values,
        )
        audit.record(
            "offer.updated",
            actor=user.username,
            actor_role=user.role,
            entity_type=ENTITY,
            entity_id=offer_id,
            summary=f"Updated offer {existing['code']}",
            detail={"changes": changed} if changed else None,
            conn=conn,
        )


def available_transitions(offer: dict, user) -> list[dict]:
    options = config.OFFER_TRANSITIONS.get(offer.get("state") or "draft", [])
    return [
        {"to": to, "label": label, "permission": permission}
        for to, label, permission in options
        if user.can(permission)
    ]


def transition_offer(offer_id: int, to_state: str, user, note: str = "") -> None:
    offer = get_offer(offer_id)
    if not offer:
        raise ValidationError({"_": "That offer no longer exists."})
    allowed = {t["to"]: t for t in available_transitions(offer, user)}
    if to_state not in allowed:
        raise ValidationError(
            {"_": f"Moving an offer from {offer['state_label'].lower()} to that state is not allowed."}
        )
    if to_state in ("in_review", "approved", "live") and offer.get("price_amount") is None:
        raise ValidationError({"_": "Set a price before submitting this offer for review."})
    with cursor() as conn:
        conn.execute(
            "UPDATE offer SET state = ?, updated_at = ?, updated_by = ? WHERE id = ?",
            (to_state, now_iso(), user.username, offer_id),
        )
        audit.record(
            "offer.state_changed",
            actor=user.username,
            actor_role=user.role,
            entity_type=ENTITY,
            entity_id=offer_id,
            summary=f"{offer['code']}: {offer['state']} → {to_state}",
            detail={"from": offer["state"], "to": to_state, "note": clean(note, 500)},
            conn=conn,
        )


def counts_by_state() -> dict[str, int]:
    with cursor() as conn:
        rows = conn.execute("SELECT state, COUNT(*) AS n FROM offer GROUP BY state").fetchall()
    return {row["state"]: int(row["n"]) for row in rows}
