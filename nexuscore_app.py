"""NexusCore — umbrella lobby (portal tower).

Central identity uses the PrimeNet users database (``ncm_users.db``). One shared
``nexus_session`` cookie (optional ``NEXUS_COOKIE_DOMAIN``) is honored by every
portal. Tower cards are filtered by each user's portal allow-list.
"""

from __future__ import annotations

import os

from flask import Blueprint, abort, redirect, render_template, url_for

from core.platform.base_app import create_base_app, run_dev_server
from core.platform.identity import create_identity_blueprint
from core.platform.paths import nexpulse_public_url, primenet_public_url
from core.platform.portal_access import (
    PORTAL_NEXPULSE,
    PORTAL_PRIMENET,
    PORTAL_SALES,
    PORTAL_SUPPORT,
    user_allowed_portals,
    user_can_access_portal,
)
from core.platform.session import DEFAULT_SHARED_COOKIE
from core.platform.shared_activation import install_shared_activation

SESSION_COOKIE = (
    os.getenv("NEXUS_SESSION_COOKIE")
    or os.getenv("NEXUSCORE_SESSION_COOKIE")
    or DEFAULT_SHARED_COOKIE
).strip() or DEFAULT_SHARED_COOKIE


def create_app():
    from database_enhanced import init_db

    app = create_base_app(
        "nexuscore",
        session_cookie_name=SESSION_COOKIE,
        secret_key_env="FLASK_SECRET_KEY_NEXUSCORE",
    )
    app.config["SESSION_COOKIE_DOMAIN"] = (os.getenv("NEXUS_COOKIE_DOMAIN") or "").strip() or None
    install_shared_activation(app, service_name="nexuscore")
    init_db()

    auth_bp = create_identity_blueprint(
        platform_id="nexuscore",
        post_login_endpoint="nexuscore.portal_select",
        brand_title="NexusCore",
        central=True,
    )
    app.register_blueprint(auth_bp)

    lobby = Blueprint("nexuscore", __name__)

    def _user_payload(user: dict) -> dict:
        return {
            "id": user.get("id"),
            "username": user.get("username"),
            "email": user.get("email"),
            "role": user.get("role"),
            "allowed_portals": user_allowed_portals(user),
        }

    @lobby.route("/portals")
    def portal_select():
        user = auth_bp.current_user()
        if not user:
            return redirect(url_for("auth.login_page"))
        allowed = set(user_allowed_portals(user))
        return render_template(
            "portal_select.html",
            user=_user_payload(user),
            primenet_url=primenet_public_url(),
            nexpulse_url=nexpulse_public_url(),
            can_engineering=PORTAL_PRIMENET in allowed,
            can_marketing=PORTAL_NEXPULSE in allowed,
            can_sales=PORTAL_SALES in allowed,
            can_support=PORTAL_SUPPORT in allowed,
        )

    @lobby.route("/portals/<portal_id>")
    def portal_enter(portal_id):
        user = auth_bp.current_user()
        if not user:
            return redirect(url_for("auth.login_page"))
        key = (portal_id or "").strip().lower()
        if key in ("engineering", "primenet"):
            if not user_can_access_portal(user, PORTAL_PRIMENET):
                abort(403)
            return redirect(f"{primenet_public_url()}/dashboard")
        if key in ("marketing", "nexpulse"):
            if not user_can_access_portal(user, PORTAL_NEXPULSE):
                abort(403)
            return redirect(f"{nexpulse_public_url()}/portals/marketing/")
        coming = {
            "sales": {
                "id": "sales",
                "name": "NexArpu",
                "domain": "Sales",
                "blurb": "Pipeline, accounts, product ordering, and commercial workflows.",
            },
            "support": {
                "id": "support",
                "name": "NexResolve",
                "domain": "Customer Support",
                "blurb": "Tickets, SLA tracking, customer care, and service assurance.",
            },
        }.get(key)
        if not coming:
            return redirect(url_for("nexuscore.portal_select"))
        if not user_can_access_portal(user, key):
            abort(403)
        return render_template(
            "portal_coming_soon.html",
            user=_user_payload(user),
            portal=coming,
        )

    app.register_blueprint(lobby)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", os.getenv("NEXUSCORE_PORT", "8000")))
    os.environ.setdefault("FLASK_PORT", str(port))
    run_dev_server(
        app,
        title="NexusCore — Platform Lobby",
        default_port=port,
        open_path="/portals",
    )
