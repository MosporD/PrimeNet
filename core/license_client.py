"""
Remote license service client for PrimeNet.

Configure via environment:
  NCM_LICENSE_SERVER_URL=http://host:5055
  NCM_LICENSE_PUBLIC_KEY_PATH=/path/to/public.pem
  NCM_LICENSE_PUBLIC_KEY_PEM=<inline PEM>   (alternative)
  NCM_LICENSE_INSTANCE_ID=<optional stable id>
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.license_tokens import load_public_key_from_pem, verify_license_token

_STATE_FILENAME = ".ncm_license_state"
def _activation_period_days() -> int:
    from core.activation_gate import activation_period_days

    return activation_period_days()


class LicenseServiceError(Exception):
    pass


def license_server_url() -> str:
    return (os.getenv("NCM_LICENSE_SERVER_URL") or "").strip().rstrip("/")


def uses_license_service() -> bool:
    return bool(license_server_url())


def _data_root() -> str:
    root = (os.getenv("NCM_DATA_ROOT") or "").strip()
    if root:
        return os.path.abspath(root)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _state_path() -> Path:
    return Path(_data_root()) / _STATE_FILENAME


def get_instance_id() -> str:
    explicit = (os.getenv("NCM_LICENSE_INSTANCE_ID") or "").strip()
    if explicit:
        return explicit
    host = socket.gethostname()
    try:
        node = platform.node() or host
    except Exception:
        node = host
    seed = f"{node}|{host}|{platform.system()}|{platform.machine()}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"{host}-{digest}"


def _load_public_key_pem() -> bytes:
    inline = (os.getenv("NCM_LICENSE_PUBLIC_KEY_PEM") or "").strip()
    if inline:
        return inline.replace("\\n", "\n").encode("utf-8")
    path = (os.getenv("NCM_LICENSE_PUBLIC_KEY_PATH") or "").strip()
    if path and Path(path).is_file():
        return Path(path).read_bytes()
    local = Path(__file__).resolve().parent / "license_public.pem"
    if local.is_file():
        return local.read_bytes()
    raise LicenseServiceError(
        "License public key not configured. Set NCM_LICENSE_PUBLIC_KEY_PATH "
        "or deploy core/license_public.pem from the license server."
    )


def _read_state() -> dict[str, Any] | None:
    path = _state_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _write_state(data: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _http_json(method: str, path: str, body: dict | None = None, timeout: float = 15.0) -> dict:
    url = f"{license_server_url()}{path}"
    payload = None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            msg = parsed.get("error") or detail
        except json.JSONDecodeError:
            msg = detail or str(exc)
        raise LicenseServiceError(msg) from exc
    except urllib.error.URLError as exc:
        raise LicenseServiceError(f"Cannot reach license server: {exc}") from exc


def _verify_token_locally(token: str) -> dict[str, Any] | None:
    public_key = load_public_key_from_pem(_load_public_key_pem())
    payload = verify_license_token(token, public_key)
    if not payload:
        return None
    instance_id = get_instance_id()
    if str(payload.get("sub") or "") != instance_id:
        return None
    return payload


def _online_verify_hours() -> int:
    raw = (os.getenv("NCM_LICENSE_ONLINE_VERIFY_HOURS") or "24").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 24


def _offline_grace_hours() -> int:
    raw = (os.getenv("NCM_LICENSE_OFFLINE_GRACE_HOURS") or "72").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 72


def _needs_online_verify(state: dict[str, Any]) -> bool:
    last = int(state.get("last_online_verify_unix") or 0)
    return (int(time.time()) - last) > _online_verify_hours() * 3600


def _online_verify(token: str) -> bool:
    data = _http_json(
        "POST",
        "/v1/verify",
        {"token": token, "instance_id": get_instance_id()},
    )
    return bool(data.get("valid"))


def is_configured() -> bool:
    if not uses_license_service():
        return False
    try:
        _load_public_key_pem()
        return True
    except LicenseServiceError:
        return False


def is_activated() -> bool:
    state = _read_state()
    if not state:
        return False
    token = (state.get("token") or "").strip()
    if not token:
        return False
    payload = _verify_token_locally(token)
    if not payload:
        return False

    if not _needs_online_verify(state):
        return True

    grace_deadline = int(state.get("last_online_verify_unix") or state.get("issued_at_unix") or 0)
    grace_deadline += _offline_grace_hours() * 3600
    try:
        if _online_verify(token):
            state["last_online_verify_unix"] = int(time.time())
            _write_state(state)
            return True
    except LicenseServiceError:
        if int(time.time()) <= grace_deadline:
            return True
        return False
    return False


def activation_status() -> dict[str, Any]:
    if not uses_license_service():
        return {"mode": "local", "configured": False, "activated": False}
    if not is_configured():
        return {
            "mode": "remote",
            "configured": False,
            "activated": False,
            "server_url": license_server_url(),
            "instance_id": get_instance_id(),
            "message": "Deploy the license server public key (NCM_LICENSE_PUBLIC_KEY_PATH).",
        }
    state = _read_state()
    activated = is_activated()
    if not activated:
        return {
            "mode": "remote",
            "configured": True,
            "activated": False,
            "server_url": license_server_url(),
            "instance_id": get_instance_id(),
            "message": "Enter your monthly operator password to contact the license server.",
        }
    payload = _verify_token_locally((state or {}).get("token") or "")
    exp = int((payload or {}).get("exp") or 0)
    days_remaining = max(0, int((exp - time.time()) / 86400))
    expires_at = datetime.fromtimestamp(exp, tz=timezone.utc).isoformat()
    return {
        "mode": "remote",
        "configured": True,
        "activated": True,
        "server_url": license_server_url(),
        "instance_id": get_instance_id(),
        "expires_at": expires_at,
        "days_remaining": days_remaining,
        "period_days": _activation_period_days(),
    }


def unlock(password: str) -> dict[str, Any]:
    instance_id = get_instance_id()
    data = _http_json(
        "POST",
        "/v1/unlock",
        {"password": password, "instance_id": instance_id},
    )
    token = (data.get("token") or "").strip()
    if not token:
        raise LicenseServiceError("License server did not return a token")
    if not _verify_token_locally(token):
        raise LicenseServiceError("License token from server failed local verification")
    _write_state({
        "token": token,
        "instance_id": instance_id,
        "issued_at_unix": int(time.time()),
        "last_online_verify_unix": int(time.time()),
        "server_url": license_server_url(),
    })
    return activation_status()
