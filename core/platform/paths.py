"""Default paths and public URLs for the three platform processes."""

from __future__ import annotations

import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _data_root() -> str:
    return (
        (os.getenv("NEXUS_DATA_ROOT") or "").strip()
        or (os.getenv("NCM_DATA_ROOT") or "").strip()
        or _ROOT
    )


def _env_path(key: str, default: str) -> str:
    raw = (os.getenv(key) or "").strip()
    return raw if raw else default


def nexuscore_users_db() -> str:
    return _env_path(
        "NEXUSCORE_USERS_DB",
        os.path.join(_data_root(), "databases", "nexuscore", "users.db"),
    )


def nexpulse_users_db() -> str:
    return _env_path(
        "NEXPULSE_USERS_DB",
        os.path.join(_data_root(), "data", "portals", "marketing", "users.db")
        if _data_root() == _ROOT
        else os.path.join(_data_root(), "portals", "marketing", "users.db"),
    )


def _env_true(key: str, default: bool = False) -> bool:
    raw = (os.getenv(key) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def public_url(key: str, default: str) -> str:
    return (os.getenv(key) or default).rstrip("/")


def suite_public_url() -> str | None:
    """Shared public origin when all portals share one reverse-proxy host.

    Priority:
    1. ``NEXUS_PUBLIC_URL`` (explicit)
    2. Request Host (when ``NEXUS_PUBLIC_URL_FROM_REQUEST=1``)
    """
    explicit = (os.getenv("NEXUS_PUBLIC_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    if not _env_true("NEXUS_PUBLIC_URL_FROM_REQUEST"):
        return None
    try:
        from flask import has_request_context, request

        if not has_request_context():
            return None
        proto = (request.headers.get("X-Forwarded-Proto") or request.scheme or "http")
        proto = proto.split(",")[0].strip() or "http"
        host = (request.headers.get("X-Forwarded-Host") or request.host or "").strip()
        host = host.split(",")[0].strip()
        if not host:
            return None
        return f"{proto}://{host}".rstrip("/")
    except Exception:
        return None


def portals_share_origin() -> bool:
    """True when nginx path-routes all portals on one public host (no :800x)."""
    if (os.getenv("NEXUS_PUBLIC_URL") or "").strip():
        return True
    if _env_true("NEXUS_PUBLIC_URL_FROM_REQUEST"):
        return True
    nxc = (os.getenv("NEXUSCORE_PUBLIC_URL") or "").strip().rstrip("/")
    pn = (os.getenv("PRIMENET_PUBLIC_URL") or "").strip().rstrip("/")
    np = (os.getenv("NEXPULSE_PUBLIC_URL") or "").strip().rstrip("/")
    if nxc and pn and np and nxc == pn == np:
        return True
    return False


def nexuscore_public_url() -> str:
    suite = suite_public_url()
    if suite:
        return suite
    return public_url("NEXUSCORE_PUBLIC_URL", "http://localhost:8000")


def primenet_public_url() -> str:
    suite = suite_public_url()
    if suite:
        return suite
    return public_url("PRIMENET_PUBLIC_URL", "http://localhost:8001")


def nexpulse_public_url() -> str:
    suite = suite_public_url()
    if suite:
        return suite
    return public_url("NEXPULSE_PUBLIC_URL", "http://localhost:8002")


def primenet_entry_url() -> str:
    """Engineering entry — relative when behind the single-host proxy."""
    if portals_share_origin():
        return "/dashboard"
    return f"{primenet_public_url()}/dashboard"


def nexpulse_entry_url() -> str:
    """Marketing entry — relative when behind the single-host proxy."""
    if portals_share_origin():
        return "/portals/marketing/"
    return f"{nexpulse_public_url()}/portals/marketing/"


def nexuscore_entry_url() -> str:
    if portals_share_origin():
        return "/portals"
    return f"{nexuscore_public_url()}/portals"


def platform_admin_entry_url() -> str:
    if portals_share_origin():
        return "/admin"
    return f"{nexuscore_public_url()}/admin"