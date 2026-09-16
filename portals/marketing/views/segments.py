"""Audience segment screens."""

from __future__ import annotations

import json

from flask import abort, flash, jsonify, redirect, request, url_for

from .. import audit, config
from ..access import current_user, login_required, require_permission
from ..repositories import ValidationError, segments
from .blueprint import flash_errors, marketing_bp, render


def _rules_from_form(form) -> dict:
    """Rebuild a definition from the rule-builder's repeating fields."""
    raw = (form.get("definition_json") or "").strip()
    if raw:
        try:
            return json.loads(raw)
        except ValueError:
            raise ValidationError({"definition": "The rule builder sent malformed data."}) from None

    attributes = form.getlist("rule_attribute")
    operators = form.getlist("rule_operator")
    values = form.getlist("rule_value")
    rules = []
    for index, attribute in enumerate(attributes):
        if not attribute:
            continue
        rules.append(
            {
                "attribute": attribute,
                "operator": operators[index] if index < len(operators) else "",
                "value": values[index] if index < len(values) else "",
            }
        )
    return {"match": form.get("match") or "all", "rules": rules}


@marketing_bp.route("/segments")
@require_permission(config.P_SEGMENT_VIEW)
def segment_list():
    query = (request.args.get("q") or "").strip()
    include_archived = request.args.get("archived") == "1"
    return render(
        "marketing/segment_list.html",
        active="segments",
        segments=segments.list_segments(include_archived=include_archived, query=query),
        filters={"q": query, "archived": include_archived},
    )


@marketing_bp.route("/segments/new", methods=["GET", "POST"])
@require_permission(config.P_SEGMENT_EDIT)
def segment_new():
    segment = {"definition": {"match": "all", "rules": []}}
    if request.method == "POST":
        form = request.form.to_dict()
        try:
            form["definition"] = _rules_from_form(request.form)
            segment_id = segments.create_segment(form, current_user())
            flash("Segment created.", "success")
            return redirect(url_for("marketing_portal.segment_detail", segment_id=segment_id))
        except ValidationError as exc:
            flash_errors(exc.errors)
            segment = {**form, "definition": form.get("definition") or {"match": "all", "rules": []}}
    return render(
        "marketing/segment_form.html",
        active="segments",
        segment=segment,
        mode="new",
        attributes=config.SEGMENT_ATTRIBUTES,
        operators=config.SEGMENT_OPERATORS,
        refresh_modes=segments.REFRESH_MODES,
        match_modes=segments.MATCH_MODES,
    )


@marketing_bp.route("/segments/<int:segment_id>")
@require_permission(config.P_SEGMENT_VIEW)
def segment_detail(segment_id: int):
    segment = segments.get_segment(segment_id)
    if not segment:
        abort(404)
    return render(
        "marketing/segment_detail.html",
        active="segments",
        segment=segment,
        estimate=segments.estimate_size(segment["definition"]),
        history=audit.recent(50, entity_type=segments.ENTITY, entity_id=segment_id),
    )


@marketing_bp.route("/segments/<int:segment_id>/edit", methods=["GET", "POST"])
@require_permission(config.P_SEGMENT_EDIT)
def segment_edit(segment_id: int):
    segment = segments.get_segment(segment_id)
    if not segment:
        abort(404)
    if request.method == "POST":
        form = request.form.to_dict()
        try:
            form["definition"] = _rules_from_form(request.form)
            segments.update_segment(segment_id, form, current_user())
            flash("Segment updated.", "success")
            return redirect(url_for("marketing_portal.segment_detail", segment_id=segment_id))
        except ValidationError as exc:
            flash_errors(exc.errors)
            segment = {**segment, **form, "definition": form.get("definition") or segment["definition"]}
    return render(
        "marketing/segment_form.html",
        active="segments",
        segment=segment,
        mode="edit",
        attributes=config.SEGMENT_ATTRIBUTES,
        operators=config.SEGMENT_OPERATORS,
        refresh_modes=segments.REFRESH_MODES,
        match_modes=segments.MATCH_MODES,
    )


@marketing_bp.route("/segments/<int:segment_id>/archive", methods=["POST"])
@require_permission(config.P_SEGMENT_EDIT)
def segment_archive(segment_id: int):
    archived = request.form.get("archived") == "1"
    try:
        segments.set_archived(segment_id, archived, current_user())
        flash("Segment archived." if archived else "Segment restored.", "success")
    except ValidationError as exc:
        flash_errors(exc.errors)
    return redirect(url_for("marketing_portal.segment_detail", segment_id=segment_id))


@marketing_bp.route("/api/segments/estimate", methods=["POST"])
@login_required
def segment_estimate():
    """Live size estimate for the rule builder."""
    payload = request.get_json(silent=True) or {}
    try:
        definition = segments.validate_definition(payload.get("definition"))
    except ValidationError as exc:
        return jsonify({"ok": False, "errors": exc.errors}), 400
    result = segments.estimate_size(definition)
    return jsonify(
        {
            "ok": True,
            "available": result.available,
            "value": result.value,
            "reason": result.reason,
            "rules": segments.describe(definition),
            "sources": segments.required_sources(definition),
        }
    )
