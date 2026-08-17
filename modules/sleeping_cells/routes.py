from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from core.radio.scoring import filter_rows, summarize
from core.radio.web import admin_required, attach_feature_guard, format_user, get_current_user, json_error, query_filters

from .logic import (
    DEFAULT_BASELINE_DAYS,
    DEFAULT_MIN_BASELINE,
    DEFAULT_RECENT_DAYS,
    detect_sleeping_cells,
)

sleeping_cells_bp = Blueprint("sleeping_cells", __name__)
attach_feature_guard(sleeping_cells_bp, "/sleeping-cells")


@sleeping_cells_bp.route("/sleeping-cells")
@admin_required
def sleeping_cells_page():
    return render_template(
        "radio_module.html",
        user=format_user(get_current_user()),
        module_title="Sleeping Cell Detector",
        module_subtitle=(
            "Cells that are Active in CM but stopped carrying traffic vs their own "
            "daily baseline — likely silent outages."
        ),
        module_kind="sleeping-cells",
        api_url="/api/sleeping-cells/issues",
        default_technology="all",
    )


def _float_arg(name: str, default: float) -> float:
    try:
        return float(request.args.get(name, default))
    except (TypeError, ValueError):
        return default


def _int_arg(name: str, default: int) -> int:
    try:
        return int(request.args.get(name, default))
    except (TypeError, ValueError):
        return default


@sleeping_cells_bp.route("/api/sleeping-cells/issues")
@admin_required
def sleeping_cells_issues():
    f = query_filters()
    try:
        payload = detect_sleeping_cells(
            vendor=f["vendor"],
            technology=f["technology"],
            limit=f["limit"],
            recent_days=_int_arg("recent_days", DEFAULT_RECENT_DAYS),
            baseline_days=_int_arg("baseline_days", DEFAULT_BASELINE_DAYS),
            min_baseline=_float_arg("min_baseline", DEFAULT_MIN_BASELINE),
        )
        rows = filter_rows(
            payload.get("issues") or [],
            area=f["area"],
            severity=f["severity"],
            search=f["search"],
        )
        return jsonify({"success": True, **payload, "summary": summarize(rows), "issues": rows})
    except Exception as exc:
        return json_error(exc)
