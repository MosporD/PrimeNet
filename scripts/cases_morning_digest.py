#!/usr/bin/env python3
"""Post Morning Cases digest to Teams/Slack webhook.

Env:
  CASES_DIGEST_WEBHOOK_URL  — Incoming webhook URL (required to post)
  CASES_DIGEST_MIN_SEVERITY — Critical|High (default High → Critical+High)
  CASES_DIGEST_DRY_RUN=1    — print payload, do not POST

Usage:
  python scripts/cases_morning_digest.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = val.strip().strip('"').strip("'")


def build_payload(cases: list[dict], *, base_url: str = "") -> dict:
    base = (base_url or os.environ.get("CASES_DIGEST_BASE_URL") or "").rstrip("/")
    lines = []
    for c in cases[:25]:
        link = f"{base}/optimization-cases?case={c.get('case_id')}" if base else f"/optimization-cases?case={c.get('case_id')}"
        lines.append(
            f"• [{c.get('severity')}] impact={c.get('impact_score')} — {c.get('title')} ({link})"
        )
    text = (
        f"PrimeNet Cases digest: {len(cases)} open Critical/High case(s)\n"
        + ("\n".join(lines) if lines else "(none)")
    )
    # Slack/Teams-compatible simple payload
    return {"text": text}


def main() -> int:
    _load_dotenv()
    from core.cases.schema import init_schema
    from core.cases import store

    init_schema()
    rows = store.list_cases(limit=200)
    openish = {"open", "assigned", "proposed", "approved", "executed", "verifying"}
    wanted = {"critical", "high"}
    cases = [
        c
        for c in rows
        if str(c.get("state") or "").lower() in openish
        and str(c.get("severity") or "").lower() in wanted
    ]
    cases.sort(key=lambda c: float(c.get("impact_score") or 0), reverse=True)

    payload = build_payload(cases)
    webhook = (os.environ.get("CASES_DIGEST_WEBHOOK_URL") or "").strip()
    dry = os.environ.get("CASES_DIGEST_DRY_RUN", "").strip() in ("1", "true", "yes")

    print(json.dumps({"count": len(cases), "dry_run": dry or not webhook, "preview": payload}, indent=2))

    if dry or not webhook:
        if not webhook:
            print("No CASES_DIGEST_WEBHOOK_URL set — dry run only.", file=sys.stderr)
        return 0

    req = urllib.request.Request(
        webhook,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"Posted status={resp.status}")
    except urllib.error.URLError as exc:
        print(f"Webhook failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
