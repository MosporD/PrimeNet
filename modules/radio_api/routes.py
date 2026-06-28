from __future__ import annotations

from flask import Blueprint, jsonify

from core.radio.metadata import list_areas
from core.radio.web import admin_required

radio_api_bp = Blueprint("radio_api", __name__)


@radio_api_bp.route("/api/radio/areas")
@admin_required
def radio_areas():
    return jsonify({"success": True, "areas": list_areas()})

