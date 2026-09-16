"""The portal blueprint and view helpers shared by every screen."""

from __future__ import annotations

from flask import Blueprint, flash, render_template

from .. import config
from ..access import current_user

marketing_bp = Blueprint(
    "marketing_portal",
    __name__,
    url_prefix=config.URL_PREFIX,
    template_folder="../templates",
    static_folder="../static",
    static_url_path="/static",
)

NAV = [
    {"key": "overview", "label": "Overview", "endpoint": "marketing_portal.overview",
     "permission": None, "icon": "grid"},
    {"key": "campaigns", "label": "Campaigns", "endpoint": "marketing_portal.campaign_list",
     "permission": config.P_CAMPAIGN_VIEW, "icon": "megaphone"},
    {"key": "calendar", "label": "Calendar", "endpoint": "marketing_portal.campaign_calendar",
     "permission": config.P_CAMPAIGN_VIEW, "icon": "calendar"},
    {"key": "catalog", "label": "Offer catalog", "endpoint": "marketing_portal.offer_list",
     "permission": config.P_CATALOG_VIEW, "icon": "tag"},
    {"key": "segments", "label": "Audiences", "endpoint": "marketing_portal.segment_list",
     "permission": config.P_SEGMENT_VIEW, "icon": "users"},
    {"key": "consent", "label": "Consent & policy", "endpoint": "marketing_portal.consent_home",
     "permission": config.P_CONSENT_VIEW, "icon": "shield"},
    {"key": "audit", "label": "Audit trail", "endpoint": "marketing_portal.audit_trail",
     "permission": config.P_AUDIT_VIEW, "icon": "list"},
]


def nav_for(user) -> list[dict]:
    return [
        item for item in NAV
        if item["permission"] is None or (user and user.can(item["permission"]))
    ]


def render(template: str, *, active: str, **context):
    """Render a portal page with the shell context every template expects."""
    user = current_user()
    return render_template(
        template,
        user=user,
        nav=nav_for(user),
        active_nav=active,
        portal_name=config.PORTAL_NAME,
        portal_domain=config.PORTAL_DOMAIN,
        cfg=config,
        **context,
    )


def flash_errors(errors: dict[str, str]) -> None:
    for field, message in errors.items():
        flash(message if field == "_" else f"{field.replace('_', ' ').title()}: {message}", "error")
