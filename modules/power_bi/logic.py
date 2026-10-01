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


def save_catalog(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Persist catalog to disk after normalizing each entry."""
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(reports or []):
        report = _normalize_report(raw, index)
        if not report or report["slug"] in seen:
            continue
        seen.add(report["slug"])
        normalized.append(report)
    normalized.sort(key=lambda item: item["title"].casefold())
    os.makedirs(os.path.dirname(CATALOG_PATH), exist_ok=True)
    tmp_path = CATALOG_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(normalized, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp_path, CATALOG_PATH)
    return normalized


def _slugify_title(title: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").strip().lower()).strip("-")
    return slug or "report"


def add_report(
    *,
    title: str,
    url: str,
    description: str = "",
    slug: str | None = None,
    visibility: str = VISIBILITY_ALL,
) -> dict[str, Any]:
    """Add or replace a Power BI gallery card. Raises ValueError on validation failure."""
    catalog = load_catalog()
    desired_slug = (slug or "").strip().lower() or _slugify_title(title)
    # Ensure uniqueness when adding a new slug that collides with another title.
    existing_slugs = {r["slug"] for r in catalog}
    if desired_slug in existing_slugs and not slug:
        base = desired_slug
        n = 2
        while f"{base}-{n}" in existing_slugs:
            n += 1
        desired_slug = f"{base}-{n}"

    candidate = {
        "slug": desired_slug,
        "title": title,
        "url": url,
        "description": description,
        "visibility": visibility or VISIBILITY_ALL,
    }
    report = _normalize_report(candidate, len(catalog))
    if not report:
        raise ValueError(
            "Invalid report: need title, description optional, and a Power BI URL "
            f"starting with {ALLOWED_URL_PREFIXES[0]}"
        )

    # Replace same slug if present; otherwise append.
    next_catalog = [r for r in catalog if r["slug"] != report["slug"]]
    next_catalog.append(report)
    save_catalog(next_catalog)
    return report


def remove_report(slug: str) -> bool:
    """Remove a report by slug. Returns True if something was removed."""
    key = str(slug or "").strip().lower()
    if not key:
        return False
    catalog = load_catalog()
    next_catalog = [r for r in catalog if r["slug"] != key]
    if len(next_catalog) == len(catalog):
        return False
    save_catalog(next_catalog)
    return True


def reports_for_role(user_or_role) -> list[dict[str, Any]]:
    role = _role_key(user_or_role)
    return [
        report
        for report in load_catalog()
        if _report_visible(report.get("visibility"), role)
    ]
