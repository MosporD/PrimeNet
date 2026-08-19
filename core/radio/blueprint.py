"""Shared radio-insight blueprint factory (radio_module.html + issues API)."""

from __future__ import annotations

import inspect
from collections.abc import Callable

from flask import Blueprint, jsonify, render_template

from .scoring import filter_rows, summarize
from .web import admin_required, attach_feature_guard, format_user, get_current_user, json_error, query_filters

InsightBuilder = Callable[..., dict]


def make_radio_module(
    *,
    name: str,
    href: str,
    title: str,
    subtitle: str,
    kind: str,
    api_url: str,
    builder: InsightBuilder,
    default_technology: str = "all",
    default_limit: int = 200,
) -> Blueprint:
    bp = Blueprint(name, __name__)
    attach_feature_guard(bp, href)

    # Not every detector has an area dimension: group/controller PM rows are
    # BSC/RNC aggregates that span areas. Pass (and filter on) area only when
    # the builder models it, so those modules neither crash nor return nothing.
    builder_params = inspect.signature(builder).parameters
    supports_area = "area" in builder_params

    @bp.route(href)
    @admin_required
    def page():
        return render_template(
            "radio_module.html",
            user=format_user(get_current_user()),
            module_title=title,
            module_subtitle=subtitle,
            module_kind=kind,
            api_url=api_url,
            default_technology=default_technology,
        )

    @bp.route(api_url)
    @admin_required
    def issues():
        f = query_filters(default_limit=default_limit)
        try:
            kwargs = {
                "vendor": f["vendor"],
                "technology": f["technology"],
                "limit": f["limit"],
            }
            if supports_area:
                kwargs["area"] = f["area"]
            payload = builder(**kwargs)
            rows = filter_rows(
                payload.get("issues") or [],
                area=f["area"] if supports_area else "",
                vendor=f["vendor"],
                technology=f["technology"],
                severity=f["severity"],
                search=f["search"],
            )
            return jsonify({"success": True, **payload, "summary": summarize(rows), "issues": rows})
        except Exception as exc:
            return json_error(exc)

    page.__name__ = f"{name}_page"
    issues.__name__ = f"{name}_issues"
    return bp
