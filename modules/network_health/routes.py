"""Network Health Scorecard routes (development stage)."""

from __future__ import annotations

from functools import wraps

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from database_enhanced import get_user_by_session
from modules.son_analytics.area_helpers import list_areas, normalize_area

from . import config as cfg
from .logic import (
    get_cell_trend_payload,
    get_clusters,
    get_health_payload,
    get_kpi_cells,
    get_precomputed_table,
    get_worst_cells,
    list_kpi_columns,
    resolve_precompute_kpis,
)
from .precalc_job import build_all, build_vendor_rat

network_health_bp = Blueprint(
    "network_health",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/network-health/static",
)


@network_health_bp.before_request
def _guard_network_health_access():
    from core.module_access import module_access_before_request
    return module_access_before_request("/network-health")

_VALID_RATS = {r["key"] for r in cfg.RAT_OPTIONS}
_VALID_VENDORS = {v["key"] for v in cfg.VENDOR_OPTIONS}


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get("session_token")
        if not token:
            return redirect(url_for("auth.login_page"))
        user = get_user_by_session(token)
        if not user:
            return redirect(url_for("auth.login_page"))
        request.current_user = user
        return f(*args, **kwargs)

    return decorated


def get_current_user():
    token = request.cookies.get("session_token")
    return get_user_by_session(token) if token else None


def format_user(user):
    if not user:
        return None
    return {"id": user.get("id"), "username": user.get("username"), "role": user.get("role")}


def _normalize_vendor(value: str) -> str:
    v = str(value or cfg.DEFAULT_VENDOR).strip().lower()
    return v if v in _VALID_VENDORS else cfg.DEFAULT_VENDOR


def _normalize_rat(value: str) -> str:
    r = str(value or cfg.DEFAULT_RAT).strip()
    return r if r in _VALID_RATS else cfg.DEFAULT_RAT


@network_health_bp.route("/network-health")
@login_required
def network_health_select():
    user = get_current_user()
    return render_template(
        "network_health_select.html",
        user=format_user(user),
        rats=cfg.RAT_OPTIONS,
        vendors=cfg.VENDOR_OPTIONS,
        default_rat=cfg.DEFAULT_RAT,
        default_vendor=cfg.DEFAULT_VENDOR,
    )


@network_health_bp.route("/network-health/view")
@login_required
def network_health_view():
    user = get_current_user()
    vendor = _normalize_vendor(request.args.get("vendor"))
    rat = _normalize_rat(request.args.get("rat") or request.args.get("technology"))
    rat_cfg = cfg.rat_config(rat) or {}
    vendor_cfg = next((v for v in cfg.VENDOR_OPTIONS if v["key"] == vendor), {})
    return render_template(
        "network_health.html",
        user=format_user(user),
        vendor=vendor,
        vendor_label=vendor_cfg.get("label", vendor.title()),
        rat=rat,
        rat_label=rat_cfg.get("label", rat),
        vendors=cfg.VENDOR_OPTIONS,
        rats=cfg.RAT_OPTIONS,
    )


@network_health_bp.route("/api/network-health/kpis")
@login_required
def network_health_kpis():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    vendor = _normalize_vendor(request.args.get("vendor"))
    rat = _normalize_rat(request.args.get("rat") or request.args.get("technology"))
    try:
        columns = list_kpi_columns(vendor, rat)
        from .precalc_store import get_build_meta

        build = get_build_meta(vendor, rat)
        precomputed = (
            list(build.get("precomputed_kpis") or [])
            if build and int(build.get("row_count") or 0) > 0
            else resolve_precompute_kpis(columns)
        )
        return jsonify({
            "success": True,
            "vendor": vendor,
            "rat": rat,
            "pm_technology": cfg.pm_technology_for_rat(rat),
            "metadata_technology": cfg.metadata_technology_for_rat(rat),
            "benchmark": "daily_vs_7day_avg",
            "benchmark_days": cfg.WOW_LOOKBACK_DAYS,
            "columns": columns,
            "count": len(columns),
            "precomputed_kpis": precomputed,
            "precompute_max": cfg.PRECOMPUTE_KPI_MAX,
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@network_health_bp.route("/api/network-health/areas")
@login_required
def network_health_areas():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"success": True, "areas": list_areas()})


