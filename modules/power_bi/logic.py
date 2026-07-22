"""Power BI report catalog — link-out gallery (interim until embed capacity)."""

from __future__ import annotations

import json
import os
from typing import Any

from sync_config import PROJECT_ROOT

CATALOG_PATH = os.path.join(PROJECT_ROOT, "modules", "power_bi", "catalog.json")
ALLOWED_URL_PREFIXES = (
    "https://app.powerbi.com/",
    "https://msit.powerbi.com/",
)

VISIBILITY_ALL = "all"
VISIBILITY_ADMIN = "admin"
VISIBILITY_ADMIN_OR_NOC = "admin_or_noc"


def _role_key(user_or_role) -> str:
    if isinstance(user_or_role, dict):
        return str(user_or_role.get("role") or "").strip().lower()
    return str(user_or_role or "").strip().lower()


def _report_visible(visibility: str, role: str) -> bool:
    vis = (visibility or VISIBILITY_ALL).strip().lower()
    if vis == VISIBILITY_ADMIN:
        return role == "admin"
    if vis == VISIBILITY_ADMIN_OR_NOC:
        return role in {"admin", "noc_sys"}
    return True


def _normalize_report(raw: dict[str, Any], index: int) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None

    title = str(raw.get("title") or "").strip()
    url = str(raw.get("url") or "").strip()
    slug = str(raw.get("slug") or "").strip().lower()
    if not title or not url:
        return None
    if not any(url.startswith(prefix) for prefix in ALLOWED_URL_PREFIXES):
        return None
    if not slug:
        slug = f"report-{index + 1}"

    description = str(raw.get("description") or "").strip()
    visibility = str(raw.get("visibility") or VISIBILITY_ALL).strip().lower()
    if visibility not in {VISIBILITY_ALL, VISIBILITY_ADMIN, VISIBILITY_ADMIN_OR_NOC}:
        visibility = VISIBILITY_ALL

    return {
        "slug": slug,
        "title": title,
        "url": url,
        "description": description,
        "visibility": visibility,
    }


def load_catalog() -> list[dict[str, Any]]:
    if not os.path.isfile(CATALOG_PATH):
        return []
    try:
        with open(CATALOG_PATH, encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(payload, list):
        return []

    reports: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()
    for index, raw in enumerate(payload):
        report = _normalize_report(raw, index)
        if not report or report["slug"] in seen_slugs:
            continue
        seen_slugs.add(report["slug"])
        reports.append(report)

    reports.sort(key=lambda item: item["title"].casefold())
    return reports


def reports_for_role(user_or_role) -> list[dict[str, Any]]:
    role = _role_key(user_or_role)
    return [
        report
        for report in load_catalog()
        if _report_visible(report.get("visibility"), role)
    ]
