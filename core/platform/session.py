"""Shared NexusCore session cookie helpers.

All platforms (NexusCore, PrimeNet, NexPulse) use one cookie name so a login
at the lobby is honored on every portal under the same parent domain.
``NEXUS_COOKIE_DOMAIN`` (e.g. ``.example.com``) shares the cookie across
subdomains; leave empty for localhost / same-host multi-port.
"""

from __future__ import annotations

import os

from flask import current_app, has_app_context, request

LEGACY_SESSION_COOKIES = frozenset(
    {
        "session_token",
        "primenet_session",
        "nxc_session",
        "nexpulse_session",
    }
)
DEFAULT_SHARED_COOKIE = "nexus_session"


def cookie_name() -> str:
    if has_app_context():
        configured = (current_app.config.get("SESSION_COOKIE_NAME") or "").strip()
        if configured:
            return configured
    return (
        os.getenv("NEXUS_SESSION_COOKIE")
        or os.getenv("PRIMENET_SESSION_COOKIE")
        or os.getenv("SESSION_COOKIE_NAME")
        or DEFAULT_SHARED_COOKIE
    ).strip() or DEFAULT_SHARED_COOKIE


def cookie_domain() -> str | None:
    if has_app_context():
        configured = current_app.config.get("SESSION_COOKIE_DOMAIN")
        if configured is not None:
            raw = str(configured).strip()
            return raw or None
    raw = (os.getenv("NEXUS_COOKIE_DOMAIN") or "").strip()
    return raw or None


def get_session_token() -> str | None:
    """Read the shared session cookie, with legacy per-portal name fallback."""
    name = cookie_name()
    token = request.cookies.get(name)
    if token:
        return token
    for legacy in LEGACY_SESSION_COOKIES:
        if legacy == name:
            continue
        token = request.cookies.get(legacy)
        if token:
            return token
    return None


def _secure_flag() -> bool:
    return (request.headers.get("X-Forwarded-Proto") == "https") or request.is_secure


def _cookie_kwargs(*, max_age: int | None = None, expires=None) -> dict:
    kwargs: dict = {
        "httponly": True,
        "secure": _secure_flag(),
        "samesite": "Lax",
        "path": "/",
    }
    domain = cookie_domain()
    if domain:
        kwargs["domain"] = domain
    if max_age is not None:
        kwargs["max_age"] = max_age
    if expires is not None:
        kwargs["expires"] = expires
    return kwargs


def set_session_cookie(response, token: str, *, max_age: int | None = None):
    response.set_cookie(cookie_name(), token, **_cookie_kwargs(max_age=max_age))
    return response


def clear_session_cookie(response):
    """Expire the shared cookie and legacy per-portal names."""
    names = {cookie_name(), *LEGACY_SESSION_COOKIES}
    base = _cookie_kwargs(expires=0)
    for name in names:
        response.set_cookie(name, "", **base)
        # Also clear host-only copies when a Domain was set.
        if "domain" in base:
            host_only = dict(base)
            host_only.pop("domain", None)
            response.set_cookie(name, "", **host_only)
    return response
