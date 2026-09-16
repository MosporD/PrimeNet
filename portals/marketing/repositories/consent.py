"""Consent, suppression, and contact policy.

This is the regulated half of the portal. Three separate things live here and
they are deliberately not merged:

* **Consent** — what a subscriber agreed to, per channel, with evidence.
* **Suppression** — hard blocks (do-not-call registers, complaints, legal
  holds) that override consent.
* **Contact policy** — how often anyone may be contacted, and when.

A campaign is contactable only when all three agree. Every write is audited.
"""

from __future__ import annotations

import re

from .. import audit, config
from ..config import (
    CHANNELS,
    CONSENT_SOURCES,
    CONSENT_STATUSES,
    IDENTIFIER_TYPES,
    SUPPRESSION_REASONS,
    SUPPRESSION_SCOPES,
)
from ..db import cursor, rows_to_dicts
from .common import (
    ValidationError,
    clean,
    clean_or_none,
    now_iso,
    parse_date,
    parse_int,
    require_choice,
)

ENTITY_CONSENT = "consent"
ENTITY_SUPPRESSION = "suppression"
ENTITY_POLICY = "contact_policy"

POLICY_SCOPES = {"all": "All subscribers", "prospects": "Prospects only", "customers": "Customers only"}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _canonical_msisdn(raw: str) -> str:
    """Collapse national and international spellings onto one value.

    Without this, a do-not-call entry recorded as ``0791234567`` would not stop
    a send addressed to ``+962791234567``. When no country code is configured
    the digits are stored as entered and the consent screens flag that
    matching is literal.
    """
    digits = re.sub(r"[^\d]", "", raw)
    if digits.startswith("00"):
        digits = digits[2:]
    country = config.msisdn_country_code()
    if country:
        trunk = config.msisdn_national_prefix()
        if not digits.startswith(country):
            if trunk and digits.startswith(trunk):
                digits = country + digits[len(trunk):]
            else:
                digits = country + digits
    if not 6 <= len(digits) <= 15:
        raise ValidationError({"identifier": "Enter a valid MSISDN (6-15 digits)."})
    return digits


def normalise_identifier(identifier_type: str, value: str) -> tuple[str, str]:
    """Normalise so the same subscriber is not stored three different ways."""
    kind = require_choice(identifier_type, IDENTIFIER_TYPES, "identifier_type")
    raw = clean(value, 120)
    if not raw:
        raise ValidationError({"identifier": "Enter an identifier."})
    if kind == "msisdn":
        return kind, _canonical_msisdn(raw)
    if kind == "email":
        lowered = raw.lower()
        if not _EMAIL_RE.match(lowered):
            raise ValidationError({"identifier": "Enter a valid email address."})
        return kind, lowered
    return kind, raw


def _parse_time(value, field: str) -> str | None:
    text = clean(value, 5)
    if not text:
        return None
    if not _TIME_RE.match(text):
        raise ValidationError({field: "Use 24-hour time, for example 21:00."})
    return text


# ---------------------------------------------------------------------------
# Consent records
# ---------------------------------------------------------------------------

def _decorate_consent(row: dict) -> dict:
    row["status_label"] = CONSENT_STATUSES.get(row.get("status") or "", row.get("status"))
    row["channel_label"] = CHANNELS.get(row.get("channel") or "", {}).get("label", row.get("channel"))
    row["source_label"] = CONSENT_SOURCES.get(row.get("source") or "", row.get("source"))
    row["type_label"] = IDENTIFIER_TYPES.get(row.get("identifier_type") or "", row.get("identifier_type"))
    row["contactable"] = row.get("status") == "opt_in"
    return row


def list_consent(*, status: str | None = None, channel: str | None = None,
                 query: str | None = None, limit: int = 200) -> list[dict]:
    sql = "SELECT * FROM consent_record"
    where, params = [], []
    if status:
        where.append("status = ?")
        params.append(status)
    if channel:
        where.append("channel = ?")
        params.append(channel)
    text = clean(query, 120)
    if text:
        where.append("identifier LIKE ?")
        params.append(f"%{text}%")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY recorded_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 1000)))
    with cursor() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_decorate_consent(row) for row in rows_to_dicts(rows)]


