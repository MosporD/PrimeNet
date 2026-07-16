"""Dashboard module version labels keyed by data-module-id / href."""

from __future__ import annotations

from modules.cm_parameter_audit.version import MODULE_VERSION_LABEL as CM_PARAMETER_AUDIT_VERSION

# Bump the label here when a module changes (e.g. "V1.1").
MODULE_VERSIONS: dict[str, str] = {
    "performance": "V1.0",
    "performance-analytics": "V1.0",
    "network-map": "V1.0",
    "neighbor-analysis": "V1.0",
    "reports": "V1.0",
    "cell-heatmap": "V1.0",
    "sector-health": "V1.0",
    "sector-health-all": "V1.0",
    "conflict-map": "V1.0",
    "femto-pm": "V1.0",
    "son-analytics": "V1.0",
    "network-health": "V1.0",
    "parameter-dictionary": "V1.0",
    "performance-dictionary": "V1.0",
    "cm-extractor": "V1.0",
    "cm-parameter-audit": CM_PARAMETER_AUDIT_VERSION,
    "xml-parser": "V1.0",
    "excel-generator": "V1.1",
    "ne-comparison": "V1.0",
    "ret-management": "V1.0",
    "config-task-scheduler": "V1.0",
    "config-history": "V1.0",
    "network-management": "V1.0",
    "ran-features": "V1.0",
    "drive-test-viewer": "V1.0",
    "fault-management": "V1.0",
    "rf-optimization": "V1.0",
    "neighbor-quality": "V1.0",
    "capacity-hotspots": "V1.0",
    "sleeping-cells": "V1.0",
    "layer-coverage": "V1.0",
    "overshooting-detector": "V1.0",
    "change-impact": "V1.0",
    "radio-morning-report": "V1.0",
    "admin-panel": "V1.0",
    "profile": "V1.0",
}

HREF_MODULE_IDS: dict[str, str] = {
    "/performance": "performance",
    "/performance-analytics": "performance-analytics",
    "/network-map": "network-map",
    "/neighbor-analysis": "neighbor-analysis",
    "/reports": "reports",
    "/cell-heatmap": "cell-heatmap",
    "/sector-health": "sector-health",
    "/sector-health-all": "sector-health-all",
    "/conflict-map": "conflict-map",
    "/femto-pm": "femto-pm",
    "/son-analytics": "son-analytics",
    "/network-health": "network-health",
    "/parameter-dictionary": "parameter-dictionary",
    "/performance-dictionary": "performance-dictionary",
    "/cm-extractor": "cm-extractor",
    "/cm-parameter-audit": "cm-parameter-audit",
    "/xml-parser": "xml-parser",
    "/excel-generator": "excel-generator",
    "/ne-comparison": "ne-comparison",
    "/ret-management": "ret-management",
    "/config-task-scheduler": "config-task-scheduler",
    "/config-history": "config-history",
    "/network-management": "network-management",
    "/ran-features": "ran-features",
    "/drive-test-viewer": "drive-test-viewer",
    "/fault-management": "fault-management",
    "/rf-optimization": "rf-optimization",
    "/neighbor-quality": "neighbor-quality",
    "/capacity-hotspots": "capacity-hotspots",
    "/sleeping-cells": "sleeping-cells",
    "/layer-coverage": "layer-coverage",
    "/overshooting-detector": "overshooting-detector",
    "/change-impact": "change-impact",
    "/radio-morning-report": "radio-morning-report",
    "/admin-panel": "admin-panel",
    "/profile": "profile",
}


def normalize_href(href: str) -> str:
    path = (href or "/").split("?")[0].strip() or "/"
    return path.rstrip("/") or "/"


def module_id_for_href(href: str) -> str | None:
    return HREF_MODULE_IDS.get(normalize_href(href))


def version_for_module(module_id: str) -> str | None:
    return MODULE_VERSIONS.get((module_id or "").strip())


def version_for_href(href: str) -> str | None:
    module_id = module_id_for_href(href)
    if not module_id:
        return None
    return version_for_module(module_id)


def nav_label(label: str, href: str) -> str:
    version = version_for_href(href)
    if version:
        return f"{label} {version}"
    return label
