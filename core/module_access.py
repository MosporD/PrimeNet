"""Canonical feature-navigation access rules (mirrors dashboard visibility)."""

from __future__ import annotations

from urllib.parse import urlparse

from core.module_versions import nav_label

# visibility:
#   all          — any authenticated user
#   admin        — owner (admin) only
#   admin_or_noc — admin or NOC SYS (user administration)
NAV_SECTIONS: list[dict] = [
    {
        "title": "Overview & Performance",
        "links": [
            {"label": "Dashboard", "href": "/dashboard", "visibility": "all"},
            {"label": "Performance Explorer", "href": "/performance", "visibility": "all"},
            {"label": "Huawei PM Query Studio", "href": "/performance-analytics", "visibility": "admin"},
            {"label": "Network Coverage Heatmap", "href": "/cell-heatmap", "visibility": "all"},
            {"label": "Network Map", "href": "/network-map", "visibility": "all"},
            {"label": "Neighbor Analysis", "href": "/neighbor-analysis", "visibility": "all"},
            {"label": "Performance Reports", "href": "/reports", "visibility": "all"},
            {"label": "Power BI Reports", "href": "/power-bi", "visibility": "all"},
            {"label": "Sector Health Monitor", "href": "/sector-health", "visibility": "all"},
            {"label": "Sector Health (All Cells)", "href": "/sector-health-all", "visibility": "all"},
            {"label": "Conflict Map", "href": "/conflict-map", "visibility": "all"},
            {"label": "Femto PM", "href": "/femto-pm", "visibility": "all"},
            {"label": "Fault Management", "href": "/fault-management", "visibility": "all"},
        ],
    },
    {
        "title": "Radio Optimization",
        "links": [
            {"label": "SON Optimization Insights", "href": "/son-analytics", "visibility": "admin"},
            {"label": "Network Health Overview", "href": "/network-health", "visibility": "admin"},
            {"label": "RF Optimization Workbench", "href": "/rf-optimization", "visibility": "admin"},
            {"label": "Neighbor Quality Analyzer", "href": "/neighbor-quality", "visibility": "admin"},
            {"label": "Capacity Hotspots", "href": "/capacity-hotspots", "visibility": "admin"},
            {"label": "Sleeping Cell Detector", "href": "/sleeping-cells", "visibility": "admin"},
            {"label": "Layer Coverage Gaps", "href": "/layer-coverage", "visibility": "admin"},
            {"label": "Overshooting Detector", "href": "/overshooting-detector", "visibility": "admin"},
            {"label": "Change Impact Tracker", "href": "/change-impact", "visibility": "admin"},
            {"label": "Radio Morning Report", "href": "/radio-morning-report", "visibility": "admin"},
            {"label": "Nokia Load Balancing", "href": "/nokia-load-balancing", "visibility": "admin"},
            {"label": "Huawei Load Balancing", "href": "/huawei-load-balancing", "visibility": "admin"},
            {"label": "Mobility / HO Explorer", "href": "/mobility-explorer", "visibility": "admin"},
            {"label": "Alarm–PM Correlator", "href": "/alarm-impact", "visibility": "admin"},
            {"label": "Group / Cluster Health", "href": "/group-health", "visibility": "admin"},
            {"label": "IRAT / Vendor Border", "href": "/irat-border", "visibility": "admin"},
            {"label": "PCI Audit", "href": "/pci-audit", "visibility": "admin"},
        ],
    },
    {
        "title": "Configuration",
        "links": [
            {"label": "Parameter Dictionary", "href": "/parameter-dictionary", "visibility": "all"},
            {"label": "Performance Dictionary", "href": "/performance-dictionary", "visibility": "all"},
            {"label": "Configuration Data Extractor", "href": "/cm-extractor", "visibility": "all"},
            {"label": "CM Parameter Audit", "href": "/cm-parameter-audit", "visibility": "all"},
            {"label": "XML Parser", "href": "/xml-parser", "visibility": "all"},
            {"label": "XML Generator", "href": "/excel-generator", "visibility": "all"},
            {"label": "NE Comparison", "href": "/ne-comparison", "visibility": "all"},
            {"label": "RET Management", "href": "/ret-management", "visibility": "all"},
            {"label": "Config Task Scheduler", "href": "/config-task-scheduler", "visibility": "all"},
            {"label": "Config History", "href": "/config-history", "visibility": "all"},
            {"label": "Network Management", "href": "/network-management", "visibility": "all"},
            {"label": "RAN Feature Library", "href": "/ran-features", "visibility": "all"},
            {"label": "Drive Test Viewer", "href": "/drive-test-viewer", "visibility": "all"},
        ],
    },
    {
        "title": "Administration",
        "links": [
            {
                "label": "Admin Panel",
                "href": "/admin-panel?section=user-admin",
                "visibility": "admin_or_noc",
            },
            {"label": "Developer Documentation", "href": "/documentation", "visibility": "admin"},
            {"label": "User Profile", "href": "/profile", "visibility": "all"},
        ],
    },
]


def normalize_href(href: str) -> str:
    path = urlparse((href or "").strip()).path or "/"
    return path.rstrip("/") or "/"


