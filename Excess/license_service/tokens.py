"""RSA-signed license tokens (PrimeNet clients verify with public key only)."""

from __future__ import annotations

import base64
import json
import time
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.backends import default_backend


def generate_key_pair(private_path, public_path) -> None:
    private_path.parent.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    priv_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    private_path.write_bytes(priv_pem)
    public_path.write_bytes(pub_pem)


def load_private_key(path) -> Any:
    data = path.read_bytes()
    return serialization.load_pem_private_key(data, password=None, backend=default_backend())


def load_public_key(pem: bytes | str) -> Any:
    if isinstance(pem, str):
        pem = pem.encode("utf-8")
    return serialization.load_pem_public_key(pem, backend=default_backend())


def issue_token(
    *,
    private_key,
    instance_id: str,
    period_days: int,
    issuer: str = "primenet-license",
) -> tuple[str, int]:
    now = int(time.time())
    expiry = now + period_days * 86400
    payload = {
        "iss": issuer,
        "sub": instance_id,
        "iat": now,
        "exp": expiry,
        "ver": 1,
    }
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = private_key.sign(
        payload_b64.encode("ascii"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    sig_b64 = _b64url_encode(sig)
    token = f"{payload_b64}.{sig_b64}"
    return token, expiry


def verify_token(token: str, public_key) -> dict[str, Any] | None:
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
    exp = int(payload.get("exp") or 0)
    if exp <= int(time.time()):
        return None
    return payload


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)
