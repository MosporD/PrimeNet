"""Marketing Portal — domain vocabulary, paths, roles, and lifecycles.

Everything here is portal-local on purpose: the portal must keep running when
it is split out of the PrimeNet process into its own service, so it defines
its own storage path and its own access model rather than borrowing PrimeNet's.
"""

from __future__ import annotations

import os

PORTAL_ID = "marketing"
PORTAL_NAME = "NexPulse"
PORTAL_DOMAIN = "Marketing"
PORTAL_BLURB = "Campaigns, offers, audiences, and consent for an ISP marketing function."
URL_PREFIX = "/portals/marketing"

_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_PACKAGE_DIR))


def database_path() -> str:
    """Portal-owned SQLite file. Never a PrimeNet database."""
    override = (os.getenv("NEXUS_MARKETING_DB") or "").strip()
    if override:
        return os.path.abspath(override)
    data_root = (os.getenv("NEXUS_DATA_ROOT") or "").strip() or _REPO_ROOT
    return os.path.join(
        os.path.abspath(data_root), "data", "portals", "marketing", "marketing.db"
    )


# ---------------------------------------------------------------------------
# Access model
# ---------------------------------------------------------------------------

ROLE_ADMIN = "marketing_admin"
ROLE_MANAGER = "marketing_manager"
ROLE_SPECIALIST = "marketing_specialist"
ROLE_ANALYST = "marketing_analyst"
ROLE_VIEWER = "marketing_viewer"

ROLES: dict[str, dict[str, str]] = {
    ROLE_ADMIN: {
        "label": "Marketing Admin",
        "description": "Full control including role assignment and portal settings.",
    },
    ROLE_MANAGER: {
        "label": "Marketing Manager",
        "description": "Approves offers and campaigns, manages contact policy.",
    },
    ROLE_SPECIALIST: {
        "label": "Campaign Specialist",
        "description": "Builds offers, campaigns, and audiences; submits them for approval.",
    },
    ROLE_ANALYST: {
        "label": "Marketing Analyst",
        "description": "Builds and reads audiences; read-only elsewhere.",
    },
    ROLE_VIEWER: {
        "label": "Viewer",
        "description": "Read-only access across the portal.",
    },
}

DEFAULT_ROLE = ROLE_VIEWER

# Identity roles coming from the shared NexusCore login map onto portal roles.
# Anything unmapped falls back to DEFAULT_ROLE, and an explicit per-user
# assignment stored in this portal always wins over the mapping.
IDENTITY_ROLE_MAP: dict[str, str] = {
    "admin": ROLE_ADMIN,
}

# Permissions
P_CATALOG_VIEW = "catalog.view"
P_CATALOG_EDIT = "catalog.edit"
P_CATALOG_APPROVE = "catalog.approve"
P_CAMPAIGN_VIEW = "campaign.view"
P_CAMPAIGN_EDIT = "campaign.edit"
P_CAMPAIGN_APPROVE = "campaign.approve"
P_SEGMENT_VIEW = "segment.view"
P_SEGMENT_EDIT = "segment.edit"
P_CONSENT_VIEW = "consent.view"
P_CONSENT_EDIT = "consent.edit"
P_POLICY_EDIT = "policy.edit"
P_AUDIT_VIEW = "audit.view"
P_SETTINGS_MANAGE = "settings.manage"

_READ_ONLY = frozenset(
    {P_CATALOG_VIEW, P_CAMPAIGN_VIEW, P_SEGMENT_VIEW, P_CONSENT_VIEW}
)

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    ROLE_VIEWER: _READ_ONLY,
    ROLE_ANALYST: _READ_ONLY | {P_SEGMENT_EDIT},
    ROLE_SPECIALIST: _READ_ONLY
    | {P_SEGMENT_EDIT, P_CATALOG_EDIT, P_CAMPAIGN_EDIT, P_CONSENT_EDIT},
    ROLE_MANAGER: _READ_ONLY
    | {
        P_SEGMENT_EDIT,
        P_CATALOG_EDIT,
        P_CAMPAIGN_EDIT,
        P_CONSENT_EDIT,
        P_CATALOG_APPROVE,
        P_CAMPAIGN_APPROVE,
        P_POLICY_EDIT,
        P_AUDIT_VIEW,
    },
    ROLE_ADMIN: frozenset(
        {
            P_CATALOG_VIEW,
            P_CATALOG_EDIT,
            P_CATALOG_APPROVE,
            P_CAMPAIGN_VIEW,
            P_CAMPAIGN_EDIT,
            P_CAMPAIGN_APPROVE,
            P_SEGMENT_VIEW,
            P_SEGMENT_EDIT,
            P_CONSENT_VIEW,
            P_CONSENT_EDIT,
            P_POLICY_EDIT,
            P_AUDIT_VIEW,
            P_SETTINGS_MANAGE,
        }
    ),
}


def permissions_for_role(role: str) -> frozenset[str]:
    return ROLE_PERMISSIONS.get((role or "").strip().lower(), frozenset())


