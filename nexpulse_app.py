"""NexPulse — Marketing Portal process.

Uses the shared NexusCore / PrimeNet users database and ``nexus_session`` cookie.
Unauthenticated visitors are sent to the NexusCore login page.
"""

from __future__ import annotations

import os

from flask import redirect, request

from core.platform.base_app import create_base_app, run_dev_server
from core.platform.identity import create_identity_blueprint
from core.platform.portal_access import PORTAL_NEXPULSE
from core.platform.session import DEFAULT_SHARED_COOKIE
from core.platform.shared_activation import install_shared_activation
from portals.marketing import create_marketing_portal

SESSION_COOKIE = (
    os.getenv("NEXUS_SESSION_COOKIE")
    or os.getenv("NEXPULSE_SESSION_COOKIE")
    or DEFAULT_SHARED_COOKIE
).strip() or DEFAULT_SHARED_COOKIE


def create_app():
    from database_enhanced import init_db

    app = create_base_app(
        "nexpulse",
        session_cookie_name=SESSION_COOKIE,
        secret_key_env="FLASK_SECRET_KEY_NEXPULSE",
    )
    app.config["SESSION_COOKIE_DOMAIN"] = (os.getenv("NEXUS_COOKIE_DOMAIN") or "").strip() or None
    install_shared_activation(app, service_name="nexpulse")
    init_db()

    auth_bp = create_identity_blueprint(
        platform_id="nexpulse",
        post_login_endpoint="marketing_portal.overview",
        brand_title="NexPulse",
        central=True,
        require_portal=PORTAL_NEXPULSE,
        sso_redirect_login=True,
    )
    app.register_blueprint(auth_bp)
    create_marketing_portal(app)

    from portals.marketing.providers_primenet import try_register_primenet_network_provider

    if try_register_primenet_network_provider():
        print("[OK] NexPulse network footprint → PrimeNet API")
    else:
        print(
            "[INFO] NexPulse network footprint not connected "
            "(set NEXUS_PRIMENET_API_URL + NEXUS_PORTAL_API_TOKEN)"
        )

    @app.route("/")
    def root():
        return redirect("/portals/marketing/")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", os.getenv("NEXPULSE_PORT", "8002")))
    os.environ.setdefault("FLASK_PORT", str(port))
    run_dev_server(
        app,
        title="NexPulse — Marketing Portal",
        default_port=port,
        open_path="/portals/marketing/",
    )
