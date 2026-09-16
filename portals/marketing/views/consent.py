"""Consent, suppression, contact policy, and the contactability lookup."""

from __future__ import annotations

from flask import abort, flash, redirect, request, url_for

from .. import config
from ..access import current_user, require_permission
from ..repositories import ValidationError, consent
from .blueprint import flash_errors, marketing_bp, render


def _shell(**extra):
    return {
        "normalisation_active": config.msisdn_normalisation_active(),
        "country_code": config.msisdn_country_code(),
        **extra,
    }


@marketing_bp.route("/consent")
@require_permission(config.P_CONSENT_VIEW)
def consent_home():
    status = (request.args.get("status") or "").strip() or None
    channel = (request.args.get("channel") or "").strip() or None
    query = (request.args.get("q") or "").strip()
    return render(
        "marketing/consent_list.html",
        active="consent",
        records=consent.list_consent(status=status, channel=channel, query=query),
        summary=consent.consent_summary(),
        filters={"status": status or "", "channel": channel or "", "q": query},
        **_shell(),
    )


@marketing_bp.route("/consent/record", methods=["POST"])
@require_permission(config.P_CONSENT_EDIT)
def consent_record():
    try:
        consent.record_consent(request.form.to_dict(), current_user())
        flash("Consent recorded.", "success")
    except ValidationError as exc:
        flash_errors(exc.errors)
    return redirect(url_for("marketing_portal.consent_home"))


@marketing_bp.route("/consent/suppression")
@require_permission(config.P_CONSENT_VIEW)
def suppression_list():
    query = (request.args.get("q") or "").strip()
    active_only = request.args.get("all") != "1"
    return render(
        "marketing/suppression_list.html",
        active="consent",
        entries=consent.list_suppression(active_only=active_only, query=query),
        filters={"q": query, "active_only": active_only},
        **_shell(),
    )


@marketing_bp.route("/consent/suppression/add", methods=["POST"])
@require_permission(config.P_CONSENT_EDIT)
def suppression_add():
    try:
        consent.add_suppression(request.form.to_dict(), current_user())
        flash("Suppression entry added.", "success")
    except ValidationError as exc:
        flash_errors(exc.errors)
    return redirect(url_for("marketing_portal.suppression_list"))


@marketing_bp.route("/consent/suppression/<int:entry_id>/release", methods=["POST"])
@require_permission(config.P_CONSENT_EDIT)
def suppression_release(entry_id: int):
    try:
        consent.release_suppression(entry_id, current_user(), request.form.get("note") or "")
        flash("Suppression released.", "success")
    except ValidationError as exc:
        flash_errors(exc.errors)
    return redirect(url_for("marketing_portal.suppression_list"))


@marketing_bp.route("/consent/policies")
@require_permission(config.P_CONSENT_VIEW)
def policy_list():
    return render(
        "marketing/policy_list.html",
        active="consent",
        policies=consent.list_policies(),
        scopes=consent.POLICY_SCOPES,
        **_shell(),
    )


@marketing_bp.route("/consent/policies/new", methods=["GET", "POST"])
@require_permission(config.P_POLICY_EDIT)
def policy_new():
    policy = request.form.to_dict() if request.method == "POST" else {"active": "1", "window_days": "30"}
    if request.method == "POST":
        try:
            consent.create_policy(policy, current_user())
            flash("Contact policy created.", "success")
            return redirect(url_for("marketing_portal.policy_list"))
        except ValidationError as exc:
            flash_errors(exc.errors)
    return render(
        "marketing/policy_form.html",
        active="consent",
        policy=policy,
        mode="new",
        scopes=consent.POLICY_SCOPES,
        **_shell(),
    )


@marketing_bp.route("/consent/policies/<int:policy_id>/edit", methods=["GET", "POST"])
@require_permission(config.P_POLICY_EDIT)
def policy_edit(policy_id: int):
    policy = consent.get_policy(policy_id)
    if not policy:
        abort(404)
    if request.method == "POST":
        form = request.form.to_dict()
        try:
            consent.update_policy(policy_id, form, current_user())
            flash("Contact policy updated.", "success")
            return redirect(url_for("marketing_portal.policy_list"))
        except ValidationError as exc:
            flash_errors(exc.errors)
            policy = {**policy, **form}
    return render(
        "marketing/policy_form.html",
        active="consent",
        policy=policy,
        mode="edit",
        scopes=consent.POLICY_SCOPES,
        **_shell(),
    )


@marketing_bp.route("/consent/lookup")
@require_permission(config.P_CONSENT_VIEW)
def contactability_lookup():
    identifier = (request.args.get("identifier") or "").strip()
    identifier_type = (request.args.get("identifier_type") or "msisdn").strip()
    result, error = None, None
    if identifier:
        try:
            result = consent.contactability(identifier_type, identifier)
        except ValidationError as exc:
            error = "; ".join(exc.errors.values())
    return render(
        "marketing/contactability.html",
        active="consent",
        result=result,
        error=error,
        identifier=identifier,
        identifier_type=identifier_type,
        **_shell(),
    )
