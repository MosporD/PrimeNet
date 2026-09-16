"""NexPulse — the NexusCore Marketing Portal.

A self-contained portal application. It owns its own SQLite store, templates,
static assets, and access rules, and imports nothing from ``modules/`` (the
Engineering Portal, PrimeNet). The only shared dependency is identity, which
NexusCore architecture rule 2 puts in one place — see ``access.py``.

Today the portal is mounted into the PrimeNet process for convenience::

    from portals.marketing import create_marketing_portal
    create_marketing_portal(app)

Splitting it into its own service means calling the same function against a
standalone Flask app instead — no view, template, or repository changes.
"""

from __future__ import annotations

from .config import PORTAL_BLURB, PORTAL_DOMAIN, PORTAL_ID, PORTAL_NAME, URL_PREFIX

__all__ = [
    "create_marketing_portal",
    "PORTAL_ID",
    "PORTAL_NAME",
    "PORTAL_DOMAIN",
    "PORTAL_BLURB",
    "URL_PREFIX",
]


def create_marketing_portal(app, *, init_db: bool = True):
    """Attach the portal to a Flask app and return the blueprint."""
    from .db import init_schema
    from .views import marketing_bp

    if init_db:
        init_schema()
    if "marketing_portal" not in app.blueprints:
        app.register_blueprint(marketing_bp)
    return marketing_bp
