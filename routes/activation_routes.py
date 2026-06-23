"""
Operator activation (separate from user login).
"""

from flask import Blueprint, jsonify, render_template, request

from core.activation_gate import (
    ActivationRequired,
    activation_period_days,
    activation_status,
    is_activated,
    unlock,
)

activation_bp = Blueprint("activation", __name__)


@activation_bp.route("/activation")
def activation_page():
    status = activation_status()
    if status.get("activated"):
        from flask import redirect, url_for

        return redirect("/dashboard")
    return render_template(
        "activation.html",
        period_days=status.get("period_days") or activation_period_days(),
        configured=bool(status.get("configured")),
        mode=status.get("mode") or "local",
        server_url=status.get("server_url") or "",
        instance_id=status.get("instance_id") or "",
    )


@activation_bp.route("/api/activation/status", methods=["GET"])
def api_activation_status():
    return jsonify(activation_status())


@activation_bp.route("/api/activation/unlock", methods=["POST"])
def api_activation_unlock():
    if request.is_json:
        payload = request.get_json(silent=True) or {}
    else:
        payload = request.form or {}
    password = (payload.get("password") or "").strip()
    if not password:
        return jsonify({"error": "Password is required"}), 400
    try:
        status = unlock(password)
        try:
            from deploy.bootstrap import run_app_bootstrap_if_enabled

            run_app_bootstrap_if_enabled()
        except Exception:
            pass
        return jsonify({"ok": True, **status})
    except ActivationRequired as exc:
        return jsonify({"error": str(exc)}), 403
