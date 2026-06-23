"""Verify RSA license tokens issued by license_service (public key only)."""

from __future__ import annotations

import base64
import json
import time
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend


def load_public_key_from_pem(pem: bytes | str) -> Any:
    if isinstance(pem, str):
        pem = pem.encode("utf-8")
    return serialization.load_pem_public_key(pem, backend=default_backend())


def verify_license_token(token: str, public_key) -> dict[str, Any] | None:
    try:
        payload_b64, sig_b64 = token.split(".", 1)
    except ValueError:
        return None
    try:
        public_key.verify(
            _b64url_decode(sig_b64),
            payload_b64.encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except Exception:
        return None
    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if int(payload.get("exp") or 0) <= int(time.time()):
        return None
    return payload


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)
