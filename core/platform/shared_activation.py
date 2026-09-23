"""Shared operator activation for local multi-platform testing.

Today every process checks the same ``core.activation_gate`` state. Unlock once
(on PrimeNet ``/activation``) and NexusCore / NexPulse unlock with it.

Later: per-platform activation keys — replace this hook with platform-scoped
state without changing the before_request shape.
"""

from __future__ import annotations

import os

from flask import Flask, jsonify, redirect, request


def _env_true(key: str, default: bool = False) -> bool:
    raw = (os.getenv(key) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def activation_unlock_url() -> str:
    """Where operators unlock for the shared (test) activation."""
    base = (
        os.getenv("PRIMENET_PUBLIC_URL")
        or os.getenv("NEXUSCORE_PUBLIC_URL")
        or "http://localhost:8001"
    ).rstrip("/")
    return f"{base}/activation"


def install_shared_activation(
    app: Flask,
    *,
    service_name: str,
    local_unlock: bool = False,
) -> None:
    """Block the app until the shared activation gate is unlocked.

    Skip with ``NCM_SKIP_ACTIVATION=1`` or ``NCM_SHARED_ACTIVATION=0``.

    ``local_unlock=True`` only when this process hosts ``/activation``
    (PrimeNet). Other platforms redirect to ``PRIMENET_PUBLIC_URL/activation``.
    """
    if _env_true("NCM_SKIP_ACTIVATION"):
        return
    # Explicit opt-out for a platform process during the transition.
    if (os.getenv("NCM_SHARED_ACTIVATION") or "1").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return

    from core.activation_gate import activation_status, install_sqlite_gate, is_activated

    install_sqlite_gate()

    allowed_prefixes = (
        "/static/",
        "/favicon",
        "/health",
        "/api/health",
        "/robots.txt",
    )
    allowed_exact = {
        "/activation",
        "/api/activation/status",
        "/api/activation/unlock",
        "/health",
        "/api/health",
        "/health/live",
        "/api/health/live",
        "/robots.txt",
    }

    @app.before_request
    def enforce_shared_operator_activation():
        path = request.path or "/"
        if path in allowed_exact or any(path.startswith(p) for p in allowed_prefixes):
            return None
        if is_activated():
            return None
        status = activation_status()
        unlock = activation_unlock_url()
        if path.startswith("/api/"):
            return jsonify(
                {
                    "error": status.get("message") or "Operator activation required",
                    "activation_required": True,
                    "activation": status,
                    "unlock_url": unlock,
                    "service": service_name,
                }
            ), 403
        if local_unlock:
            return redirect("/activation")
        return redirect(unlock)