# ---------------------------------------------------------------------------
# Lifecycles
# ---------------------------------------------------------------------------
# A transition is (to_state, label, required_permission). Guarding the state
# machine here keeps the rules in one readable place instead of scattered
# across views.

OFFER_STATES: dict[str, dict[str, str]] = {
    "draft": {"label": "Draft", "tone": "neutral"},
    "in_review": {"label": "In review", "tone": "pending"},
    "approved": {"label": "Approved", "tone": "ok"},
    "live": {"label": "Live", "tone": "live"},
    "retired": {"label": "Retired", "tone": "muted"},
}

OFFER_TRANSITIONS: dict[str, list[tuple[str, str, str]]] = {
    "draft": [("in_review", "Submit for review", P_CATALOG_EDIT)],
    "in_review": [
        ("approved", "Approve", P_CATALOG_APPROVE),
        ("draft", "Send back to draft", P_CATALOG_APPROVE),
    ],
    "approved": [
        ("live", "Publish", P_CATALOG_APPROVE),
        ("draft", "Reopen as draft", P_CATALOG_APPROVE),
    ],
    "live": [("retired", "Retire", P_CATALOG_APPROVE)],
    "retired": [("draft", "Reopen as draft", P_CATALOG_APPROVE)],
}

CAMPAIGN_STATES: dict[str, dict[str, str]] = {
    "draft": {"label": "Draft", "tone": "neutral"},
    "in_review": {"label": "In review", "tone": "pending"},
    "approved": {"label": "Approved", "tone": "ok"},
    "scheduled": {"label": "Scheduled", "tone": "ok"},
    "running": {"label": "Running", "tone": "live"},
    "paused": {"label": "Paused", "tone": "warn"},
    "completed": {"label": "Completed", "tone": "muted"},
    "cancelled": {"label": "Cancelled", "tone": "muted"},
}

CAMPAIGN_TRANSITIONS: dict[str, list[tuple[str, str, str]]] = {
    "draft": [
        ("in_review", "Submit for review", P_CAMPAIGN_EDIT),
        ("cancelled", "Cancel", P_CAMPAIGN_EDIT),
    ],
    "in_review": [
        ("approved", "Approve", P_CAMPAIGN_APPROVE),
        ("draft", "Send back to draft", P_CAMPAIGN_APPROVE),
    ],
    "approved": [
        ("scheduled", "Schedule", P_CAMPAIGN_APPROVE),
        ("draft", "Reopen as draft", P_CAMPAIGN_APPROVE),
    ],
    "scheduled": [
        ("running", "Start", P_CAMPAIGN_APPROVE),
        ("cancelled", "Cancel", P_CAMPAIGN_APPROVE),
    ],
    "running": [
        ("paused", "Pause", P_CAMPAIGN_APPROVE),
        ("completed", "Complete", P_CAMPAIGN_APPROVE),
    ],
    "paused": [
        ("running", "Resume", P_CAMPAIGN_APPROVE),
        ("completed", "Complete", P_CAMPAIGN_APPROVE),
        ("cancelled", "Cancel", P_CAMPAIGN_APPROVE),
    ],
    "completed": [],
    "cancelled": [],
}

# States where a campaign is considered committed — editing core targeting
# after this point would invalidate the approval it received.
CAMPAIGN_LOCKED_STATES = frozenset({"scheduled", "running", "paused", "completed", "cancelled"})
OFFER_LOCKED_STATES = frozenset({"live", "retired"})


# ---------------------------------------------------------------------------
# Domain vocabulary
# ---------------------------------------------------------------------------

CHANNELS: dict[str, dict[str, str]] = {
    "sms": {"label": "SMS", "addressable": "msisdn"},
    "email": {"label": "Email", "addressable": "email"},
    "push": {"label": "App push", "addressable": "device"},
    "ivr": {"label": "IVR / voice", "addressable": "msisdn"},
    "outbound_call": {"label": "Outbound call", "addressable": "msisdn"},
    "app_banner": {"label": "Self-care app banner", "addressable": "account"},
    "retail": {"label": "Retail / POS", "addressable": "account"},
    "paid_digital": {"label": "Paid digital", "addressable": "audience"},
}

OFFER_FAMILIES: dict[str, str] = {
    "ftth": "Fibre (FTTH)",
    "fwa": "Fixed wireless (FWA)",
    "mobile_postpaid": "Mobile postpaid",
    "mobile_prepaid": "Mobile prepaid",
    "mobile_data": "Mobile data / bundles",
    "b2b": "Business / B2B",
    "device": "Device & CPE",
    "value_added": "Value-added service",
}

CAMPAIGN_OBJECTIVES: dict[str, str] = {
    "acquisition": "Acquisition",
    "upsell": "Upsell / upgrade",
    "cross_sell": "Cross-sell",
    "retention": "Retention / churn save",
    "winback": "Win-back",
    "usage": "Usage stimulation",
    "awareness": "Awareness / brand",
    "migration": "Technology migration",
}

