"""Audit trail screen."""

from __future__ import annotations

from flask import request

from .. import audit, config
from ..access import require_permission
from .blueprint import marketing_bp, render


@marketing_bp.route("/audit")
@require_permission(config.P_AUDIT_VIEW)
def audit_trail():
    entity_type = (request.args.get("entity_type") or "").strip() or None
    entity_id = (request.args.get("entity_id") or "").strip() or None
    return render(
        "marketing/audit.html",
        active="audit",
        events=audit.recent(200, entity_type=entity_type, entity_id=entity_id),
        entity_type=entity_type or "",
        entity_id=entity_id or "",
    )
