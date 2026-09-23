"""NexPulse — the NexusCore Marketing Portal.

A self-contained portal application. It owns its own SQLite domain store,
templates, static assets, and (via the NexPulse process) a separate users DB
and session cookie. It imports nothing from ``modules/`` (PrimeNet).

Run standalone::

    python nexpulse_app.py
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
