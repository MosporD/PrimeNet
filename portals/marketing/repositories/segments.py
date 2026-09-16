"""Audience segments — rule definitions and size estimation.

A segment is a stored, validated rule expression. It is deliberately not tied
to a query engine: the rules are evaluated by whichever
``SegmentSizeProvider`` is connected, so the definitions written today stay
valid when a real subscriber source arrives.
"""

from __future__ import annotations

import json

from .. import audit, providers
from ..config import SEGMENT_ATTRIBUTES, SEGMENT_OPERATORS
from ..db import cursor, rows_to_dicts
from .common import ValidationError, clean, clean_or_none, now_iso

ENTITY = "segment"

REFRESH_MODES = {
    "manual": "Manual refresh",
    "daily": "Daily",
    "weekly": "Weekly",
    "per_campaign": "Refresh when a campaign runs",
}

MATCH_MODES = {"all": "Match ALL rules", "any": "Match ANY rule"}

ATTRIBUTES_BY_KEY = {a["key"]: a for a in SEGMENT_ATTRIBUTES}

SOURCE_LABELS = {
    "crm": "CRM / subscriber master",
    "billing": "Billing",
    "usage": "Usage / mediation",
    "analytics": "Analytics models",
    "network": "Engineering Portal (PrimeNet) API",
}


# ---------------------------------------------------------------------------
# Rule validation
# ---------------------------------------------------------------------------

def _validate_rule(raw: dict, index: int) -> dict:
    field = f"rule_{index}"
    if not isinstance(raw, dict):
        raise ValidationError({field: "This rule is malformed."})

    key = clean(raw.get("attribute"), 64)
    attribute = ATTRIBUTES_BY_KEY.get(key)
    if not attribute:
        raise ValidationError({field: "Choose a subscriber attribute."})

    operator = clean(raw.get("operator"), 24).lower()
    spec = SEGMENT_OPERATORS.get(operator)
    if not spec:
        raise ValidationError({field: "Choose a comparison."})
    if attribute["type"] not in spec["types"]:
        raise ValidationError(
            {field: f"“{spec['label']}” cannot be used with {attribute['label']}."}
        )

    rule = {"attribute": key, "operator": operator}
    if spec.get("no_value"):
        return rule

    value = raw.get("value")
    if spec.get("multi"):
        if isinstance(value, str):
            value = [part.strip() for part in value.split(",")]
        if not isinstance(value, list):
            raise ValidationError({field: "Provide one or more values."})
        values = [clean(v, 120) for v in value if clean(v, 120)]
        if not values:
            raise ValidationError({field: "Provide at least one value."})
        if attribute["type"] == "enum":
            allowed = set(attribute.get("values") or [])
            bad = [v for v in values if v not in allowed]
            if bad:
                raise ValidationError({field: f"Not valid for {attribute['label']}: {', '.join(bad)}."})
        rule["value"] = values
        return rule

    if attribute["type"] == "number":
        text = clean(value, 24)
        if not text:
            raise ValidationError({field: "Enter a number."})
        try:
            rule["value"] = float(text)
        except ValueError:
            raise ValidationError({field: "Enter a number."}) from None
        return rule

    if attribute["type"] == "boolean":
        text = clean(value, 8).lower()
        if text not in ("true", "false", "1", "0", "yes", "no"):
            raise ValidationError({field: "Choose yes or no."})
        rule["value"] = text in ("true", "1", "yes")
        return rule

    text = clean(value, 120)
    if not text:
        raise ValidationError({field: "Enter a value."})
    if attribute["type"] == "enum" and text not in (attribute.get("values") or []):
        raise ValidationError({field: f"Not a valid value for {attribute['label']}."})
    rule["value"] = text
    return rule


