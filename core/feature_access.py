"""
Configurable feature access.

Stores, per feature (nav href), which roles may see/use it. Defaults are derived
from the hardcoded ``visibility`` in ``core.module_access.NAV_SECTIONS`` so the
system behaves identically until an Owner edits role rules from PrimeNet
Engineering Admin (Module Access by role).

Per-user overrides (``user_feature_access``) win over role rules when set.

Invariants:
- ``admin`` (Owner) always has access to everything — never stored, never
  editable, cannot be revoked.
- A small set of core features is LOCKED (dashboard, profile, admin panel) so an
  admin can never lock themselves or NOC out of essentials.

Storage: table ``feature_access`` in the PrimeNet app DB. Only overrides that
differ from defaults are persisted; everything else falls back to defaults.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

# Role model (mirrors admin_panel.ROLE_LABELS). ``admin`` is implicit/always-on.
ROLE_ORDER = ["admin", "noc_sys", "ran_config_user", "user"]
ROLE_LABELS = {
    "admin": "Owner",
    "noc_sys": "NOC SYS",
    "ran_config_user": "RNC User",
    "user": "User",
}
# Roles an admin can toggle per feature (admin is excluded — always allowed).
EDITABLE_ROLES = ["noc_sys", "ran_config_user", "user"]

# Features that cannot be restricted (prevent self/NOC lockout). Kept at their
# default visibility and shown read-only in the UI.
LOCKED_HREFS = {"/dashboard", "/profile", "/admin-panel"}

_CACHE_TTL_SECONDS = 10
_lock = threading.Lock()
_cache: dict[str, object] = {"at": 0.0, "data": None}


def default_roles(visibility: str) -> set[str]:
    """Map a NAV_SECTIONS visibility level to the editable roles enabled by default."""
    v = (visibility or "all").strip().lower()
    if v == "admin":
        return set()  # admin-only (admin is implicit)
    if v == "admin_or_noc":
        return {"noc_sys"}
    return set(EDITABLE_ROLES)  # "all"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _connect():
    # Local import to avoid import cycles at module load.
    from db.runtime import connect_app

    return connect_app()


def _ensure_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS feature_access (
            href       TEXT PRIMARY KEY,
            roles      TEXT NOT NULL DEFAULT '',
            updated_by TEXT,
            updated_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_feature_access (
            user_id    INTEGER NOT NULL,
            href       TEXT NOT NULL,
            allowed    INTEGER NOT NULL,
            updated_by TEXT,
            updated_at TEXT,
            PRIMARY KEY (user_id, href)
        )
        """
    )
    conn.commit()


def _bust_cache() -> None:
    with _lock:
        _cache["at"] = 0.0
        _cache["data"] = None


def get_overrides() -> dict[str, set[str]]:
    """Return {href: set(editable roles enabled)} for stored overrides only.

    Cached briefly. On any DB error (e.g. table missing on a fresh DB), returns
    an empty dict so callers fall back to defaults.
    """
    now = time.time()
    with _lock:
        data = _cache["data"]
        if data is not None and (now - float(_cache["at"])) < _CACHE_TTL_SECONDS:
            return dict(data)  # shallow copy of the mapping

    result: dict[str, set[str]] = {}
    try:
        conn = _connect()
        try:
            _ensure_table(conn)
            for row in conn.execute("SELECT href, roles FROM feature_access"):
                href = str(row["href"])
                roles = {
                    r.strip().lower()
                    for r in str(row["roles"] or "").split(",")
                    if r.strip()
                }
                result[href] = roles & set(EDITABLE_ROLES)
        finally:
            conn.close()
    except Exception:
        return {}

    with _lock:
        _cache["at"] = now
        _cache["data"] = result
    return dict(result)


def effective_roles(href: str, default_visibility: str) -> set[str]:
    """The editable roles enabled for a feature (override if present, else default)."""
    if href in LOCKED_HREFS:
        return default_roles(default_visibility)
    overrides = get_overrides()
    if href in overrides:
        return overrides[href]
    return default_roles(default_visibility)


def role_can_access(href: str, default_visibility: str, role: str) -> bool:
    """True if ``role`` may access ``href`` given config. Admin always True."""
    r = (role or "").strip().lower()
    if r == "admin":
        return True
    return r in effective_roles(href, default_visibility)


