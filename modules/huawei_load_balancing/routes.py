"""Huawei Load Balancing — placeholder module (implementation pending)."""

from __future__ import annotations

from flask import Blueprint, render_template

from core.radio.web import admin_required, format_user, get_current_user

huawei_load_balancing_bp = Blueprint(
    "huawei_load_balancing",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/huawei-load-balancing/static",
)


@huawei_load_balancing_bp.before_request
def _guard_huawei_load_balancing_access():
    from core.module_access import module_access_before_request
    return module_access_before_request("/huawei-load-balancing")


@huawei_load_balancing_bp.route("/huawei-load-balancing")
@admin_required
def huawei_load_balancing_page():
    return render_template(
        "huawei_load_balancing.html",
        user=format_user(get_current_user()),
    )