# Subscriber attributes a segment rule can target. `source` records where the
# value will come from once ingestion exists — "network" attributes arrive from
# the Engineering Portal API, never from its database.
SEGMENT_ATTRIBUTES: list[dict] = [
    {"key": "subscriber_type", "label": "Subscriber type", "type": "enum", "source": "crm",
     "values": ["prepaid", "postpaid", "ftth", "fwa", "b2b"]},
    {"key": "current_plan", "label": "Current plan", "type": "text", "source": "crm"},
    {"key": "arpu_band", "label": "ARPU band", "type": "enum", "source": "billing",
     "values": ["low", "medium", "high", "premium"]},
    {"key": "tenure_months", "label": "Tenure (months)", "type": "number", "source": "crm"},
    {"key": "contract_end_days", "label": "Days to contract end", "type": "number", "source": "crm"},
    {"key": "data_usage_gb", "label": "Monthly data usage (GB)", "type": "number", "source": "usage"},
    {"key": "data_usage_trend", "label": "Data usage trend", "type": "enum", "source": "usage",
     "values": ["rising", "flat", "falling"]},
    {"key": "churn_risk", "label": "Churn risk", "type": "enum", "source": "analytics",
     "values": ["low", "medium", "high"]},
    {"key": "device_class", "label": "Device class", "type": "enum", "source": "crm",
     "values": ["2g", "3g", "4g", "5g", "cpe", "unknown"]},
    {"key": "region", "label": "Region / governorate", "type": "text", "source": "crm"},
    {"key": "billing_status", "label": "Billing status", "type": "enum", "source": "billing",
     "values": ["current", "overdue", "suspended"]},
    {"key": "served_technology", "label": "Best served technology", "type": "enum", "source": "network",
     "values": ["2g", "3g", "4g", "5g", "ftth"]},
    {"key": "ftth_serviceable", "label": "FTTH serviceable address", "type": "boolean", "source": "network"},
    {"key": "site_congested", "label": "On a congested site", "type": "boolean", "source": "network"},
    {"key": "experience_degraded", "label": "Degraded network experience", "type": "boolean", "source": "network"},
]

SEGMENT_OPERATORS: dict[str, dict] = {
    "eq": {"label": "is", "types": ["enum", "text", "number", "boolean"]},
    "ne": {"label": "is not", "types": ["enum", "text", "number", "boolean"]},
    "in": {"label": "is any of", "types": ["enum", "text"], "multi": True},
    "not_in": {"label": "is none of", "types": ["enum", "text"], "multi": True},
    "gt": {"label": "is greater than", "types": ["number"]},
    "gte": {"label": "is at least", "types": ["number"]},
    "lt": {"label": "is less than", "types": ["number"]},
    "lte": {"label": "is at most", "types": ["number"]},
    "contains": {"label": "contains", "types": ["text"]},
    "is_set": {"label": "has any value", "types": ["enum", "text", "number", "boolean"], "no_value": True},
    "is_not_set": {"label": "has no value", "types": ["enum", "text", "number", "boolean"], "no_value": True},
}

CONSENT_STATUSES: dict[str, str] = {
    "opt_in": "Opted in",
    "opt_out": "Opted out",
    "pending": "Pending confirmation",
    "withdrawn": "Withdrawn",
}

CONSENT_SOURCES: dict[str, str] = {
    "self_care": "Self-care app / portal",
    "retail": "Retail store",
    "call_centre": "Call centre",
    "sms_keyword": "SMS keyword",
    "web_form": "Web form",
    "contract": "Contract signature",
    "regulator": "Regulator instruction",
    "import": "Bulk import",
}

SUPPRESSION_SCOPES: dict[str, str] = {
    "global": "All marketing contact",
    "channel": "One channel",
    "campaign": "One campaign",
}

SUPPRESSION_REASONS: dict[str, str] = {
    "customer_request": "Customer request",
    "regulator_dnc": "Regulator do-not-call register",
    "complaint": "Complaint",
    "fraud": "Fraud / abuse",
    "deceased": "Deceased",
    "legal_hold": "Legal hold",
    "data_quality": "Bad contact data",
}

IDENTIFIER_TYPES: dict[str, str] = {
    "msisdn": "MSISDN",
    "email": "Email address",
    "account_id": "Account ID",
    "subscriber_id": "Subscriber ID",
}


# ---------------------------------------------------------------------------
# MSISDN normalisation
# ---------------------------------------------------------------------------
# Consent and do-not-call matching is only as good as identifier normalisation:
# if "0791234567" and "962791234567" are stored as two different subscribers, a
# regulator block recorded against one will not stop a send to the other. Set
# the operator's country code so national and international forms collapse to
# one canonical value. No country is assumed by default — when this is unset,
# the portal stores digits as entered and says so in the consent screens.

def msisdn_country_code() -> str:
    return "".join(ch for ch in (os.getenv("NEXUS_MARKETING_MSISDN_CC") or "") if ch.isdigit())


def msisdn_national_prefix() -> str:
    raw = os.getenv("NEXUS_MARKETING_MSISDN_TRUNK")
    if raw is None:
        return "0"
    return "".join(ch for ch in raw if ch.isdigit())


def msisdn_normalisation_active() -> bool:
    return bool(msisdn_country_code())
