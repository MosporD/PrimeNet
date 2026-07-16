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


def _link_visible(visibility: str, role: str) -> bool:
    if visibility == "admin":
        return role == "admin"
    if visibility == "admin_or_noc":
        return role in {"admin", "noc_sys"}
    return True


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
            if _link_visible(str(link.get("visibility") or "all"), role)
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