def record_consent(form: dict, user) -> int:
    kind, identifier = normalise_identifier(form.get("identifier_type"), form.get("identifier"))
    channel = require_choice(form.get("channel"), CHANNELS, "channel")
    status = require_choice(form.get("status"), CONSENT_STATUSES, "status")
    source = require_choice(form.get("source"), CONSENT_SOURCES, "source")
    captured_at = parse_date(form.get("captured_at"), "captured_at", required=True)
    expires_at = parse_date(form.get("expires_at"), "expires_at")
    if expires_at and expires_at < captured_at:
        raise ValidationError({"expires_at": "Expiry cannot fall before the capture date."})
    evidence = clean_or_none(form.get("evidence_ref"), 200)
    if status == "opt_in" and not evidence:
        raise ValidationError(
            {"evidence_ref": "An opt-in needs an evidence reference (form ID, call ID, contract number)."}
        )
    notes = clean_or_none(form.get("notes"), 1000)
    stamp = now_iso()

    with cursor() as conn:
        previous = conn.execute(
            "SELECT status FROM consent_record WHERE identifier_type = ? AND identifier = ? AND channel = ?",
            (kind, identifier, channel),
        ).fetchone()
        conn.execute(
            "INSERT INTO consent_record (identifier_type, identifier, channel, status, source, "
            "evidence_ref, captured_at, expires_at, notes, recorded_at, recorded_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(identifier_type, identifier, channel) DO UPDATE SET "
            "status = excluded.status, source = excluded.source, evidence_ref = excluded.evidence_ref, "
            "captured_at = excluded.captured_at, expires_at = excluded.expires_at, "
            "notes = excluded.notes, recorded_at = excluded.recorded_at, recorded_by = excluded.recorded_by",
            (kind, identifier, channel, status, source, evidence, captured_at, expires_at,
             notes, stamp, user.username),
        )
        row = conn.execute(
            "SELECT id FROM consent_record WHERE identifier_type = ? AND identifier = ? AND channel = ?",
            (kind, identifier, channel),
        ).fetchone()
        record_id = int(row["id"])
        audit.record(
            "consent.recorded",
            actor=user.username,
            actor_role=user.role,
            entity_type=ENTITY_CONSENT,
            entity_id=record_id,
            summary=f"{CHANNELS[channel]['label']} consent for {identifier} set to {CONSENT_STATUSES[status]}",
            detail={
                "identifier_type": kind,
                "channel": channel,
                "from": previous["status"] if previous else None,
                "to": status,
                "source": source,
                "evidence_ref": evidence,
            },
            conn=conn,
        )
    return record_id


def consent_summary() -> dict[str, int]:
    with cursor() as conn:
        rows = conn.execute("SELECT status, COUNT(*) AS n FROM consent_record GROUP BY status").fetchall()
    return {row["status"]: int(row["n"]) for row in rows}


# ---------------------------------------------------------------------------
# Suppression
# ---------------------------------------------------------------------------

def _decorate_suppression(row: dict) -> dict:
    row["reason_label"] = SUPPRESSION_REASONS.get(row.get("reason") or "", row.get("reason"))
    row["scope_label"] = SUPPRESSION_SCOPES.get(row.get("scope") or "", row.get("scope"))
    row["type_label"] = IDENTIFIER_TYPES.get(row.get("identifier_type") or "", row.get("identifier_type"))
    row["active"] = not row.get("released_at")
    return row


def list_suppression(*, active_only: bool = True, query: str | None = None,
                     limit: int = 200) -> list[dict]:
    sql = "SELECT * FROM suppression_entry"
    where, params = [], []
    if active_only:
        where.append("released_at IS NULL")
    text = clean(query, 120)
    if text:
        where.append("identifier LIKE ?")
        params.append(f"%{text}%")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY added_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 1000)))
    with cursor() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_decorate_suppression(row) for row in rows_to_dicts(rows)]


def add_suppression(form: dict, user) -> int:
    kind, identifier = normalise_identifier(form.get("identifier_type"), form.get("identifier"))
    scope = require_choice(form.get("scope"), SUPPRESSION_SCOPES, "scope")
    reason = require_choice(form.get("reason"), SUPPRESSION_REASONS, "reason")
    scope_ref = clean_or_none(form.get("scope_ref"), 120)
    if scope in ("channel", "campaign") and not scope_ref:
        raise ValidationError({"scope_ref": "Name the channel or campaign this block applies to."})
    if scope == "channel" and scope_ref not in CHANNELS:
        raise ValidationError({"scope_ref": "Choose a valid channel."})
    expires_at = parse_date(form.get("expires_at"), "expires_at")
    notes = clean_or_none(form.get("notes"), 1000)

    with cursor() as conn:
        existing = conn.execute(
            "SELECT id FROM suppression_entry WHERE identifier_type = ? AND identifier = ? "
            "AND scope = ? AND IFNULL(scope_ref, '') = IFNULL(?, '') AND released_at IS NULL",
            (kind, identifier, scope, scope_ref),
        ).fetchone()
        if existing:
            raise ValidationError({"identifier": "An active block already covers this identifier and scope."})
        cur = conn.execute(
            "INSERT INTO suppression_entry (identifier_type, identifier, scope, scope_ref, reason, "
            "notes, added_at, added_by, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (kind, identifier, scope, scope_ref, reason, notes, now_iso(), user.username, expires_at),
        )
        entry_id = int(cur.lastrowid)
        audit.record(
            "suppression.added",
            actor=user.username,
            actor_role=user.role,
            entity_type=ENTITY_SUPPRESSION,
            entity_id=entry_id,
            summary=f"Blocked {identifier} ({SUPPRESSION_SCOPES[scope]}) — {SUPPRESSION_REASONS[reason]}",
            detail={"scope": scope, "scope_ref": scope_ref, "reason": reason, "expires_at": expires_at},
            conn=conn,
        )
    return entry_id


