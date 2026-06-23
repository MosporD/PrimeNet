"""
PrimeNet License Service — run separately from the main application.

Start:
  cd license_service
  python generate_keys.py          # once
  set LICENSE_OPERATOR_PASSWORD=your-secret
  python app.py

PrimeNet clients set:
  NCM_LICENSE_SERVER_URL=http://your-server:5055
  NCM_LICENSE_PUBLIC_KEY_PATH=path/to/public.pem   (copy from license_service/data/public.pem)
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from pathlib import Path

from flask import Flask, jsonify, request

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

from config import (
    API_TOKEN,
    LICENSE_DATA_DIR,
    LICENSE_HOST,
    LICENSE_PERIOD_DAYS,
    LICENSE_PORT,
    OPERATOR_PASSWORD,
    PRIVATE_KEY_PATH,
    PUBLIC_KEY_PATH,
)
from store import LicenseStore
from tokens import generate_key_pair, issue_token, load_private_key, load_public_key, verify_token

app = Flask(__name__)
_store: LicenseStore | None = None


def _store() -> LicenseStore:
    global _store
    if _store is None:
        _store = LicenseStore(LICENSE_DATA_DIR / "licenses.db")
    return _store


def _ensure_keys() -> None:
    if PRIVATE_KEY_PATH.is_file() and PUBLIC_KEY_PATH.is_file():
        return
    generate_key_pair(PRIVATE_KEY_PATH, PUBLIC_KEY_PATH)


def _check_operator_password(password: str) -> bool:
    if not OPERATOR_PASSWORD:
        return False
    return hmac.compare_digest(password, OPERATOR_PASSWORD)


def _admin_auth() -> bool:
    if not API_TOKEN:
        return True
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return hmac.compare_digest(auth[7:].strip(), API_TOKEN)
    return hmac.compare_digest(request.headers.get("X-License-Admin-Token", ""), API_TOKEN)


def _token_id(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "primenet-license"})


@app.route("/v1/public-key", methods=["GET"])
def public_key():
    _ensure_keys()
    pem = PUBLIC_KEY_PATH.read_text(encoding="utf-8")
    return jsonify({"public_key_pem": pem})


@app.route("/v1/unlock", methods=["POST"])
def unlock():
    """
    Body JSON: { "password": "...", "instance_id": "..." }
    Returns a signed license token valid for LICENSE_PERIOD_DAYS.
    """
    if not OPERATOR_PASSWORD:
        return jsonify({"error": "LICENSE_OPERATOR_PASSWORD is not set on the server"}), 503

    _ensure_keys()
    body = request.get_json(silent=True) or {}
    password = (body.get("password") or "").strip()
    instance_id = (body.get("instance_id") or "").strip()
    if not password or not instance_id:
        return jsonify({"error": "password and instance_id are required"}), 400
    if not _check_operator_password(password):
        return jsonify({"error": "Invalid operator password"}), 403

    if _store().is_revoked(instance_id):
        return jsonify({"error": "This installation has been revoked"}), 403

    private_key = load_private_key(PRIVATE_KEY_PATH)
    token, expiry = issue_token(
        private_key=private_key,
        instance_id=instance_id,
        period_days=LICENSE_PERIOD_DAYS,
    )
    _store().record_activation(instance_id, expiry, _token_id(token))
    return jsonify({
        "ok": True,
        "token": token,
        "expires_at": expiry,
        "expires_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(expiry)),
        "period_days": LICENSE_PERIOD_DAYS,
        "instance_id": instance_id,
    })


@app.route("/v1/verify", methods=["POST"])
def verify():
    """
    Body JSON: { "token": "...", "instance_id": "..." (optional) }
    Online revocation check; clients should call periodically.
    """
    _ensure_keys()
    body = request.get_json(silent=True) or {}
    token = (body.get("token") or "").strip()
    instance_id = (body.get("instance_id") or "").strip()
    if not token:
        return jsonify({"error": "token is required"}), 400

    public_key = load_public_key(PUBLIC_KEY_PATH.read_bytes())
    payload = verify_token(token, public_key)
    if not payload:
        return jsonify({"valid": False, "reason": "invalid_or_expired"}), 200

    sub = str(payload.get("sub") or "")
    if instance_id and sub != instance_id:
        return jsonify({"valid": False, "reason": "instance_mismatch"}), 200
    if _store().is_revoked(sub):
        return jsonify({"valid": False, "reason": "revoked"}), 200

    exp = int(payload.get("exp") or 0)
    days_remaining = max(0, int((exp - time.time()) / 86400))
    return jsonify({
        "valid": True,
        "instance_id": sub,
        "expires_at": exp,
        "days_remaining": days_remaining,
    })


@app.route("/v1/admin/revoke", methods=["POST"])
def admin_revoke():
    if not _admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    instance_id = (body.get("instance_id") or "").strip()
    if not instance_id:
        return jsonify({"error": "instance_id is required"}), 400
    _store().revoke(instance_id, reason=(body.get("reason") or ""))
    return jsonify({"ok": True, "instance_id": instance_id, "revoked": True})


@app.route("/v1/admin/unrevoke", methods=["POST"])
def admin_unrevoke():
    if not _admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    instance_id = (body.get("instance_id") or "").strip()
    if not instance_id:
        return jsonify({"error": "instance_id is required"}), 400
    _store().unrevoke(instance_id)
    return jsonify({"ok": True, "instance_id": instance_id, "revoked": False})


if __name__ == "__main__":
    _ensure_keys()
    if not OPERATOR_PASSWORD:
        print("[WARNING] Set LICENSE_OPERATOR_PASSWORD before production use")
    print(f"License service listening on http://{LICENSE_HOST}:{LICENSE_PORT}")
    print(f"Public key: {PUBLIC_KEY_PATH}")
    app.run(host=LICENSE_HOST, port=LICENSE_PORT, debug=False)
