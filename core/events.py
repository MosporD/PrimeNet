"""Outbound platform events → Microsoft Teams incoming webhook.

Posts MessageCard JSON. Includes assigned approver emails from the users table.
Never raises into callers. No n8n / SMTP / WhatsApp clients here.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_SOURCE = "primenet"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def webhook_url() -> str:
    """Prefer Teams-specific URL; fall back to legacy NCM_EVENTS_WEBHOOK_URL."""
    return (
        (os.getenv("NCM_TEAMS_WEBHOOK_URL") or "").strip()
        or (os.getenv("NCM_EVENTS_WEBHOOK_URL") or "").strip()
    )


def events_enabled() -> bool:
    if not _env_bool("NCM_EVENTS_ENABLED", True):
        return False
    return bool(webhook_url())


def _host() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def _events_log_path():
    try:
        from sync_config import DATA_ROOT

        root = DATA_ROOT
    except Exception:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "var", "platform_events.jsonl")


def _persist_event(kind: str, body: dict[str, Any]) -> None:
    try:
        path = _events_log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        line = json.dumps(body, default=str)[:20000]
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as exc:
        logger.debug("platform_events persist skipped: %s", exc)


def _approvers() -> list[dict[str, Any]]:
    try:
        from database_enhanced import list_approver_emails

        return list_approver_emails()
    except Exception as exc:
        logger.debug("approver lookup skipped: %s", exc)
        return []


def _theme_for(kind: str) -> str:
    k = (kind or "").lower()
    if "fail" in k or "stale" in k or "error" in k:
        return "D13438"
    if "detector" in k or "hotspot" in k or "sleeping" in k:
        return "FFB900"
    return "0078D4"


def _teams_card(kind: str, body: dict[str, Any], approvers: list[dict[str, Any]]) -> dict[str, Any]:
    payload = body.get("payload") or {}
    detail = str(payload.get("detail") or payload.get("message") or "")[:1500]
    facts = [
        {"name": "Kind", "value": kind},
        {"name": "Host", "value": str(body.get("host") or "")},
        {"name": "Time (UTC)", "value": str(body.get("ts") or "")},
    ]
    if payload.get("job_key"):
        facts.append({"name": "Job", "value": str(payload.get("job_key"))})
    if payload.get("new_count") is not None:
        facts.append({"name": "New offenders", "value": str(payload.get("new_count"))})
    if payload.get("stale_count") is not None:
        facts.append({"name": "Stale stores", "value": str(payload.get("stale_count"))})

    approver_lines = []
    for a in approvers[:40]:
        label = (a.get("full_name") or a.get("username") or "").strip()
        email = (a.get("email") or "").strip()
        if email:
            approver_lines.append(f"{label} <{email}>" if label else email)

    text_bits = []
    if detail:
        text_bits.append(detail)
    if approver_lines:
        text_bits.append("**Approvers:** " + "; ".join(approver_lines))
    else:
        text_bits.append("_No users flagged can_approve yet — assign Approver in Platform Admin._")

    return {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": f"PrimeNet: {kind}",
        "themeColor": _theme_for(kind),
        "title": f"PrimeNet — {kind}",
        "sections": [
            {
                "activityTitle": "PrimeNet alert",
                "facts": facts,
                "text": "\n\n".join(text_bits),
            }
        ],
    }


def emit(kind: str, payload: dict | None = None, *, source: str = _SOURCE) -> None:
    """POST a Teams MessageCard. No-op if webhook unset. Never raises."""
    try:
        kind_s = str(kind or "").strip()
        if not kind_s:
            return
        approvers = _approvers()
        body = {
            "kind": kind_s,
            "ts": datetime.now(timezone.utc).isoformat(),
            "host": _host(),
            "source": source or _SOURCE,
            "payload": dict(payload or {}),
            "approvers": [
                {"email": a.get("email"), "username": a.get("username"), "full_name": a.get("full_name")}
                for a in approvers
            ],
        }
        _persist_event(kind_s, body)
        if not events_enabled():
            return
        url = webhook_url()
        if not url:
            return
        card = _teams_card(kind_s, body, approvers)
        data = json.dumps(card, default=str).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": "PrimeNet-events-teams/1",
            },
        )
        timeout = float(os.getenv("NCM_EVENTS_TIMEOUT_SEC") or "8")
        with urllib.request.urlopen(req, timeout=max(2.0, timeout)) as resp:
            resp.read(256)
    except urllib.error.HTTPError as exc:
        logger.warning("Teams emit HTTP %s for kind=%s", getattr(exc, "code", "?"), kind)
    except Exception as exc:
        logger.warning("Teams emit failed kind=%s: %s", kind, exc)
