"""
Operator activation for PrimeNet (password unlock, configurable period).

Modes (set in .env):
  **Remote (recommended)** — separate license service holds the private signing key.
    NCM_LICENSE_SERVER_URL=http://your-license-host:5055
    NCM_LICENSE_PUBLIC_KEY_PATH=path/to/public.pem

  **Local** — password hash on this machine (no separate server).
    Run: python scripts/set_activation_password.py

Development bypass: NCM_SKIP_ACTIVATION=1

Creator / operator local unlock period: NCM_ACTIVATION_PERIOD_DAYS=180 (default 6 months).
Set your password once: python scripts/set_activation_password.py
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_STATE_FILENAME = ".ncm_activation_state"
_DEFAULT_ACTIVATION_PERIOD_DAYS = 180


def activation_period_days() -> int:
    """
    Days each successful unlock keeps PrimeNet active (local mode).
    Override with NCM_ACTIVATION_PERIOD_DAYS (default 180 ≈ six months).
    """
    raw = (os.getenv("NCM_ACTIVATION_PERIOD_DAYS") or "").strip()
    if not raw:
        return _DEFAULT_ACTIVATION_PERIOD_DAYS
    try:
        days = int(raw)
    except ValueError:
        return _DEFAULT_ACTIVATION_PERIOD_DAYS
    return max(1, min(days, 3650))
_PBKDF2_ITERATIONS = 600_000

_ORIGINAL_SQLITE_CONNECT = sqlite3.connect
_SQLITE_GATE_INSTALLED = False


class ActivationRequired(Exception):
    def __init__(self, message: str | None = None, *, days_remaining: int | None = None):
        self.days_remaining = days_remaining
        super().__init__(message or "Operator activation required")


def _env_true(key: str) -> bool:
    return (os.getenv(key) or "").strip().lower() in ("1", "true", "yes", "on")


def is_bypass_enabled() -> bool:
    return _env_true("NCM_SKIP_ACTIVATION")


def _remote_mode() -> bool:
    from core.license_client import uses_license_service

    return uses_license_service()


# ---------------------------------------------------------------------------
# Local mode (legacy)
# ---------------------------------------------------------------------------

def _load_local_secrets() -> tuple[bytes, bytes]:
    password_hash: bytes | None = None
    signing_key: bytes | None = None
    try:
        from core import activation_secrets_local as local  # type: ignore

        password_hash = _decode_hex(getattr(local, "PASSWORD_HASH_HEX", "") or "")
        signing_key = _decode_hex(getattr(local, "SIGNING_KEY_HEX", "") or "")
    except ImportError:
        pass
    if not password_hash:
        password_hash = _decode_hex(os.getenv("NCM_ACTIVATION_PASSWORD_HASH") or "")
    if not signing_key:
        signing_key = _decode_hex(os.getenv("NCM_ACTIVATION_SIGNING_KEY") or "")
    if not password_hash or not signing_key:
        raise ActivationRequired(
            "Local activation not configured. Set NCM_LICENSE_SERVER_URL for remote licensing, "
            "or run: python scripts/set_activation_password.py"
        )
    return password_hash, signing_key


def _decode_hex(value: str) -> bytes | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return bytes.fromhex(value)
    except ValueError:
        return None


def _data_root() -> str:
    root = (os.getenv("NCM_DATA_ROOT") or "").strip()
    if root:
        return os.path.abspath(root)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _local_state_path() -> Path:
    return Path(_data_root()) / _STATE_FILENAME


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sign_payload(expiry_unix: int, signing_key: bytes) -> str:
    import base64

    msg = str(expiry_unix).encode("utf-8")
    digest = hmac.new(signing_key, msg, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii")


def _read_local_state() -> dict[str, Any] | None:
    path = _local_state_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _write_local_state(expiry_unix: int, signature: str) -> None:
    path = _local_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "expiry_unix": expiry_unix,
                "signature": signature,
                "activated_at_unix": int(_utc_now().timestamp()),
                "period_days": activation_period_days(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _verify_local_state(password_hash: bytes, signing_key: bytes) -> bool:
    data = _read_local_state()
    if not data:
        return False
    try:
        expiry_unix = int(data["expiry_unix"])
        signature = str(data["signature"])
    except (KeyError, TypeError, ValueError):
        return False
    if expiry_unix <= int(_utc_now().timestamp()):
        return False
    expected = _sign_payload(expiry_unix, signing_key)
    if not hmac.compare_digest(expected, signature):
        return False
    _ = password_hash
    return True


def _local_is_configured() -> bool:
    try:
        _load_local_secrets()
        return True
    except ActivationRequired:
        return False


def _local_is_activated() -> bool:
    try:
        password_hash, signing_key = _load_local_secrets()
    except ActivationRequired:
        return False
    return _verify_local_state(password_hash, signing_key)


def _local_status() -> dict[str, Any]:
    configured = _local_is_configured()
    if not configured:
        return {
            "mode": "local",
            "configured": False,
            "activated": False,
            "expires_at": None,
            "days_remaining": 0,
            "message": "Run scripts/set_activation_password.py or enable NCM_LICENSE_SERVER_URL.",
        }
    data = _read_local_state()
    if not data or not _local_is_activated():
        return {
            "mode": "local",
            "configured": True,
            "activated": False,
            "expires_at": None,
            "days_remaining": 0,
            "message": "Enter your operator password to continue.",
        }
    expiry_unix = int(data["expiry_unix"])
    now_unix = int(_utc_now().timestamp())
    days_remaining = max(0, int((expiry_unix - now_unix) / 86400))
    expires_at = datetime.fromtimestamp(expiry_unix, tz=timezone.utc).isoformat()
    return {
        "mode": "local",
        "configured": True,
        "activated": True,
        "expires_at": expires_at,
        "days_remaining": days_remaining,
        "period_days": activation_period_days(),
    }


def _local_unlock(password: str) -> dict[str, Any]:
    if not _local_verify_password(password):
        raise ActivationRequired("Invalid operator password")
    _, signing_key = _load_local_secrets()
    expiry_unix = int(_utc_now().timestamp()) + activation_period_days() * 86400
    _write_local_state(expiry_unix, _sign_payload(expiry_unix, signing_key))
    return _local_status()


def _local_verify_password(password: str) -> bool:
    if not password:
        return False
    password_hash, _ = _load_local_secrets()
    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        password_hash[:16],
        _PBKDF2_ITERATIONS,
        dklen=32,
    )
    return hmac.compare_digest(candidate, password_hash[16:48])


# ---------------------------------------------------------------------------
# Public API (local or remote)
# ---------------------------------------------------------------------------

def is_configured() -> bool:
    if is_bypass_enabled():
        return True
    if _remote_mode():
        from core.license_client import is_configured as remote_configured

        return remote_configured()
    return _local_is_configured()


def is_activated() -> bool:
    if is_bypass_enabled():
        return True
    if _remote_mode():
        from core.license_client import is_activated as remote_activated

        return remote_activated()
    return _local_is_activated()


def activation_status() -> dict[str, Any]:
    if is_bypass_enabled():
        return {
            "configured": True,
            "activated": True,
            "bypass": True,
            "expires_at": None,
            "days_remaining": None,
        }
    if _remote_mode():
        from core.license_client import activation_status as remote_status

        status = remote_status()
        status["bypass"] = False
        return status
    status = _local_status()
    status["bypass"] = False
    return status


def verify_password(password: str) -> bool:
    if _remote_mode():
        return bool(password)
    return _local_verify_password(password)


def unlock(password: str) -> dict[str, Any]:
    if is_bypass_enabled():
        return activation_status()
    if _remote_mode():
        from core.license_client import LicenseServiceError, unlock as remote_unlock

        try:
            return remote_unlock(password)
        except LicenseServiceError as exc:
            raise ActivationRequired(str(exc)) from exc
    return _local_unlock(password)


def require_activation() -> None:
    if is_activated():
        return
    status = activation_status()
    days = status.get("days_remaining")
    if not is_configured():
        raise ActivationRequired(status.get("message") or "Activation not configured")
    raise ActivationRequired(
        status.get("message") or "Operator activation required",
        days_remaining=days if isinstance(days, int) else 0,
    )


def install_sqlite_gate() -> None:
    global _SQLITE_GATE_INSTALLED
    if _SQLITE_GATE_INSTALLED:
        return

    def gated_connect(database, *args, **kwargs):
        if not is_bypass_enabled() and not is_activated():
            require_activation()
        return _ORIGINAL_SQLITE_CONNECT(database, *args, **kwargs)

    sqlite3.connect = gated_connect  # type: ignore[method-assign, assignment]
    _SQLITE_GATE_INSTALLED = True


def hash_password_for_config(password: str) -> tuple[str, str]:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _PBKDF2_ITERATIONS,
        dklen=32,
    )
    stored = salt + derived
    signing_key = hashlib.sha256(stored + b"ncm-activation-signing-v1").digest()
    return stored.hex(), signing_key.hex()
