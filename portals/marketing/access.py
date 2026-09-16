"""Identity bridge and portal access control.

NexusCore architecture rule 2: one identity service owns users and sessions
and every portal trusts it. Today that service is PrimeNet's login, so the
bridge below is the *only* place in this portal that reaches into it. When
identity is extracted into a standalone service, this file is the single
thing that changes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps
from typing import Callable

from flask import abort, g, redirect, request, url_for

from . import config
from .db import cursor

SESSION_COOKIE = "session_token"


# ---------------------------------------------------------------------------
# Identity bridge
# ---------------------------------------------------------------------------

def _resolve_session(token: str) -> dict | None:
    """Ask the shared identity service who owns this session token."""
    try:
        from database_enhanced import get_user_by_session
    except Exception:
        return None
    try:
        user = get_user_by_session(token)
    except Exception:
        return None
    if not user:
        return None
    if isinstance(user, dict):
        return {
            "id": str(user.get("id") or ""),
            "username": user.get("username") or "",
            "email": user.get("email") or "",
            "identity_role": str(user.get("role") or "").strip().lower(),
        }
    # Tuple-shaped rows from the legacy user store.
    try:
        return {
            "id": str(user[0]),
            "username": user[1],
            "email": user[2] if len(user) > 2 else "",
            "identity_role": str(user[6]).strip().lower() if len(user) > 6 else "",
        }
    except Exception:
        return None


def current_identity() -> dict | None:
    cached = getattr(g, "_mkt_identity", None)
    if cached is not None:
        return cached or None
    token = request.cookies.get(SESSION_COOKIE)
    identity = _resolve_session(token) if token else None
    g._mkt_identity = identity or {}
    return identity


# ---------------------------------------------------------------------------
# Portal role resolution
# ---------------------------------------------------------------------------

def _stored_role(identity_user_id: str) -> str | None:
    if not identity_user_id:
        return None
    with cursor() as conn:
        row = conn.execute(
            "SELECT role FROM portal_user_role WHERE identity_user_id = ?",
            (identity_user_id,),
        ).fetchone()
    if not row:
        return None
    role = str(row["role"] or "").strip().lower()
    return role if role in config.ROLES else None


def portal_role(identity: dict | None) -> str:
    """Explicit portal assignment wins; otherwise map the identity role."""
    if not identity:
        return config.DEFAULT_ROLE
    stored = _stored_role(identity.get("id") or "")
    if stored:
        return stored
    mapped = config.IDENTITY_ROLE_MAP.get(identity.get("identity_role") or "")
    return mapped or config.DEFAULT_ROLE


def assign_role(identity_user_id: str, username: str, role: str, assigned_by: str) -> None:
    role = (role or "").strip().lower()
    if role not in config.ROLES:
        raise ValueError(f"Unknown marketing role: {role}")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with cursor() as conn:
        conn.execute(
            "INSERT INTO portal_user_role (identity_user_id, username, role, assigned_by, assigned_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(identity_user_id) DO UPDATE SET "
            "username = excluded.username, role = excluded.role, "
            "assigned_by = excluded.assigned_by, assigned_at = excluded.assigned_at",
            (str(identity_user_id), username, role, assigned_by, now),
        )


class PortalUser:
    """The acting user, as this portal sees them."""

    __slots__ = ("id", "username", "email", "identity_role", "role", "permissions")

    def __init__(self, identity: dict, role: str):
        self.id = identity.get("id") or ""
        self.username = identity.get("username") or ""
        self.email = identity.get("email") or ""
        self.identity_role = identity.get("identity_role") or ""
        self.role = role
        self.permissions = config.permissions_for_role(role)

    @property
    def role_label(self) -> str:
        return config.ROLES.get(self.role, {}).get("label", self.role)

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    def can_any(self, *permissions: str) -> bool:
        return any(p in self.permissions for p in permissions)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "role_label": self.role_label,
            "permissions": sorted(self.permissions),
        }


def current_user() -> PortalUser | None:
    identity = current_identity()
    if not identity:
        return None
    cached = getattr(g, "_mkt_user", None)
    if cached is not None:
        return cached
    user = PortalUser(identity, portal_role(identity))
    g._mkt_user = user
    return user


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------

def _wants_json() -> bool:
    if request.path.startswith(f"{config.URL_PREFIX}/api/"):
        return True
    return request.accept_mimetypes.best == "application/json"


def login_required(view: Callable) -> Callable:
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            if _wants_json():
                abort(401)
            return redirect(url_for("auth.login_page"))
        return view(*args, **kwargs)

    return wrapped


def require_permission(permission: str) -> Callable:
    def decorator(view: Callable) -> Callable:
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                if _wants_json():
                    abort(401)
                return redirect(url_for("auth.login_page"))
            if not user.can(permission):
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator
