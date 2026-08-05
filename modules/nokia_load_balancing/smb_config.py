"""Network Balance SMB share settings (Linux / Docker auto-mount)."""

from __future__ import annotations

import os
import sys


def _truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "")
    if not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def smb_enabled() -> bool:
    return _truthy("NETWORK_BALANCE_SMB_ENABLED", default=False)


def smb_settings() -> dict[str, str | bool]:
    mount = (
        os.environ.get("NETWORK_BALANCE_SMB_MOUNT", "").strip()
        or os.environ.get("NETWORK_BALANCE_PATH", "").strip()
        or "/network-balance"
    )
    host = os.environ.get("NETWORK_BALANCE_SMB_HOST", "").strip()
    user = os.environ.get("NETWORK_BALANCE_SMB_USER", "").strip()
    password = os.environ.get("NETWORK_BALANCE_SMB_PASSWORD", "").strip()
    return {
        "enabled": smb_enabled(),
        "host": host,
        "share": os.environ.get("NETWORK_BALANCE_SMB_SHARE", "Network Balance").strip() or "Network Balance",
        "user": user,
        "password": password,
        "domain": os.environ.get("NETWORK_BALANCE_SMB_DOMAIN", "").strip(),
        "mount_point": mount,
        "configured": bool(host and user and password),
    }


def resolve_balance_path() -> str:
    explicit = os.environ.get("NETWORK_BALANCE_PATH", "").strip()
    if explicit:
        return explicit
    if smb_enabled() or os.environ.get("NCM_CONTAINER") == "1":
        return str(smb_settings()["mount_point"])
    if sys.platform == "win32":
        return r"\\RNO-WAN\Network Balance"
    return "/network-balance"


def mount_point_active(path: str) -> bool:
    """True when path is a live mount (Linux /proc/mounts) or contains CSV files."""
    from pathlib import Path

    folder = Path(path)
    try:
        if any(folder.glob("*.csv")):
            return True
    except OSError:
        return False
    try:
        target = str(folder.resolve())
        with open("/proc/mounts", encoding="utf-8") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == target:
                    return True
    except OSError:
        pass
    return False


def smb_status_public() -> dict[str, str | bool | None]:
    """Safe for API/UI — never exposes password."""
    cfg = smb_settings()
    mount = str(cfg["mount_point"])
    return {
        "enabled": bool(cfg["enabled"]),
        "configured": bool(cfg["configured"]),
        "host": cfg["host"] or None,
        "share": cfg["share"],
        "domain": cfg["domain"] or None,
        "user": cfg["user"] or None,
        "mount_point": mount,
        "mounted": mount_point_active(mount),
    }