def _role_key(user_or_role) -> str:
    if isinstance(user_or_role, dict):
        return str(user_or_role.get("role") or "").strip().lower()
    return str(user_or_role or "").strip().lower()


def _default_visibility_map() -> dict[str, str]:
    """Normalized href -> hardcoded default visibility, from NAV_SECTIONS."""
    out: dict[str, str] = {}
    for section in NAV_SECTIONS:
        for link in section.get("links") or []:
            out[normalize_href(link.get("href") or "")] = str(link.get("visibility") or "all")
    return out


def default_visibility_for(href: str) -> str:
    return _default_visibility_map().get(normalize_href(href), "all")


def _link_visible(href: str, visibility: str, role: str) -> bool:
    """Config-aware visibility check (admin always visible)."""
    if role == "admin":
        return True
    from core import feature_access

    return feature_access.role_can_access(normalize_href(href), visibility, role)


def feature_catalog(user_or_role=None) -> list[dict]:
    """Flat list of every feature with its configurable access state.

    Used by the admin panel. Each entry: section, label, href, default_visibility,
    locked, and ``roles`` (editable roles currently enabled).
    """
    from core import feature_access

    seen: set[str] = set()
    out: list[dict] = []
    for section in NAV_SECTIONS:
        for link in section.get("links") or []:
            href = normalize_href(link.get("href") or "")
            if href in seen:
                continue
            seen.add(href)
            visibility = str(link.get("visibility") or "all")
            out.append({
                "section": section["title"],
                "label": link["label"],
                "href": href,
                "default_visibility": visibility,
                "locked": href in feature_access.LOCKED_HREFS,
                "roles": sorted(
                    feature_access.effective_roles(href, visibility),
                    key=lambda r: feature_access.ROLE_ORDER.index(r)
                    if r in feature_access.ROLE_ORDER else 99,
                ),
            })
    return out


def feature_for_path(path: str) -> str | None:
    """Longest feature href that matches ``path`` (or its /api-stripped form)."""
    hrefs = list(_default_visibility_map().keys())

    def _match(target: str) -> str | None:
        target = normalize_href(target)
        best: str | None = None
        for href in hrefs:
            if href == "/":
                continue
            if target == href or target.startswith(f"{href}/"):
                if best is None or len(href) > len(best):
                    best = href
        return best

    hit = _match(path)
    if hit is None and (path or "").startswith("/api/"):
        hit = _match("/" + path[len("/api/"):])
    return hit


def path_access(path: str, user_or_role) -> tuple[bool, bool]:
    """Return (allowed, matched) for a request path under the current config.

    ``matched`` is False when no feature owns the path — callers decide whether an
    unmatched path is permitted (login_required: yes; admin_required: no).
    """
    role = _role_key(user_or_role)
    href = feature_for_path(path)
    if href is None:
        return (role == "admin", False)
    if role == "admin":
        return (True, True)
    return (_link_visible(href, default_visibility_for(href), role), True)


def enforce_module_access(href: str, user_or_role):
    """
    Return None when access is allowed, otherwise a Flask response
    (redirect for pages, JSON 403 for API).
    """
    from flask import jsonify, redirect, request, url_for

    if href_allowed_for_role(href, user_or_role):
        return None

    if (request.path or "").startswith("/api/") or request.is_json:
        return jsonify({"success": False, "error": "Access denied."}), 403
    return redirect(url_for("auth.dashboard"))


def module_access_before_request(href: str):
    """Blueprint before_request helper keyed to a module href."""
    from flask import redirect, request, url_for
    from database_enhanced import get_user_by_session

    if request.endpoint and str(request.endpoint).endswith(".static"):
        return None

    token = request.cookies.get("session_token")
    if not token:
        return redirect(url_for("auth.login_page"))
    user = get_user_by_session(token)
    if not user:
        return redirect(url_for("auth.login_page"))
    request.current_user = user
    return enforce_module_access(href, user)


def navigation_sections_for_role(user_or_role) -> list[dict]:
    """Return feature-nav sections filtered for the user's role."""
    role = _role_key(user_or_role)
    sections: list[dict] = []
    for section in NAV_SECTIONS:
        links = [
            {"label": nav_label(link["label"], link["href"]), "href": link["href"]}
            for link in section.get("links") or []
            if _link_visible(link.get("href") or "", str(link.get("visibility") or "all"), role)
        ]
        if links:
            sections.append({"title": section["title"], "links": links})
    return sections


def allowed_hrefs_for_role(user_or_role) -> list[str]:
    hrefs: list[str] = []
    seen: set[str] = set()
    for section in navigation_sections_for_role(user_or_role):
        for link in section.get("links") or []:
            href = normalize_href(link.get("href") or "")
            if href not in seen:
                seen.add(href)
                hrefs.append(href)
    return hrefs


def href_allowed_for_role(href: str, user_or_role) -> bool:
    target = normalize_href(href)
    allowed = allowed_hrefs_for_role(user_or_role)
    if target in allowed:
        return True
    for root in allowed:
        if root != "/" and target.startswith(f"{root}/"):
            return True
    return False
