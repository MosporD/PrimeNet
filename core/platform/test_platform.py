"""Smoke tests for shared SSO cookie + central PrimeNet users DB."""

from __future__ import annotations

import os
import tempfile

import pytest


@pytest.fixture
def central_users(monkeypatch):
    root = tempfile.mkdtemp()
    users_db = os.path.join(root, "ncm_users.db")
    monkeypatch.setenv("NCM_SKIP_ACTIVATION", "1")
    monkeypatch.setenv("NEXUS_SESSION_COOKIE", "nexus_session")
    monkeypatch.setenv("NEXUS_MARKETING_DB", os.path.join(root, "marketing.db"))
    monkeypatch.delenv("NEXUS_COOKIE_DOMAIN", raising=False)
    monkeypatch.delenv("NCM_ALLOW_LOCAL_LOGIN", raising=False)

    import sync_config
    import db.runtime as runtime

    monkeypatch.setattr(sync_config, "NCMUSERS_DB", users_db)
    monkeypatch.setattr(runtime, "NCMUSERS_DB", users_db)

    from database_enhanced import create_user, init_db

    init_db()
    ok, uid = create_user(
        username="sso_admin",
        email="sso@local",
        password="sso-secret",
        role="admin",
        allowed_portals=["primenet", "nexpulse"],
    )
    assert ok, uid
    ok2, uid2 = create_user(
        username="eng_only",
        email="eng@local",
        password="eng-secret",
        role="user",
        allowed_portals=["primenet"],
    )
    assert ok2, uid2
    return {"root": root, "users_db": users_db}


def test_shared_cookie_name(central_users):
    from nexuscore_app import create_app as create_nxc
    from nexpulse_app import create_app as create_np

    nxc = create_nxc()
    np = create_np()
    assert nxc.config["SESSION_COOKIE_NAME"] == "nexus_session"
    assert np.config["SESSION_COOKIE_NAME"] == "nexus_session"
    assert "marketing_portal" not in nxc.blueprints
    assert "marketing_portal" in np.blueprints


def test_nexuscore_login_sets_shared_cookie(central_users):
    from nexuscore_app import create_app as create_nxc

    app = create_nxc()
    client = app.test_client()
    r = client.post("/api/login", json={"username": "sso_admin", "password": "sso-secret"})
    assert r.status_code == 200, r.get_json()
    assert "nexus_session=" in r.headers.get("Set-Cookie", "")


def test_portal_allowlist_gates_nexpulse(central_users):
    from nexuscore_app import create_app as create_nxc
    from nexpulse_app import create_app as create_np

    nxc = create_nxc()
    np = create_np()
    c = nxc.test_client()
    r = c.post("/api/login", json={"username": "eng_only", "password": "eng-secret"})
    assert r.status_code == 200, r.get_json()

    tower = c.get("/portals")
    assert tower.status_code == 200
    assert b"No access" in tower.data
    assert b"Engineering Portal" in tower.data

    # Reuse session token against NexPulse.
    set_cookie = r.headers.get("Set-Cookie", "")
    token = None
    for part in set_cookie.split(","):
        for segment in part.split(";"):
            segment = segment.strip()
            if segment.startswith("nexus_session="):
                token = segment.split("=", 1)[1]
                break
        if token:
            break
    assert token

    np_client = np.test_client()
    np_client.set_cookie("nexus_session", token)
    denied = np_client.get("/portals/marketing/")
    # Unauthenticated / no portal → redirect to NexusCore login or 401/403.
    assert denied.status_code in (302, 401, 403)


def test_portal_access_helpers():
    from core.platform.portal_access import (
        parse_allowed_portals,
        user_can_access_portal,
    )

    assert parse_allowed_portals(None, role="user") == ["primenet"]
    assert "nexpulse" in parse_allowed_portals(None, role="admin")
    assert user_can_access_portal(
        {"role": "user", "allowed_portals": "primenet,nexpulse"},
        "marketing",
    )
    assert not user_can_access_portal(
        {"role": "user", "allowed_portals": "primenet"},
        "nexpulse",
    )
