"""Domain rules for the NexPulse Marketing Portal.

Run: python -m pytest portals/marketing/test_marketing.py
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch):
    """Each test gets its own portal database."""
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


def _live_offer(user):
    from portals.marketing.repositories import catalog

    offer_id = catalog.create_offer(
        {"code": "FTTH-500", "name": "Fibre 500", "family": "ftth",
         "price_amount": "29.9", "price_currency": "JOD", "price_period": "month"},
        user,
    )
    for state in ("in_review", "approved", "live"):
        catalog.transition_offer(offer_id, state, user)
    return offer_id


# --------------------------------------------------------------- catalog

def test_offer_needs_a_price_before_review(user):
    from portals.marketing.repositories import ValidationError, catalog

    offer_id = catalog.create_offer({"code": "X1", "name": "No price", "family": "ftth"}, user)
    with pytest.raises(ValidationError):
        catalog.transition_offer(offer_id, "in_review", user)


def test_live_offer_cannot_be_edited(user):
    from portals.marketing.repositories import ValidationError, catalog

    offer_id = _live_offer(user)
    with pytest.raises(ValidationError):
        catalog.update_offer(offer_id, {"code": "FTTH-500", "name": "Renamed", "family": "ftth"}, user)


def test_offer_transitions_follow_the_state_machine(user):
    from portals.marketing.repositories import ValidationError, catalog

    offer_id = catalog.create_offer(
        {"code": "X2", "name": "Draft offer", "family": "ftth", "price_amount": "10"}, user
    )
    with pytest.raises(ValidationError):
        catalog.transition_offer(offer_id, "live", user)  # cannot skip review


def test_promotional_price_must_undercut_and_expire(user):
    from portals.marketing.repositories import ValidationError, catalog

    base = {"code": "X3", "name": "Promo", "family": "ftth", "price_amount": "20"}
    with pytest.raises(ValidationError):
        catalog.create_offer({**base, "promo_amount": "25", "promo_ends_on": "2027-01-01"}, user)
    with pytest.raises(ValidationError):
        catalog.create_offer({**base, "promo_amount": "15"}, user)  # no end date


# -------------------------------------------------------------- segments

def test_segment_rejects_operator_the_attribute_cannot_use(user):
    from portals.marketing.repositories import ValidationError, segments

    with pytest.raises(ValidationError):
        segments.create_segment(
            {"name": "Bad rule", "definition": {"match": "all", "rules": [
                {"attribute": "arpu_band", "operator": "gt", "value": "5"}]}},
            user,
        )


def test_segment_reports_the_sources_it_depends_on(user):
    from portals.marketing.repositories import segments

    segment_id = segments.create_segment(
        {"name": "FTTH upsell", "definition": {"match": "all", "rules": [
            {"attribute": "data_usage_gb", "operator": "gte", "value": "200"},
            {"attribute": "ftth_serviceable", "operator": "eq", "value": "true"}]}},
        user,
    )
    segment = segments.get_segment(segment_id)
    keys = {source["key"] for source in segment["sources"]}
    assert keys == {"usage", "network"}
    assert all(source["connected"] is False for source in segment["sources"])


def test_segment_size_is_unavailable_without_a_source(user):
    from portals.marketing.repositories import segments

    result = segments.estimate_size({"match": "all", "rules": []})
    assert result.available is False
    assert result.value is None


def test_segment_in_use_cannot_be_archived(user):
    from portals.marketing.repositories import ValidationError, campaigns, segments

    segment_id = segments.create_segment(
        {"name": "In use", "definition": {"match": "all", "rules": [
            {"attribute": "churn_risk", "operator": "eq", "value": "high"}]}},
        user,
    )
    campaigns.create_campaign(
        {"code": "C1", "name": "Retention", "objective": "retention", "segment_id": str(segment_id)},
        user,
    )
    with pytest.raises(ValidationError):
        segments.set_archived(segment_id, True, user)


# ------------------------------------------------------------- campaigns

def _ready_campaign(user):
    from portals.marketing.repositories import campaigns, consent, segments

    offer_id = _live_offer(user)
    segment_id = segments.create_segment(
        {"name": "Targets", "definition": {"match": "all", "rules": [
            {"attribute": "churn_risk", "operator": "eq", "value": "high"}]}},
        user,
    )
    campaign_id = campaigns.create_campaign(
        {"code": "Q4", "name": "Q4 push", "objective": "upsell", "segment_id": str(segment_id),
         "holdout_pct": "10", "starts_on": "2026-10-01", "ends_on": "2026-12-31"},
        user,
    )
    campaigns.set_channels(campaign_id, [{"channel": "sms", "template_ref": "TPL-1"}], user)
    campaigns.set_offers(campaign_id, [offer_id], user)
    consent.create_policy(
        {"name": "SMS cap", "channel": "sms", "max_contacts": "4", "window_days": "30", "active": "1"},
        user,
    )
    return campaign_id


def test_campaign_cannot_be_submitted_until_ready(user):
    from portals.marketing.repositories import ValidationError, campaigns

    campaign_id = campaigns.create_campaign(
        {"code": "BARE", "name": "Bare campaign", "objective": "upsell"}, user
    )
    with pytest.raises(ValidationError):
        campaigns.transition_campaign(campaign_id, "in_review", user)


def test_missing_contact_policy_blocks_approval(user):
    from portals.marketing.repositories import ValidationError, campaigns, segments

    offer_id = _live_offer(user)
    segment_id = segments.create_segment(
        {"name": "Targets", "definition": {"match": "all", "rules": [
            {"attribute": "churn_risk", "operator": "eq", "value": "high"}]}},
        user,
    )
    campaign_id = campaigns.create_campaign(
        {"code": "NOPOL", "name": "No policy", "objective": "upsell", "segment_id": str(segment_id),
         "starts_on": "2026-10-01", "ends_on": "2026-12-31"},
        user,
    )
    campaigns.set_channels(campaign_id, [{"channel": "sms", "template_ref": "T"}], user)
    campaigns.set_offers(campaign_id, [offer_id], user)

    status = campaigns.readiness(campaigns.get_campaign(campaign_id))
    assert status["ready"] is False
    assert "policy" in {check["key"] for check in status["blocking_open"]}
    with pytest.raises(ValidationError):
        campaigns.transition_campaign(campaign_id, "in_review", user)


def test_ready_campaign_reaches_scheduled(user):
    from portals.marketing.repositories import campaigns

    campaign_id = _ready_campaign(user)
    assert campaigns.readiness(campaigns.get_campaign(campaign_id))["ready"] is True
    for state in ("in_review", "approved", "scheduled"):
        campaigns.transition_campaign(campaign_id, state, user)
    campaign = campaigns.get_campaign(campaign_id)
    assert campaign["state"] == "scheduled"
    assert campaign["editable"] is False


def test_holdout_is_advisory_not_blocking(user):
    from portals.marketing.repositories import campaigns

    campaign_id = _ready_campaign(user)
    campaigns.update_campaign(
        campaign_id,
        {"code": "Q4", "name": "Q4 push", "objective": "upsell", "holdout_pct": "0",
         "segment_id": str(campaigns.get_campaign(campaign_id)["segment_id"]),
         "starts_on": "2026-10-01", "ends_on": "2026-12-31"},
        user,
    )
    status = campaigns.readiness(campaigns.get_campaign(campaign_id))
    assert status["ready"] is True
    assert "holdout" in {check["key"] for check in status["advisory_open"]}


def test_campaign_only_promotes_approved_offers(user):
    from portals.marketing.repositories import ValidationError, campaigns, catalog

    draft_offer = catalog.create_offer(
        {"code": "DRAFT1", "name": "Draft", "family": "ftth", "price_amount": "5"}, user
    )
    campaign_id = campaigns.create_campaign(
        {"code": "C2", "name": "Test", "objective": "upsell"}, user
    )
    with pytest.raises(ValidationError):
        campaigns.set_offers(campaign_id, [draft_offer], user)


# ---------------------------------------------------- consent & matching

def test_suppression_matches_across_msisdn_formats(monkeypatch, user):
    monkeypatch.setenv("NEXUS_MARKETING_MSISDN_CC", "962")
    from portals.marketing.repositories import consent

    consent.add_suppression(
        {"identifier_type": "msisdn", "identifier": "0796667777", "scope": "global",
         "reason": "regulator_dnc"},
        user,
    )
    verdict = consent.contactability("msisdn", "+962 79 666 7777")
    assert verdict["suppressed"] is True
    assert all(channel["contactable"] is False for channel in verdict["channels"])


def test_without_a_country_code_formats_do_not_collapse(monkeypatch, user):
    monkeypatch.delenv("NEXUS_MARKETING_MSISDN_CC", raising=False)
    from portals.marketing.repositories import consent

    consent.add_suppression(
        {"identifier_type": "msisdn", "identifier": "0796667777", "scope": "global",
         "reason": "regulator_dnc"},
        user,
    )
    assert consent.contactability("msisdn", "962796667777")["suppressed"] is False


def test_suppression_overrides_an_opt_in(monkeypatch, user):
    monkeypatch.setenv("NEXUS_MARKETING_MSISDN_CC", "962")
    from portals.marketing.repositories import consent

    consent.record_consent(
        {"identifier_type": "msisdn", "identifier": "0791234567", "channel": "sms",
         "status": "opt_in", "source": "self_care", "captured_at": "2026-03-01",
         "evidence_ref": "SC-1"},
        user,
    )
    assert _sms(consent.contactability("msisdn", "0791234567"))["contactable"] is True

    consent.add_suppression(
        {"identifier_type": "msisdn", "identifier": "0791234567", "scope": "global",
         "reason": "complaint"},
        user,
    )
    sms = _sms(consent.contactability("msisdn", "0791234567"))
    assert sms["contactable"] is False and sms["blocking"] is True


def _sms(verdict):
    return next(c for c in verdict["channels"] if c["channel"] == "sms")


def test_opt_in_requires_evidence(user):
    from portals.marketing.repositories import ValidationError, consent

    with pytest.raises(ValidationError):
        consent.record_consent(
            {"identifier_type": "msisdn", "identifier": "0791111111", "channel": "sms",
             "status": "opt_in", "source": "retail", "captured_at": "2026-03-01"},
            user,
        )


def test_channel_scoped_block_leaves_other_channels_alone(user):
    from portals.marketing.repositories import consent

    consent.add_suppression(
        {"identifier_type": "msisdn", "identifier": "0792222222", "scope": "channel",
         "scope_ref": "sms", "reason": "customer_request"},
        user,
    )
    verdict = consent.contactability("msisdn", "0792222222")
    assert _sms(verdict)["blocking"] is True
    email = next(c for c in verdict["channels"] if c["channel"] == "email")
    assert email["blocking"] is False


def test_policy_quiet_hours_need_both_ends(user):
    from portals.marketing.repositories import ValidationError, consent

    with pytest.raises(ValidationError):
        consent.create_policy(
            {"name": "Half window", "channel": "sms", "max_contacts": "3",
             "window_days": "30", "quiet_from": "21:00"},
            user,
        )


# ------------------------------------------------------------------ RBAC

def test_role_permissions_are_layered():
    from portals.marketing import config

    viewer = config.permissions_for_role(config.ROLE_VIEWER)
    specialist = config.permissions_for_role(config.ROLE_SPECIALIST)
    manager = config.permissions_for_role(config.ROLE_MANAGER)

    assert config.P_CAMPAIGN_EDIT not in viewer
    assert config.P_CAMPAIGN_EDIT in specialist
    assert config.P_CAMPAIGN_APPROVE not in specialist
    assert config.P_CAMPAIGN_APPROVE in manager
    assert config.P_SETTINGS_MANAGE not in manager


def test_specialist_cannot_approve_own_campaign(user):
    from portals.marketing import config
    from portals.marketing.repositories import ValidationError, campaigns

    campaign_id = _ready_campaign(user)

    class Specialist:
        username = "spec"
        role = config.ROLE_SPECIALIST
        permissions = config.permissions_for_role(config.ROLE_SPECIALIST)

        def can(self, permission):
            return permission in self.permissions

    spec = Specialist()
    campaigns.transition_campaign(campaign_id, "in_review", spec)
    assert campaigns.available_transitions(campaigns.get_campaign(campaign_id), spec) == []
    with pytest.raises(ValidationError):
        campaigns.transition_campaign(campaign_id, "approved", spec)


def test_identity_role_maps_to_portal_role():
    from portals.marketing import config

    assert config.IDENTITY_ROLE_MAP.get("admin") == config.ROLE_ADMIN
    assert config.IDENTITY_ROLE_MAP.get("noc sys") is None


# ----------------------------------------------------------------- audit

def test_every_state_change_is_audited(user):
    from portals.marketing import audit
    from portals.marketing.repositories import catalog

    offer_id = _live_offer(user)
    events = audit.recent(50, entity_type=catalog.ENTITY, entity_id=offer_id)
    actions = [event["action"] for event in events]
    assert actions.count("offer.state_changed") == 3
    assert "offer.created" in actions
    assert all(event["actor"] == "tester" for event in events)


# ------------------------------------------------------------- isolation

def test_portal_imports_nothing_from_primenet_modules():
    """Architecture rule 1: a portal is not a PrimeNet module."""
    import pathlib

    root = pathlib.Path(__file__).parent
    offenders = []
    for path in root.rglob("*.py"):
        if path.name.startswith("test_"):
            continue
        source = path.read_text(encoding="utf-8")
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import modules", "from modules")):
                offenders.append(f"{path.name}: {stripped}")
            if "sync_config" in stripped and stripped.startswith(("import ", "from ")):
                offenders.append(f"{path.name}: {stripped}")
    assert offenders == [], f"portal reached into PrimeNet internals: {offenders}"


def test_nexpulse_identity_uses_central_store_only_in_access():
    """SSO may resolve sessions via database_enhanced; only access.py should import it."""
    import pathlib

    root = pathlib.Path(__file__).parent
    importers = []
    for path in root.rglob("*.py"):
        if path.name.startswith("test_"):
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")) and "database_enhanced" in stripped:
                importers.append(path.name)
    assert importers == ["access.py"], importers