def validate_definition(raw) -> dict:
    """Normalise a submitted rule expression, or raise ValidationError."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except ValueError:
            raise ValidationError({"definition": "The rule definition is not valid JSON."}) from None
    if not isinstance(raw, dict):
        raise ValidationError({"definition": "The rule definition is malformed."})

    match = clean(raw.get("match"), 8).lower() or "all"
    if match not in MATCH_MODES:
        raise ValidationError({"definition": "Choose whether rules match ALL or ANY."})

    rules = raw.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ValidationError({"definition": "Add at least one rule."})
    if len(rules) > 30:
        raise ValidationError({"definition": "A segment can hold at most 30 rules."})

    return {"match": match, "rules": [_validate_rule(r, i) for i, r in enumerate(rules)]}


def describe_rule(rule: dict) -> str:
    attribute = ATTRIBUTES_BY_KEY.get(rule.get("attribute") or "", {})
    spec = SEGMENT_OPERATORS.get(rule.get("operator") or "", {})
    label = attribute.get("label", rule.get("attribute", "?"))
    comparison = spec.get("label", rule.get("operator", "?"))
    if spec.get("no_value"):
        return f"{label} {comparison}"
    value = rule.get("value")
    if isinstance(value, list):
        rendered = ", ".join(str(v) for v in value)
    elif isinstance(value, bool):
        rendered = "yes" if value else "no"
    else:
        rendered = str(value)
    return f"{label} {comparison} {rendered}"


def describe(definition: dict) -> list[str]:
    return [describe_rule(rule) for rule in (definition or {}).get("rules", [])]


def required_sources(definition: dict) -> list[dict]:
    """Which upstream systems this segment depends on, and whether they exist."""
    keys: list[str] = []
    for rule in (definition or {}).get("rules", []):
        attribute = ATTRIBUTES_BY_KEY.get(rule.get("attribute") or "")
        if attribute and attribute["source"] not in keys:
            keys.append(attribute["source"])
    network_ready = providers.get("network_footprint").available()
    subscriber_ready = providers.get("segment_size").available()
    out = []
    for key in keys:
        connected = network_ready if key == "network" else subscriber_ready
        out.append(
            {"key": key, "label": SOURCE_LABELS.get(key, key), "connected": bool(connected)}
        )
    return out


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _decorate(row: dict) -> dict:
    try:
        definition = json.loads(row.get("definition") or "{}")
    except ValueError:
        definition = {}
    row["definition"] = definition
    row["rule_count"] = len(definition.get("rules") or [])
    row["match_label"] = MATCH_MODES.get(definition.get("match") or "all", "")
    row["rule_text"] = describe(definition)
    row["refresh_label"] = REFRESH_MODES.get(row.get("refresh") or "manual", row.get("refresh"))
    row["sources"] = required_sources(definition)
    return row


def list_segments(*, include_archived: bool = False, query: str | None = None) -> list[dict]:
    sql = "SELECT * FROM segment"
    where, params = [], []
    if not include_archived:
        where.append("archived = 0")
    text = clean(query, 80)
    if text:
        where.append("(name LIKE ? OR description LIKE ?)")
        params += [f"%{text}%", f"%{text}%"]
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY archived, name COLLATE NOCASE"
    with cursor() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_decorate(row) for row in rows_to_dicts(rows)]


def get_segment(segment_id: int) -> dict | None:
    with cursor() as conn:
        row = conn.execute("SELECT * FROM segment WHERE id = ?", (segment_id,)).fetchone()
    return _decorate(dict(row)) if row else None


def _validate(form: dict, *, existing: dict | None = None) -> dict:
    name = clean(form.get("name"), 120)
    if len(name) < 3:
        raise ValidationError({"name": "Give the segment a name of at least 3 characters."})
    refresh = clean(form.get("refresh"), 24).lower() or "manual"
    if refresh not in REFRESH_MODES:
        raise ValidationError({"refresh": "Choose a refresh mode."})
    definition = validate_definition(form.get("definition"))

    with cursor() as conn:
        clash = conn.execute(
            "SELECT id FROM segment WHERE name = ? AND id != ?",
            (name, (existing or {}).get("id", 0)),
        ).fetchone()
    if clash:
        raise ValidationError({"name": "Another segment already uses this name."})

    return {
        "name": name,
        "description": clean_or_none(form.get("description"), 1000),
        "owner": clean_or_none(form.get("owner"), 120),
        "refresh": refresh,
        "definition": json.dumps(definition, ensure_ascii=False, sort_keys=True),
    }


def create_segment(form: dict, user) -> int:
    data = _validate(form)
    stamp = now_iso()
    with cursor() as conn:
        cur = conn.execute(
            "INSERT INTO segment (name, description, definition, refresh, owner, "
            "created_at, created_by, updated_at, updated_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data["name"], data["description"], data["definition"], data["refresh"],
                data["owner"], stamp, user.username, stamp, user.username,
            ),
        )
        segment_id = int(cur.lastrowid)
        audit.record(
            "segment.created",
            actor=user.username,
            actor_role=user.role,
            entity_type=ENTITY,
            entity_id=segment_id,
            summary=f"Created segment “{data['name']}”",
            conn=conn,
        )
    return segment_id


def update_segment(segment_id: int, form: dict, user) -> None:
    existing = get_segment(segment_id)
    if not existing:
        raise ValidationError({"_": "That segment no longer exists."})
    data = _validate(form, existing=existing)
    with cursor() as conn:
        conn.execute(
            "UPDATE segment SET name = ?, description = ?, definition = ?, refresh = ?, "
            "owner = ?, updated_at = ?, updated_by = ? WHERE id = ?",
            (
                data["name"], data["description"], data["definition"], data["refresh"],
                data["owner"], now_iso(), user.username, segment_id,
            ),
        )
        audit.record(
            "segment.updated",
            actor=user.username,
            actor_role=user.role,
            entity_type=ENTITY,
            entity_id=segment_id,
            summary=f"Updated segment “{data['name']}”",
            conn=conn,
        )


def set_archived(segment_id: int, archived: bool, user) -> None:
    existing = get_segment(segment_id)
    if not existing:
        raise ValidationError({"_": "That segment no longer exists."})
    if archived:
        with cursor() as conn:
            in_use = conn.execute(
                "SELECT COUNT(*) AS n FROM campaign WHERE segment_id = ? "
                "AND state NOT IN ('completed', 'cancelled')",
                (segment_id,),
            ).fetchone()
        if in_use and int(in_use["n"]) > 0:
            raise ValidationError(
                {"_": f"{in_use['n']} active campaign(s) still target this segment."}
            )
    with cursor() as conn:
        conn.execute(
            "UPDATE segment SET archived = ?, updated_at = ?, updated_by = ? WHERE id = ?",
            (1 if archived else 0, now_iso(), user.username, segment_id),
        )
        audit.record(
            "segment.archived" if archived else "segment.restored",
            actor=user.username,
            actor_role=user.role,
            entity_type=ENTITY,
            entity_id=segment_id,
            summary=f"{'Archived' if archived else 'Restored'} segment “{existing['name']}”",
            conn=conn,
        )


def estimate_size(definition: dict):
    """Ask the connected provider how many subscribers match."""
    return providers.get("segment_size").estimate(definition or {})
