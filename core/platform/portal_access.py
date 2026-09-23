"""Portal allow-list for central NexusCore identity (PrimeNet users DB).

Login is shared; each user has an explicit list of portals they may enter.
In-portal RBAC (PrimeNet modules, NexPulse permissions) stays separate.
"""

from __future__ import annotations

from typing import Any, Iterable

# Stable keys stored in ``users.allowed_portals`` (comma-separated).
PORTAL_PRIMENET = "primenet"
PORTAL_NEXPULSE = "nexpulse"
PORTAL_SALES = "sales"
PORTAL_SUPPORT = "support"

LIVE_PORTALS: tuple[str, ...] = (PORTAL_PRIMENET, PORTAL_NEXPULSE)
ALL_PORTAL_KEYS: tuple[str, ...] = (
    PORTAL_PRIMENET,
    PORTAL_NEXPULSE,
    PORTAL_SALES,
    PORTAL_SUPPORT,
)

PORTAL_LABELS: dict[str, str] = {
    PORTAL_PRIMENET: "Engineering (PrimeNet)",
    PORTAL_NEXPULSE: "Marketing (NexPulse)",
    PORTAL_SALES: "Sales (NexArpu)",
    PORTAL_SUPPORT: "Support (NexResolve)",
}

# Tower / URL segment → allow-list key
PORTAL_ALIASES: dict[str, str] = {
    "engineering": PORTAL_PRIMENET,
    "primenet": PORTAL_PRIMENET,
    "marketing": PORTAL_NEXPULSE,
    "nexpulse": PORTAL_NEXPULSE,
    "sales": PORTAL_SALES,
    "nexarpu": PORTAL_SALES,
    "support": PORTAL_SUPPORT,
    "nexresolve": PORTAL_SUPPORT,
}

# Existing accounts with a NULL/empty column keep Engineering access.
_LEGACY_DEFAULT: tuple[str, ...] = (PORTAL_PRIMENET,)
_ADMIN_DEFAULT: tuple[str, ...] = LIVE_PORTALS


def normalize_portal_key(raw: str | None) -> str | None:
    key = (raw or "").strip().lower()
    if not key:
        return None
    return PORTAL_ALIASES.get(key, key if key in ALL_PORTAL_KEYS else None)


def parse_allowed_portals(raw: Any, *, role: str | None = None) -> list[str]:
    """Return ordered unique portal keys for a user row value."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        role_l = (role or "").strip().lower()
        if role_l == "admin":
            return list(_ADMIN_DEFAULT)
        return list(_LEGACY_DEFAULT)

    if isinstance(raw, (list, tuple, set)):
        parts = [str(p) for p in raw]
    else:
        text = str(raw).strip()
        if text.startswith("["):
            # Tolerate accidental JSON lists from older experiments.
            try:
                import json

                parsed = json.loads(text)
                if isinstance(parsed, list):
                    parts = [str(p) for p in parsed]
                else:
                    parts = [text]
            except Exception:
                parts = [p.strip() for p in text.replace(";", ",").split(",")]
        else:
            parts = [p.strip() for p in text.replace(";", ",").split(",")]

    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        key = normalize_portal_key(part)
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    if not out:
        role_l = (role or "").strip().lower()
        return list(_ADMIN_DEFAULT if role_l == "admin" else _LEGACY_DEFAULT)
    return out


def serialize_allowed_portals(portals: Iterable[str]) -> str:
    cleaned = parse_allowed_portals(list(portals))
    return ",".join(cleaned)


def default_portals_for_role(role: str | None) -> list[str]:
    role_l = (role or "").strip().lower()
    if role_l == "admin":
        return list(_ADMIN_DEFAULT)
    return list(_LEGACY_DEFAULT)


def user_allowed_portals(user: dict | None) -> list[str]:
    if not user:
        return []
    return parse_allowed_portals(
        user.get("allowed_portals"),
        role=str(user.get("role") or ""),
    )


def user_can_access_portal(user: dict | None, portal: str | None) -> bool:
    key = normalize_portal_key(portal)
    if not key or not user:
        return False
    return key in user_allowed_portals(user)


def catalog_for_admin() -> list[dict[str, Any]]:
    """Payload for Admin Panel portal checkboxes."""
    return [
        {
            "key": key,
            "label": PORTAL_LABELS[key],
            "live": key in LIVE_PORTALS,
        }
        for key in ALL_PORTAL_KEYS
    ]
