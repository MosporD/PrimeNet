"""Offer & product catalog screens."""

from __future__ import annotations

from flask import abort, flash, redirect, request, url_for

from .. import audit, config
from ..access import current_user, require_permission
from ..repositories import ValidationError, catalog
from .blueprint import flash_errors, marketing_bp, render


@marketing_bp.route("/catalog")
@require_permission(config.P_CATALOG_VIEW)
def offer_list():
    state = (request.args.get("state") or "").strip() or None
    family = (request.args.get("family") or "").strip() or None
    query = (request.args.get("q") or "").strip()
    return render(
        "marketing/offer_list.html",
        active="catalog",
        offers=catalog.list_offers(state=state, family=family, query=query),
        counts=catalog.counts_by_state(),
        filters={"state": state or "", "family": family or "", "q": query},
    )


@marketing_bp.route("/catalog/new", methods=["GET", "POST"])
@require_permission(config.P_CATALOG_EDIT)
def offer_new():
    form = request.form.to_dict() if request.method == "POST" else {}
    if request.method == "POST":
        try:
            offer_id = catalog.create_offer(form, current_user())
            flash("Offer created.", "success")
            return redirect(url_for("marketing_portal.offer_detail", offer_id=offer_id))
        except ValidationError as exc:
            flash_errors(exc.errors)
    return render("marketing/offer_form.html", active="catalog", offer=form, mode="new")


@marketing_bp.route("/catalog/<int:offer_id>")
@require_permission(config.P_CATALOG_VIEW)
def offer_detail(offer_id: int):
    offer = catalog.get_offer(offer_id)
    if not offer:
        abort(404)
    user = current_user()
    return render(
        "marketing/offer_detail.html",
        active="catalog",
        offer=offer,
        transitions=catalog.available_transitions(offer, user),
        history=audit.recent(50, entity_type=catalog.ENTITY, entity_id=offer_id),
    )


@marketing_bp.route("/catalog/<int:offer_id>/edit", methods=["GET", "POST"])
@require_permission(config.P_CATALOG_EDIT)
def offer_edit(offer_id: int):
    offer = catalog.get_offer(offer_id)
    if not offer:
        abort(404)
    if request.method == "POST":
        form = request.form.to_dict()
        try:
            catalog.update_offer(offer_id, form, current_user())
            flash("Offer updated.", "success")
            return redirect(url_for("marketing_portal.offer_detail", offer_id=offer_id))
        except ValidationError as exc:
            flash_errors(exc.errors)
            offer = {**offer, **form}
    return render("marketing/offer_form.html", active="catalog", offer=offer, mode="edit")


@marketing_bp.route("/catalog/<int:offer_id>/transition", methods=["POST"])
@require_permission(config.P_CATALOG_EDIT)
def offer_transition(offer_id: int):
    try:
        catalog.transition_offer(
            offer_id,
            (request.form.get("to_state") or "").strip(),
            current_user(),
            request.form.get("note") or "",
        )
        flash("Offer status updated.", "success")
    except ValidationError as exc:
        flash_errors(exc.errors)
    return redirect(url_for("marketing_portal.offer_detail", offer_id=offer_id))