def release_suppression(entry_id: int, user, note: str = "") -> None:
    with cursor() as conn:
        row = conn.execute(
            "SELECT * FROM suppression_entry WHERE id = ?", (entry_id,)
        ).fetchone()
        if not row:
            raise ValidationError({"_": "That suppression entry no longer exists."})
        if row["released_at"]:
            raise ValidationError({"_": "That entry has already been released."})
        conn.execute(
            "UPDATE suppression_entry SET released_at = ?, released_by = ? WHERE id = ?",
            (now_iso(), user.username, entry_id),
        )
        audit.record(
            "suppression.released",
            actor=user.username,
            actor_role=user.role,
            entity_type=ENTITY_SUPPRESSION,
            entity_id=entry_id,
            summary=f"Released block on {row['identifier']}",
            detail={"note": clean(note, 500)},
            conn=conn,
        )


def suppression_count(active_only: bool = True) -> int:
    sql = "SELECT COUNT(*) AS n FROM suppression_entry"
    if active_only:
        sql += " WHERE released_at IS NULL"
    with cursor() as conn:
        return int(conn.execute(sql).fetchone()["n"])


# ---------------------------------------------------------------------------
# Contact policy
# ---------------------------------------------------------------------------

def _decorate_policy(row: dict) -> dict:
    channel = row.get("channel") or "all"
    row["channel_label"] = "All channels" if channel == "all" else CHANNELS.get(channel, {}).get("label", channel)
    row["applies_label"] = POLICY_SCOPES.get(row.get("applies_to") or "all", row.get("applies_to"))
    row["quiet_hours"] = (
        f"{row['quiet_from']}–{row['quiet_to']}" if row.get("quiet_from") and row.get("quiet_to") else ""
    )
    row["cap_text"] = f"{row.get('max_contacts')} per {row.get('window_days')} day(s)"
    row["active"] = bool(row.get("active"))
    return row