@network_health_bp.route("/api/network-health/clusters")
@login_required
def network_health_clusters():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    area = normalize_area(request.args.get("area"))
    return jsonify({"success": True, "clusters": get_clusters(area)})


@network_health_bp.route("/api/network-health/table")
@login_required
def network_health_table():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    vendor = _normalize_vendor(request.args.get("vendor"))
    rat = _normalize_rat(request.args.get("rat") or request.args.get("technology"))
    kpi = request.args.get("kpi", "").strip() or None
    try:
        payload = get_precomputed_table(vendor, rat, kpi=kpi, slim=True)
        return jsonify({
            "success": True,
            "vendor": vendor,
            "rat": rat,
            "kpi": kpi,
            "pm_technology": cfg.pm_technology_for_rat(rat),
            "benchmark": "daily_vs_7day_avg",
            "benchmark_days": cfg.WOW_LOOKBACK_DAYS,
            "benchmark_note": "pre=7-day avg (excl. latest), post=latest daily, delta=post-pre",
            "kpi_count": len(payload.get("precomputed_kpis") or []),
            "total_kpi_count": payload.get("total_kpi_count", 0),
            "precomputed_kpis": payload.get("precomputed_kpis") or [],
            "tables": payload.get("tables") or {},
            "precalc_ready": payload.get("precalc_ready", False),
            "precalc_empty": payload.get("precalc_empty", False),
            "precalc_stale": payload.get("precalc_stale", False),
            "precalc_built_at": payload.get("precalc_built_at"),
            "precalc_row_count": payload.get("precalc_row_count"),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@network_health_bp.route("/api/network-health/cells")
@login_required
def network_health_cells():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    vendor = _normalize_vendor(request.args.get("vendor"))
    rat = _normalize_rat(request.args.get("rat") or request.args.get("technology"))
    kpi = request.args.get("kpi", "").strip()
    if not kpi:
        return jsonify({"success": False, "error": "kpi is required"}), 400
    area = normalize_area(request.args.get("area"))
    cluster_raw = request.args.get("cluster", "").strip()
    cluster = int(cluster_raw) if cluster_raw.isdigit() else None
    sort_mode = request.args.get("sort", "").strip()
    all_cells = request.args.get("all", "").strip().lower() in ("1", "true", "yes")
    if all_cells:
        top_n = 500_000
    else:
        top_n = min(500_000, max(10, int(request.args.get("top_n", 50_000))))
    try:
        rows = get_kpi_cells(
            kpi,
            vendor=vendor,
            rat=rat,
            area=area,
            cluster=cluster,
            sort_mode=sort_mode or None,
            top_n=top_n,
        )
        return jsonify({
            "success": True,
            "stage": "development",
            "pm_data_scope": "daily",
            "benchmark": "daily_vs_7day_avg",
            "benchmark_days": cfg.WOW_LOOKBACK_DAYS,
            "kpi": kpi,
            "kpi_label": kpi,
            "vendor": vendor,
            "rat": rat,
            "area": area or "all",
            "cluster": cluster,
            "cells": rows,
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@network_health_bp.route("/api/network-health/cell-trend")
@login_required
def network_health_cell_trend():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    cell_name = request.args.get("cell_name", "").strip()
    kpi = request.args.get("kpi", "").strip()
    vendor = _normalize_vendor(request.args.get("vendor"))
    rat = _normalize_rat(request.args.get("rat") or request.args.get("technology"))
    if not cell_name or not kpi:
        return jsonify({"success": False, "error": "cell_name and kpi required"}), 400
    try:
        payload = get_cell_trend_payload(cell_name, kpi, vendor=vendor, rat=rat)
        if not payload:
            return jsonify({"success": False, "error": "No trend data for cell"}), 404
        return jsonify({"success": True, **payload})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@network_health_bp.route("/api/network-health/summary")
@login_required
def network_health_summary():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    vendor = request.args.get("vendor", cfg.DEFAULT_VENDOR)
    technology = cfg.pm_technology_for_rat(
        request.args.get("rat") or request.args.get("technology", cfg.DEFAULT_RAT)
    )
    area = request.args.get("area", "all")
    top_n = min(50, max(5, int(request.args.get("top_n", 20))))
    try:
        payload = get_health_payload(
            vendor=vendor, technology=technology, top_n=top_n, area=area,
        )
        return jsonify({
            "success": True,
            "stage": "development",
            "pm_data_scope": payload.get("pm_data_scope"),
            "benchmark": payload.get("benchmark"),
            "benchmark_days": payload.get("benchmark_days"),
            "generated_at": payload.get("generated_at"),
            "summary": payload.get("summary"),
            "technology": payload.get("technology"),
            "area": payload.get("area_filter"),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@network_health_bp.route("/api/network-health/worst")
@login_required
def network_health_worst():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    vendor = request.args.get("vendor", cfg.DEFAULT_VENDOR)
    technology = cfg.pm_technology_for_rat(
        request.args.get("rat") or request.args.get("technology", cfg.DEFAULT_RAT)
    )
    category = request.args.get("category")
    area = request.args.get("area", "all")
    top_n = min(50, max(5, int(request.args.get("top_n", 20))))
    try:
        payload = get_health_payload(
            vendor=vendor, technology=technology, top_n=top_n, area=area,
        )
        rows = get_worst_cells(payload, category=category, top_n=top_n)
        return jsonify({
            "success": True,
            "stage": "development",
            "pm_data_scope": payload.get("pm_data_scope"),
            "generated_at": payload.get("generated_at"),
            "category": category or "all",
            "area": payload.get("area_filter"),
            "cells": rows,
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@network_health_bp.route("/api/network-health/refresh", methods=["POST"])
@login_required
def network_health_refresh():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    role = str(user.get("role") or "").lower()
    if role not in ("admin", "noc_sys"):
        return jsonify({"error": "Forbidden"}), 403
    vendor = _normalize_vendor(request.args.get("vendor"))
    rat = _normalize_rat(request.args.get("rat") or request.args.get("technology"))
    force = request.args.get("force", "").strip().lower() in ("1", "true", "yes")
    try:
        if request.args.get("precalc", "").strip().lower() in ("1", "true", "yes"):
            result = build_vendor_rat(vendor, rat, force=force)
            return jsonify({"success": True, "precalc": result})
        all_build = request.args.get("all", "").strip().lower() in ("1", "true", "yes")
        if all_build:
            results = build_all(force=force)
            return jsonify({"success": True, "precalc": results})
        area = normalize_area(request.args.get("area"))
        top_n = min(50, max(5, int(request.args.get("top_n", 20))))
        technology = cfg.pm_technology_for_rat(rat)
        payload = get_health_payload(
            vendor=vendor,
            technology=technology,
            top_n=top_n,
            area=area,
            force_refresh=True,
        )
        return jsonify({
            "success": True,
            "stage": "development",
            "generated_at": payload.get("generated_at"),
            "summary": payload.get("summary"),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@network_health_bp.route("/api/network-health/groups")
@login_required
def network_health_groups():
    """Controller/BSC/RNC congestion from groups PM DBs (same data as Group Health)."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    vendor = request.args.get("vendor", "all")
    technology = request.args.get("rat") or request.args.get("technology") or "all"
    top_n = min(100, max(5, int(request.args.get("top_n", 20))))
    try:
        from core.radio.groups import group_health

        payload = group_health(vendor=vendor, technology=technology, limit=top_n)
        return jsonify({"success": True, "stage": "development", **payload})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500