def get_user_override(user_id: int, href: str) -> bool | None:
    """Per-user override: True/False, or None to inherit role rules."""
    if user_id is None:
        return None
    try:
        conn = _connect()
        try:
            _ensure_table(conn)
            row = conn.execute(
                "SELECT allowed FROM user_feature_access WHERE user_id = ? AND href = ?",
                (int(user_id), str(href)),
            ).fetchone()
            if not row:
                return None
            val = row["allowed"] if isinstance(row, dict) else row[0]
            return bool(val)
        finally:
            conn.close()
    except Exception:
        return None


def get_user_overrides(user_id: int) -> dict[str, bool]:
    """All overrides for a user: {href: allowed}."""
    out: dict[str, bool] = {}
    if user_id is None:
        return out
    try:
        conn = _connect()
        try:
            _ensure_table(conn)
            for row in conn.execute(
                "SELECT href, allowed FROM user_feature_access WHERE user_id = ?",
                (int(user_id),),
            ):
                href = str(row["href"] if isinstance(row, dict) else row[0])
                allowed = row["allowed"] if isinstance(row, dict) else row[1]
                out[href] = bool(allowed)
        finally:
            conn.close()
    except Exception:
        return {}
    return out


def set_user_override(
    user_id: int,
    href: str,
    allowed: bool | None,
    updated_by: str = "",
) -> None:
    """Set per-user override (None clears — inherit role rules)."""
    if href in LOCKED_HREFS:
        return
    conn = _connect()
    try:
        _ensure_table(conn)
        if allowed is None:
            conn.execute(
                "DELETE FROM user_feature_access WHERE user_id = ? AND href = ?",
                (int(user_id), str(href)),
            )
        else:
            conn.execute(
                """
                INSERT INTO user_feature_access (user_id, href, allowed, updated_by, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, href) DO UPDATE SET
                    allowed = excluded.allowed,
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                (
                    int(user_id),
                    str(href),
                    bool(allowed),
                    str(updated_by or ""),
                    _now_iso(),
                ),
            )
        conn.commit()
    finally:
        conn.close()
    _bust_cache()


def reset_user_overrides(user_id: int) -> None:
    conn = _connect()
    try:
        _ensure_table(conn)
        conn.execute(
            "DELETE FROM user_feature_access WHERE user_id = ?",
            (int(user_id),),
        )
        conn.commit()
    finally:
        conn.close()
    _bust_cache()


def user_can_access(
    href: str,
    default_visibility: str,
    role: str,
    user_id: int | None = None,
) -> bool:
    """Role rules unless a per-user override exists (Owner always True)."""
    r = (role or "").strip().lower()
    if r == "admin":
        return True
    if user_id is not None:
        override = get_user_override(int(user_id), href)
        if override is not None:
            return bool(override)
    return role_can_access(href, default_visibility, role)


def set_feature_roles(href: str, roles, updated_by: str = "") -> None:
    """Persist the editable roles for a feature. LOCKED features are ignored."""
    if href in LOCKED_HREFS:
        return
    clean = ",".join(
        r for r in EDITABLE_ROLES if r in {str(x).strip().lower() for x in (roles or [])}
    )
    conn = _connect()
    try:
        _ensure_table(conn)
        conn.execute(
            """
            INSERT INTO feature_access (href, roles, updated_by, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(href) DO UPDATE SET
                roles = excluded.roles,
                updated_by = excluded.updated_by,
                updated_at = excluded.updated_at
            """,
            (href, clean, str(updated_by or ""), _now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    _bust_cache()


def reset_all() -> None:
    """Delete all role overrides, restoring hardcoded defaults."""
    conn = _connect()
    try:
        _ensure_table(conn)
        conn.execute("DELETE FROM feature_access")
        conn.commit()
    finally:
        conn.close()
    _bust_cache()


def reset_all_user_overrides() -> None:
    """Delete every per-user module override."""
    conn = _connect()
    try:
        _ensure_table(conn)
        conn.execute("DELETE FROM user_feature_access")
        conn.commit()
    finally:
        conn.close()
    _bust_cache()