def list_policies(*, active_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM contact_policy"
    if active_only:
        sql += " WHERE active = 1"
    sql += " ORDER BY active DESC, channel, name COLLATE NOCASE"
    with cursor() as conn:
        rows = conn.execute(sql).fetchall()
    return [_decorate_policy(row) for row in rows_to_dicts(rows)]


def get_policy(policy_id: int) -> dict | None:
    with cursor() as conn:
        row = conn.execute("SELECT * FROM contact_policy WHERE id = ?", (policy_id,)).fetchone()
    return _decorate_policy(dict(row)) if row else None


def _validate_policy(form: dict, existing: dict | None = None) -> dict:
    name = clean(form.get("name"), 120)
    if len(name) < 3:
        raise ValidationError({"name": "Give the policy a name of at least 3 characters."})
    channel = clean(form.get("channel"), 32).lower() or "all"
    if channel != "all" and channel not in CHANNELS:
        raise ValidationError({"channel": "Choose a valid channel."})
    applies_to = clean(form.get("applies_to"), 24).lower() or "all"
    if applies_to not in POLICY_SCOPES:
        raise ValidationError({"applies_to": "Choose who the policy applies to."})
    max_contacts = parse_int(form.get("max_contacts"), "max_contacts", minimum=0, maximum=100, required=True)
    window_days = parse_int(form.get("window_days"), "window_days", minimum=1, maximum=365, required=True)
    quiet_from = _parse_time(form.get("quiet_from"), "quiet_from")
    quiet_to = _parse_time(form.get("quiet_to"), "quiet_to")
    if bool(quiet_from) != bool(quiet_to):
        raise ValidationError({"quiet_to": "Set both ends of the quiet-hours window, or neither."})

    with cursor() as conn:
        clash = conn.execute(
            "SELECT id FROM contact_policy WHERE name = ? AND id != ?",
            (name, (existing or {}).get("id", 0)),
        ).fetchone()
    if clash:
        raise ValidationError({"name": "Another policy already uses this name."})

    return {
        "name": name,
        "channel": channel,
        "applies_to": applies_to,
        "max_contacts": max_contacts,
        "window_days": window_days,
        "quiet_from": quiet_from,
        "quiet_to": quiet_to,
        "timezone": clean_or_none(form.get("timezone"), 64),
        "notes": clean_or_none(form.get("notes"), 1000),
        "active": 1 if clean(form.get("active"), 8).lower() in ("1", "true", "on", "yes") else 0,
    }


_POLICY_FIELDS = (
    "name", "channel", "applies_to", "max_contacts", "window_days",
    "quiet_from", "quiet_to", "timezone", "notes", "active",
)


def create_policy(form: dict, user) -> int:
    data = _validate_policy(form)
    stamp = now_iso()
    columns = ", ".join(_POLICY_FIELDS) + ", created_at, created_by, updated_at, updated_by"
    placeholders = ", ".join(["?"] * (len(_POLICY_FIELDS) + 4))
    values = [data[f] for f in _POLICY_FIELDS] + [stamp, user.username, stamp, user.username]
    with cursor() as conn:
        cur = conn.execute(f"INSERT INTO contact_policy ({columns}) VALUES ({placeholders})", values)
        policy_id = int(cur.lastrowid)
        audit.record(
            "policy.created",
            actor=user.username,
            actor_role=user.role,
            entity_type=ENTITY_POLICY,
            entity_id=policy_id,
            summary=f"Created contact policy “{data['name']}”",
            detail=data,
            conn=conn,
        )
    return policy_id


def update_policy(policy_id: int, form: dict, user) -> None:
    existing = get_policy(policy_id)
    if not existing:
        raise ValidationError({"_": "That policy no longer exists."})
    data = _validate_policy(form, existing)
    assignments = ", ".join(f"{f} = ?" for f in _POLICY_FIELDS)
    values = [data[f] for f in _POLICY_FIELDS] + [now_iso(), user.username, policy_id]
    with cursor() as conn:
        conn.execute(
            f"UPDATE contact_policy SET {assignments}, updated_at = ?, updated_by = ? WHERE id = ?",
            values,
        )
        audit.record(
            "policy.updated",
            actor=user.username,
            actor_role=user.role,
            entity_type=ENTITY_POLICY,
            entity_id=policy_id,
            summary=f"Updated contact policy “{data['name']}”",
            detail=data,
            conn=conn,
        )


def policies_for_channels(channels: list[str]) -> list[dict]:
    """Active policies that would govern a campaign using these channels."""
    if not channels:
        return []
    active = list_policies(active_only=True)
    wanted = set(channels)
    return [p for p in active if p["channel"] == "all" or p["channel"] in wanted]


# ---------------------------------------------------------------------------
# Contactability lookup
# ---------------------------------------------------------------------------

def contactability(identifier_type: str, identifier: str) -> dict:
    """Per-channel verdict for one identifier: consent AND no suppression.

    This is the lookup an execution connector will call before sending. It is
    exposed in the UI so an agent can answer "why did this customer not get
    the campaign?" without reading the database.
    """
    kind, value = normalise_identifier(identifier_type, identifier)
    with cursor() as conn:
        consent_rows = rows_to_dicts(
            conn.execute(
                "SELECT * FROM consent_record WHERE identifier_type = ? AND identifier = ?",
                (kind, value),
            ).fetchall()
        )
        blocks = rows_to_dicts(
            conn.execute(
                "SELECT * FROM suppression_entry WHERE identifier_type = ? AND identifier = ? "
                "AND released_at IS NULL",
                (kind, value),
            ).fetchall()
        )

    by_channel = {row["channel"]: row for row in consent_rows}
    global_blocks = [b for b in blocks if b["scope"] == "global"]
    channel_blocks = {b["scope_ref"]: b for b in blocks if b["scope"] == "channel"}

    verdicts = []
    for channel, meta in CHANNELS.items():
        consent = by_channel.get(channel)
        block = global_blocks[0] if global_blocks else channel_blocks.get(channel)
        if block:
            verdicts.append({
                "channel": channel,
                "channel_label": meta["label"],
                "contactable": False,
                "reason": f"Blocked — {SUPPRESSION_REASONS.get(block['reason'], block['reason'])}",
                "blocking": True,
            })
            continue
        if not consent:
            verdicts.append({
                "channel": channel,
                "channel_label": meta["label"],
                "contactable": False,
                "reason": "No consent on record",
                "blocking": False,
            })
            continue
        ok = consent["status"] == "opt_in"
        verdicts.append({
            "channel": channel,
            "channel_label": meta["label"],
            "contactable": ok,
            "reason": CONSENT_STATUSES.get(consent["status"], consent["status"])
            + (f" — {CONSENT_SOURCES.get(consent['source'], consent['source'])}" if ok else ""),
            "blocking": False,
        })

    return {
        "identifier_type": kind,
        "identifier": value,
        "channels": verdicts,
        "suppressed": bool(blocks),
        "suppression": [_decorate_suppression(b) for b in blocks],
        "consent_records": [_decorate_consent(c) for c in consent_rows],
    }
