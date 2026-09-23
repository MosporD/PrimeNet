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


def public_url(key: str, default: str) -> str:
    return (os.getenv(key) or default).rstrip("/")


def nexuscore_public_url() -> str:
    return public_url("NEXUSCORE_PUBLIC_URL", "http://localhost:8000")


def primenet_public_url() -> str:
    return public_url("PRIMENET_PUBLIC_URL", "http://localhost:8001")


def nexpulse_public_url() -> str:
    return public_url("NEXPULSE_PUBLIC_URL", "http://localhost:8002")
