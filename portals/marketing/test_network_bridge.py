"""Tests for PrimeNet portal API + NexPulse network footprint bridge."""

from __future__ import annotations

import json
import os
import tempfile
from unittest import mock

import pytest


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch):
    path = os.path.join(tempfile.mkdtemp(), "marketing.db")
    monkeypatch.setenv("NEXUS_MARKETING_DB", path)
    from portals.marketing import db

    monkeypatch.setattr(db, "_initialised_for", None, raising=False)
    yield path


@pytest.fixture
def user():
    from portals.marketing import config

    class _User:
        username = "tester"
        role = config.ROLE_ADMIN
        permissions = config.permissions_for_role(config.ROLE_ADMIN)

        def can(self, permission):
            return permission in self.permissions

    return _User()


@pytest.fixture
def portal_token(monkeypatch):
    monkeypatch.setenv("NEXUS_PORTAL_API_TOKEN", "test-portal-token")
    monkeypatch.setenv("NCM_SKIP_ACTIVATION", "1")


def test_portal_api_rejects_missing_bearer(portal_token):
    from flask import Flask
    from modules.portal_api import portal_api_bp

    app = Flask(__name__)
    app.register_blueprint(portal_api_bp)
    client = app.test_client()
    r = client.get("/api/portal/health")
    assert r.status_code == 401


def test_portal_api_health_ok(portal_token):
    from flask import Flask
    from modules.portal_api import portal_api_bp

    app = Flask(__name__)
    app.register_blueprint(portal_api_bp)
    client = app.test_client()
    r = client.get(
        "/api/portal/health",
        headers={"Authorization": "Bearer test-portal-token"},
    )
    assert r.status_code == 200
    assert r.get_json()["ok"] is True


def test_portal_api_technologies_payload(portal_token, monkeypatch):
    from flask import Flask
    from modules.portal_api import portal_api_bp
    from modules.portal_api import network as net

    monkeypatch.setattr(
        net,
        "technology_footprint",
        lambda area=None: {
            "as_of": "2026-09-16T00:00:00+00:00",
            "area": area or "all",
            "technologies": [{"technology": "4G-FDD", "cell_count": 10, "site_count": 3}],
            "totals": {"cells": 10, "sites": 3},
            "source": "test",
        },
    )
    app = Flask(__name__)
    app.register_blueprint(portal_api_bp)
    client = app.test_client()
    r = client.get(
        "/api/portal/network-footprint/technologies",
        headers={"Authorization": "Bearer test-portal-token"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["success"] is True
    assert body["totals"]["cells"] == 10


def test_primenet_provider_parses_http(monkeypatch):
    from portals.marketing.providers_primenet import PrimeNetNetworkFootprint

    payload = {
        "success": True,
        "as_of": "2026-09-16T00:00:00+00:00",
        "site_count": 2,
        "sites": [{"site_id": "A"}, {"site_id": "B"}],
    }

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setenv("NEXUS_PRIMENET_API_URL", "http://primenet.test")
    monkeypatch.setenv("NEXUS_PORTAL_API_TOKEN", "tok")
    with mock.patch("urllib.request.urlopen", return_value=_Resp()):
        provider = PrimeNetNetworkFootprint()
        assert provider.available() is True
        result = provider.congested_sites()
    assert result.available is True
    assert result.value["site_count"] == 2


def test_campaign_blocks_when_network_rules_without_api(user):
    from portals.marketing import providers
    from portals.marketing.repositories import campaigns, catalog, consent, segments

    providers.register("network_footprint", providers._NullNetworkFootprint())

    offer_id = catalog.create_offer(
        {
            "code": "NET-1",
            "name": "Network offer",
            "family": "ftth",
            "price_amount": "10",
        },
        user,
    )
    for state in ("in_review", "approved", "live"):
        catalog.transition_offer(offer_id, state, user)

    seg_id = segments.create_segment(
        {
            "name": "Congested avoiders",
            "definition": {
                "match": "all",
                "rules": [
                    {"attribute": "site_congested", "operator": "eq", "value": False},
                ],
            },
        },
        user,
    )
    campaign_id = campaigns.create_campaign(
        {
            "code": "C-NET",
            "name": "Network gated",
            "objective": "upsell",
            "segment_id": str(seg_id),
            "holdout_pct": "10",
            "starts_on": "2026-10-01",
            "ends_on": "2026-12-31",
        },
        user,
    )
    campaigns.set_channels(
        campaign_id,
        [{"channel": "sms", "template_ref": "t1"}],
        user,
    )
    campaigns.set_offers(campaign_id, [offer_id], user)
    consent.create_policy(
        {
            "name": "SMS cap",
            "channel": "sms",
            "max_contacts": "4",
            "window_days": "30",
            "active": "1",
        },
        user,
    )

    status = campaigns.readiness(campaigns.get_campaign(campaign_id))
    network_checks = [c for c in status["checks"] if c["key"] == "network_api"]
    assert network_checks, status["checks"]
    assert network_checks[0]["blocking"] is True
    assert network_checks[0]["ok"] is False
    assert status["ready"] is False
