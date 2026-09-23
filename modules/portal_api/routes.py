"""HTTP routes for portal consumers (Bearer token)."""

from __future__ import annotations

import hmac
import os
from functools import wraps

from flask import Blueprint, jsonify, request

from . import network

portal_api_bp = Blueprint("portal_api", __name__)


def _configured_token() -> str:
    return (
        os.getenv("NEXUS_PORTAL_API_TOKEN")
        or os.getenv("NEXUS_PRIMENET_API_TOKEN")
        or ""
    ).strip()


def require_portal_bearer(view):
    """Require ``Authorization: Bearer <token>`` matching the configured portal token."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        expected = _configured_token()
        if not expected:
            return jsonify(
                {
                    "success": False,
                    "error": "Portal API token is not configured on PrimeNet "
                    "(set NEXUS_PORTAL_API_TOKEN).",
                }
            ), 503
        auth = (request.headers.get("Authorization") or "").strip()
        if not auth.lower().startswith("bearer "):
            return jsonify({"success": False, "error": "Bearer token required"}), 401
        provided = auth[7:].strip()
        if not provided or not hmac.compare_digest(provided, expected):
            return jsonify({"success": False, "error": "Invalid portal API token"}), 401
        return view(*args, **kwargs)

    return wrapped


@portal_api_bp.route("/api/portal/health")
@require_portal_bearer
def portal_health():
    return jsonify({"success": True, "service": "primenet-portal-api", "ok": True})


@portal_api_bp.route("/api/portal/network-footprint")
@require_portal_bearer
def network_footprint():
    area = (request.args.get("area") or "").strip() or None
    try:
        limit = int(request.args.get("congested_limit") or 50)
    except (TypeError, ValueError):
        limit = 50
    try:
        payload = network.footprint_bundle(area=area, congested_limit=limit)
        return jsonify({"success": True, **payload})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@portal_api_bp.route("/api/portal/network-footprint/technologies")
@require_portal_bearer
def network_technologies():
    area = (request.args.get("area") or "").strip() or None
    try:
        return jsonify({"success": True, **network.technology_footprint(area=area)})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@portal_api_bp.route("/api/portal/network-footprint/congested")
@require_portal_bearer
def network_congested():
    try:
        limit = int(request.args.get("limit") or 100)
    except (TypeError, ValueError):
        limit = 100
    try:
        return jsonify(
            {
                "success": True,
                **network.congested_sites(
                    vendor=(request.args.get("vendor") or "all").strip(),
                    technology=(request.args.get("technology") or "all").strip(),
                    area=(request.args.get("area") or "").strip(),
                    limit=limit,
                ),
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@portal_api_bp.route("/api/portal/network-footprint/serviceability")
@require_portal_bearer
def network_serviceability():
    try:
        limit = int(request.args.get("limit") or 200)
    except (TypeError, ValueError):
        limit = 200
    try:
        return jsonify(
            {
                "success": True,
                **network.serviceability(
                    area=(request.args.get("area") or "").strip(),
                    limit=limit,
                ),
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500
