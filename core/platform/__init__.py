"""Shared Flask boot and per-platform identity helpers."""

from .base_app import create_base_app, env_true, run_dev_server
from .session import (
    DEFAULT_SHARED_COOKIE,
    LEGACY_SESSION_COOKIES,
    clear_session_cookie,
    cookie_domain,
    cookie_name,
    get_session_token,
    set_session_cookie,
)

# Backward-compatible alias (single legacy name used by older imports).
LEGACY_SESSION_COOKIE = "session_token"

__all__ = [
    "create_base_app",
    "env_true",
    "run_dev_server",
    "DEFAULT_SHARED_COOKIE",
    "LEGACY_SESSION_COOKIE",
    "LEGACY_SESSION_COOKIES",
    "clear_session_cookie",
    "cookie_domain",
    "cookie_name",
    "get_session_token",
    "set_session_cookie",
]
