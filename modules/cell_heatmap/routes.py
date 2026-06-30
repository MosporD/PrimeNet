"""
Cell Heatmap Routes
Standalone heatmap module for KPI-driven map intensity overlays.
"""

from flask import Blueprint, request, jsonify, render_template, redirect, url_for
from functools import wraps
from datetime import datetime
import sqlite3
import math
import re

from db.runtime import connect_metadata, execute_query
from database_enhanced import get_user_by_session, log_activity
from sync_config import (
    NOKIA_PM_DB,
    HUAWEI_PM_DB,
    NOKIA_PM_DAILY_DB,
    HUAWEI_PM_DAILY_DB,
    pm_table_name,
)


cell_heatmap_bp = Blueprint(
    "cell_heatmap",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/cell_heatmap/static",
)

KPI_PRESETS = {
    "access_rrc": {
        "label": "RRC / Radio Access SR (%)",
        "direction": "higher_better",
        "good": 99.0,
        "bad": 95.0,
        "aliases": [
            "RRC Setup Success Rate(%)",
            "RRC Setup Success Rate",
            "RRC Connection Setup Success Rate",
            "RRC Conn Setup SR",
            "Total E-UTRAN RRC conn stp SR",
            "RRC conn stp SR (Service)",
            "RRC conn stp SR mos",
            "Comp Cont based RACH stp SR",
            "Compl RACH stp SR",
            "RACH Stp Completion SR",
            "Radio Access Success Rate",
            "CSSR(%)",
            "CSSR",
            "Call Setup Success Rate",
            "SDCCH Assignment Success Rate",
            "TCH Assignment Success Rate",
            "RACH Success Rate",
            "Random Access Success Rate",
        ],
    },
    "access_erab": {
        "label": "E-RAB / Bearer Setup SR (%)",
        "direction": "higher_better",
        "good": 99.0,
        "bad": 96.0,
        "aliases": [
            "E-RAB Setup Success Rate (ALL)(%)",
            "E-RAB Setup Success Rate",
            "E-UTRAN E-RAB stp SR",
            "E-RAB stp SR",
            "ERAB Setup Success Rate",
            "Bearer Setup Success Rate",
            "Initial E-RAB Setup Success Rate",
        ],
    },
    "access_initial": {
        "label": "Initial Access / Attach SR (%)",
        "direction": "higher_better",
        "good": 98.5,
        "bad": 95.0,
        "aliases": [
            "Initial Access Success Rate",
            "Attach Success Rate",
            "Service Request Success Rate",
            "S1 Signaling Connection Setup Success Rate",
            "S1 init ctxt stp SR",
            "RACH Setup Success Rate",
            "Random Access Setup Success Rate",
        ],
    },
    "retainability_drop": {
        "label": "Drop Rate (%)",
        "direction": "lower_better",
        "good": 0.0,
        "bad": 0.7,
        "aliases": [
            "E-UTRAN E-RAB DR, RAN View",
            "E-RAB Drop Ratio (RAN View) (%)",
            "E-UTRAN E-RAB Drop Ratio, User Perspective",
            "drop_rate",
            "call_drop_rate",
            "Drop Call Rate",
            "Call DR",
            "Call Drop Rate (All)(%)",
            "AMR Call Drop Ratio(%)",
        ],
    },
}


def _resolve_kpi_preset(key: str) -> tuple[str, dict]:
    k = (key or "").strip()
    if k in KPI_PRESETS:
        return k, KPI_PRESETS[k]
    return "access_rrc", KPI_PRESETS["access_rrc"]


def _normalize_vendor(raw: str | None) -> str:
    v = str(raw or "all").strip().lower()
    return v if v in ("all", "nokia", "huawei") else "all"


def _normalize_technology(raw: str | None) -> str:
    t = str(raw or "4G").strip().upper().replace("_", "-")
    aliases = {
        "ALL": "all",
        "2G": "2G",
        "3G": "3G",
        "4G": "4G",
        "LTE": "4G",
        "4G-FDD": "4G-FDD",
        "4G-TDD": "4G-TDD",
        "5G": "5G",
        "NR": "5G",
    }
    return aliases.get(t, "4G")


def _pm_technology(metadata_technology: str) -> str:
    tech = str(metadata_technology or "").strip().upper()
    if tech.startswith("4G"):
        return "4G"
    return tech or "4G"


def _metadata_union_sql() -> str:
    return """
        SELECT
            cell_name,
            '2G' AS technology,
            vendor,
            NULL AS activity_status,
            azimuth,
            frequency_band AS frequency_band,
            site_id AS site_id,
            site_name AS site_name,
            CAST(lat AS REAL) AS latitude,
            CAST("long" AS REAL) AS longitude
        FROM cells_2g
        UNION ALL
        SELECT
            cell_name,
            '3G' AS technology,
            vendor,
            NULL AS activity_status,
            azimuth,
            dl_uarfcn AS frequency_band,
            nodeb_id AS site_id,
            nodeb_name AS site_name,
            CAST(lat AS REAL) AS latitude,
            CAST("long" AS REAL) AS longitude
        FROM cells_3g
        UNION ALL
        SELECT
            cell_name,
            '4G-FDD' AS technology,
            vendor,
            NULL AS activity_status,
            azimuth,
            band AS frequency_band,
            enb_id_actual AS site_id,
            enb_name AS site_name,
            CAST(lat AS REAL) AS latitude,
            CAST("long" AS REAL) AS longitude
        FROM cells_4g_fdd
        UNION ALL
        SELECT
            cell_name,
            '4G-TDD' AS technology,
            vendor,
            NULL AS activity_status,
            azimuth,
            band AS frequency_band,
            enb_id_actual AS site_id,
            enb_name AS site_name,
            CAST(lat AS REAL) AS latitude,
            CAST("long" AS REAL) AS longitude
        FROM cells_4g_tdd
        UNION ALL
        SELECT
            cell_name,
            '5G' AS technology,
            vendor,
            NULL AS activity_status,
            azimuth,
            bw AS frequency_band,
            gnb_id_actual AS site_id,
            gnb_name AS site_name,
            CAST(lat AS REAL) AS latitude,
            CAST("long" AS REAL) AS longitude
        FROM cells_5g
    """


def _normalize_scope(raw: str) -> str:
    v = (raw or "").strip().lower()
    if v in ("daily", "day", "d"):
        return "daily"
    return "hourly"


def _size_from_avg_distance(value: float | None) -> float:
    """
    Convert average-distance KPI to map radius (meters), bounded for readability.
    The Nokia PM stores this in km (e.g. 0.261 = 261m), so multiply by 1000.
    """
    if value is None:
        return 260.0
    v = max(0.0, float(value))
    if v < 50:
        v = v * 1000.0
    return max(120.0, min(1200.0, v))


def _normalize_size_weight(radius_m: float, min_r: float, max_r: float) -> float:
    """Map sector radius (m) to 0..1 for heat / fill intensity."""
    span = max_r - min_r
    if span < 1e-6:
        return 0.5
    v = (float(radius_m) - min_r) / span
    return max(0.0, min(1.0, v))


def _normalize_weight(value: float | None, direction: str, good: float, bad: float) -> float:
    if value is None:
        return 0.0
    span = abs(good - bad)
    if span < 1e-9:
        return 0.0
    if direction == "lower_better":
        score = (value - good) / span
    else:
        score = (good - value) / span
    if score < 0:
        return 0.0
    if score > 1:
        return 1.0
    return score


def _to_float(raw) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    s = str(raw).strip()
    if not s:
        return None
    s = s.replace(",", "")
    s = re.sub(r"(?i)\s*(m|meter|meters|%)\s*$", "", s).strip()
    m = re.search(r"[-+]?\d*\.?\d+", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except (TypeError, ValueError):
        return None


# Map of known cell-name and timestamp columns per technology table
_CELL_COL_CANDIDATES = [
    "LNCEL name",
    "NRCEL name",
    "WCEL name",
    "BTS name",
    "cell_name",
    "Cell Name",
    "Cell",
    "LocalCell Id",
]
_TS_COL_CANDIDATES = [
    "PERIOD_START_TIME",
    "timestamp",
    "Timestamp",
    "period_start_time",
    "Date",
    "date",
    "Time",
    "time",
]


def _sqlite_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _find_col(cols: list[str], candidates: list[str]) -> str | None:
    cols_lower = {c.strip().lower(): c for c in cols}
    for cand in candidates:
        matched = cols_lower.get(cand.strip().lower())
        if matched:
            return matched
    return None


def _column_nonempty_count(conn: sqlite3.Connection, table_name: str, column: str) -> int:
    try:
        row = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM {_sqlite_ident(table_name)}
            WHERE {_sqlite_ident(column)} IS NOT NULL
              AND TRIM(CAST({_sqlite_ident(column)} AS TEXT)) <> ''
            """
        ).fetchone()
        return int(row[0] or 0) if row else 0
    except sqlite3.Error:
        return 0


def _find_populated_col(conn: sqlite3.Connection, table_name: str, cols: list[str], candidates: list[str]) -> str | None:
    cols_lower = {c.strip().lower(): c for c in cols}
    matches: list[str] = []
    for cand in candidates:
        matched = cols_lower.get(cand.strip().lower())
        if matched and matched not in matches:
            matches.append(matched)
    if not matches:
        return None
    return max(matches, key=lambda c: _column_nonempty_count(conn, table_name, c))


def _parse_pm_timestamp(raw) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    s = str(raw).strip()
    if not s:
        return None
    s = s.replace("T", " ").replace("Z", "")
    s = re.sub(r"\.\d{1,6}$", "", s)
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%d-%m-%Y",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _pm_latest_values_for_cells(pm_db_path: str, table_name: str, kpi_column: str, cell_names: list[str]) -> dict[str, float]:
    if not cell_names:
        return {}
    out: dict[str, float] = {}

    conn = sqlite3.connect(pm_db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()]
        if not cols:
            return out

        cell_col = _find_populated_col(conn, table_name, cols, _CELL_COL_CANDIDATES)
        ts_col = _find_populated_col(conn, table_name, cols, _TS_COL_CANDIDATES)
        if not cell_col or not ts_col:
            return out
        if kpi_column not in cols:
            return out

        chunk_size = 700
        for i in range(0, len(cell_names), chunk_size):
            chunk = [str(name).strip() for name in cell_names[i:i + chunk_size] if str(name or "").strip()]
            if not chunk:
                continue
            ph = ",".join("?" for _ in chunk)
            sql = f"""
                SELECT
                    {_sqlite_ident(cell_col)} AS cell_name,
                    {_sqlite_ident(ts_col)} AS ts_value,
                    {_sqlite_ident(kpi_column)} AS kpi_value
                FROM {_sqlite_ident(table_name)}
                WHERE {_sqlite_ident(cell_col)} IN ({ph})
                  AND {_sqlite_ident(kpi_column)} IS NOT NULL
            """
            rows = conn.execute(sql, chunk).fetchall()
            latest: dict[str, tuple[tuple[int, datetime | str], float]] = {}
            for r in rows:
                v = _to_float(r["kpi_value"])
                if v is None:
                    continue
                cell_name = str(r["cell_name"] or "").strip()
                if not cell_name:
                    continue
                parsed_ts = _parse_pm_timestamp(r["ts_value"])
                sort_key: tuple[int, datetime | str]
                if parsed_ts is not None:
                    sort_key = (1, parsed_ts)
                else:
                    sort_key = (0, str(r["ts_value"] or ""))
                prev = latest.get(cell_name)
                if prev is None or sort_key > prev[0]:
                    latest[cell_name] = (sort_key, v)
            out.update({cell: val for cell, (_sort_key, val) in latest.items()})
    finally:
        conn.close()
    return out


def _resolve_kpi_column_in_table(pm_db_path: str, table_name: str, aliases: list[str]) -> str | None:
    conn = sqlite3.connect(pm_db_path, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()]
        if not cols:
            return None
        lower_map = {str(c).strip().lower(): c for c in cols}
        for alias in aliases:
            c = lower_map.get(str(alias).strip().lower())
            if c:
                return c
        def _norm(s: str) -> str:
            return "".join(ch for ch in str(s).lower() if ch.isalnum())
        norm_cols = { _norm(c): c for c in cols }
        for alias in aliases:
            c = norm_cols.get(_norm(alias))
            if c:
                return c
        alias_lows = [str(a).strip().lower() for a in aliases]
        for col in cols:
            cl = str(col).strip().lower()
            if any((a and (a in cl or cl in a)) for a in alias_lows):
                return col
        return None
    finally:
        conn.close()


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        session_token = request.cookies.get("session_token")
        if not session_token:
            return redirect(url_for("auth.login_page"))
        user = get_user_by_session(session_token)
        if not user:
            return redirect(url_for("auth.login_page"))
        request.current_user = user
        return f(*args, **kwargs)

    return decorated


def get_current_user():
    session_token = request.cookies.get("session_token")
    if session_token:
        return get_user_by_session(session_token)
    return None


def format_user(user):
    if not user:
        return None
    if isinstance(user, dict):
        return {
            "id": user.get("id"),
            "username": user.get("username"),
            "role": user.get("role"),
        }
    return {
        "id": user[0],
        "username": user[1],
        "role": user[6],
    }


@cell_heatmap_bp.route("/cell-heatmap")
@login_required
def cell_heatmap_page():
    user = get_current_user()
    return render_template("cell_heatmap.html", user=format_user(user))


@cell_heatmap_bp.route("/api/cell-heatmap/points", methods=["GET"])
def get_heatmap_points():
    """
    Returns heat points for Leaflet.heat as [latitude, longitude, weight] and
    per-cell details. Weights are normalized from KPI value using preset direction
    and optional good/bad query overrides (threshold_normalized).
    """
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    kpi = (request.args.get("kpi") or "access_rrc").strip()
    vendor = _normalize_vendor(request.args.get("vendor"))
    technology = _normalize_technology(request.args.get("technology"))
    data_scope = _normalize_scope(request.args.get("data_scope"))
    band = (request.args.get("band") or "").strip()
    limit_raw = request.args.get("limit")
    try:
        limit = max(100, min(int(limit_raw), 20000)) if limit_raw else 20000
    except ValueError:
        limit = 8000

    preset_key, preset = _resolve_kpi_preset(kpi)
    aliases = preset["aliases"]
    size_aliases = [
        "Avg UE distance",
        "Expect cell size",
        "Average UE Distance (m)",
        "avg_ue_distance",
        "avg_ue_dist_rrc",
        "avg_ue_dist_rach",
        "UCELL.UE.TP.MEAN.DISTANCE(m)",
        "Avg UE dist RRC con",
        "Avg UE dist RACH stp",
    ]
    try:
        good_thr = float(request.args.get("good", preset["good"]))
    except (TypeError, ValueError):
        good_thr = float(preset["good"])
    try:
        bad_thr = float(request.args.get("bad", preset["bad"]))
    except (TypeError, ValueError):
        bad_thr = float(preset["bad"])
    if abs(good_thr - bad_thr) < 1e-9:
        bad_thr = good_thr - 1.0 if preset["direction"] == "higher_better" else good_thr + 1.0

    try:
        conn = connect_metadata()
        if isinstance(conn, sqlite3.Connection):
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA query_only=ON")
        tech_clause = ""
        tech_params: list[object] = []
        if technology == "4G":
            tech_clause = "AND v.technology IN ('4G-FDD', '4G-TDD')"
        elif technology != "all":
            tech_clause = "AND v.technology = ?"
            tech_params.append(technology)
        vendor_clause = ""
        params: list[object] = []
        if vendor != "all":
            vendor_clause = "AND LOWER(TRIM(COALESCE(v.vendor, ''))) = ?"
            params.append(vendor)
        params.extend(tech_params)
        params.extend([band, band, limit])

        sql = f"""
            WITH v AS (
                {_metadata_union_sql()}
            )
            SELECT
                v.cell_name,
                v.technology,
                v.vendor,
                v.activity_status,
                v.azimuth,
                v.frequency_band,
                v.site_id,
                v.site_name,
                v.latitude,
                v.longitude
            FROM v
            WHERE v.latitude IS NOT NULL
              AND v.longitude IS NOT NULL
              {vendor_clause}
              {tech_clause}
              AND (? = '' OR LOWER(TRIM(CAST(v.frequency_band AS TEXT))) = LOWER(TRIM(?)))
            ORDER BY v.site_id, v.cell_name
            LIMIT ?
        """
        rows = execute_query(conn, sql, params).fetchall()
        conn.close()

        cell_rows = [dict(r) for r in rows]
        by_vendor_tech: dict[tuple[str, str], list[str]] = {}
        for r in cell_rows:
            row_vendor = str(r.get("vendor") or "").strip()
            row_tech = str(r.get("technology") or "").strip()
            pm_tech = _pm_technology(row_tech)
            key = (row_vendor, pm_tech)
            by_vendor_tech.setdefault(key, []).append(str(r.get("cell_name") or ""))

        kpi_map: dict[str, float] = {}
        size_map: dict[str, float] = {}
        for (vnd, pm_tech), names in by_vendor_tech.items():
            if not names:
                continue
            if vnd.strip().lower() == "huawei":
                pm_db_primary = HUAWEI_PM_DAILY_DB if data_scope == "daily" else HUAWEI_PM_DB
                pm_db_fallback = HUAWEI_PM_DB
            else:
                pm_db_primary = NOKIA_PM_DAILY_DB if data_scope == "daily" else NOKIA_PM_DB
                pm_db_fallback = NOKIA_PM_DB
            table_name = pm_table_name(pm_tech)
            if data_scope == "daily":
                table_name = table_name.replace("_HOURLY", "_DAILY")

            # Try primary DB; if table is empty or missing, fall back to hourly
            pm_db = pm_db_primary
            tbl = table_name
            resolved_col = _resolve_kpi_column_in_table(pm_db, tbl, aliases)
            if not resolved_col and data_scope == "daily":
                pm_db = pm_db_fallback
                tbl = pm_table_name(pm_tech)
                resolved_col = _resolve_kpi_column_in_table(pm_db, tbl, aliases)

            if resolved_col:
                kpi_map.update(_pm_latest_values_for_cells(pm_db, tbl, resolved_col, names))

            size_col = _resolve_kpi_column_in_table(pm_db, tbl, size_aliases)
            if size_col:
                size_map.update(_pm_latest_values_for_cells(pm_db, tbl, size_col, names))

        matched_vals = [v for v in kpi_map.values() if isinstance(v, (int, float))]
        kpi_avg = (sum(matched_vals) / len(matched_vals)) if matched_vals else None
        kpi_min = min(matched_vals) if matched_vals else None
        kpi_max = max(matched_vals) if matched_vals else None
        direction = preset["direction"]

        details = []
        matched = 0
        matched_size = 0
        fallback_used = 0
        for r in cell_rows:
            kpi_value = kpi_map.get(str(r["cell_name"]))
            avg_distance = size_map.get(str(r["cell_name"]))
            if avg_distance is not None:
                matched_size += 1
            if kpi_value is not None:
                matched += 1
                kpi_weight = _normalize_weight(kpi_value, direction, good_thr, bad_thr)
            else:
                kpi_weight = None
                fallback_used += 1
            lat = float(r["latitude"])
            lng = float(r["longitude"])
            size_radius_m = _size_from_avg_distance(avg_distance)
            details.append(
                {
                    "cell_name": r["cell_name"],
                    "site_id": r["site_id"],
                    "site_name": r["site_name"],
                    "technology": r["technology"],
                    "frequency_band": r.get("frequency_band"),
                    "vendor": r["vendor"],
                    "activity_status": r["activity_status"],
                    "kpi_name": preset_key,
                    "kpi_value": kpi_value,
                    "kpi_weight": kpi_weight,
                    "weight": kpi_weight,
                    "azimuth": r.get("azimuth"),
                    "avg_distance_m": avg_distance,
                    "size_radius_m": size_radius_m,
                    "latitude": lat,
                    "longitude": lng,
                }
            )

        details = [d for d in details if d["kpi_value"] is not None]
        shown_radii = [float(d["size_radius_m"]) for d in details]
        min_radius = min(shown_radii) if shown_radii else 0.0
        max_radius = max(shown_radii) if shown_radii else 0.0
        size_vals = [d["size_radius_m"] for d in details]
        size_avg = (sum(size_vals) / len(size_vals)) if size_vals else None

        points = []
        for d in details:
            sw = _normalize_size_weight(d["size_radius_m"], min_radius, max_radius)
            d["size_weight"] = sw
            lat = d["latitude"]
            lng = d["longitude"]
            points.append([lat, lng, float(sw)])

        uid = user.get("id") if isinstance(user, dict) else user[0]
        log_activity(uid, "heatmap_view", f"Viewed cell heatmap ({len(points)} points)")

        return jsonify(
            {
                "success": True,
                "points": points,
                "details": details,
                "meta": {
                    "count": len(points),
                    "kpi": preset_key,
                    "kpi_label": preset["label"],
                    "direction": preset["direction"],
                    "technology_scope": technology,
                    "vendor_scope": vendor,
                    "good_threshold": good_thr,
                    "bad_threshold": bad_thr,
                    "data_scope": data_scope,
                    "matched_kpi_cells": matched,
                    "matched_size_cells": matched_size,
                    "fallback_cells": fallback_used,
                    "weight_mode": "sector_size",
                    "size_min_m": min_radius,
                    "size_max_m": max_radius,
                    "size_avg_m": size_avg,
                    "kpi_avg": kpi_avg,
                    "kpi_min": kpi_min,
                    "kpi_max": kpi_max,
                    "drop_avg": kpi_avg,
                    "drop_min": kpi_min,
                    "drop_max": kpi_max,
                    "size_metric": "avg_distance_m",
                },
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@cell_heatmap_bp.route("/api/cell-heatmap/config", methods=["GET"])
def get_heatmap_config():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    presets = [
        {
            "key": k,
            "label": v["label"],
            "direction": v["direction"],
            "good": float(v["good"]),
            "bad": float(v["bad"]),
        }
        for k, v in KPI_PRESETS.items()
    ]
    return jsonify({"success": True, "kpi_presets": presets})


@cell_heatmap_bp.route("/api/cell-heatmap/bands", methods=["GET"])
def get_heatmap_bands():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    vendor = _normalize_vendor(request.args.get("vendor"))
    technology = _normalize_technology(request.args.get("technology"))
    try:
        conn = connect_metadata()
        tech_clause = ""
        tech_params: list[object] = []
        if technology == "4G":
            tech_clause = "AND v.technology IN ('4G-FDD', '4G-TDD')"
        elif technology != "all":
            tech_clause = "AND v.technology = ?"
            tech_params.append(technology)
        vendor_clause = ""
        params: list[object] = []
        if vendor != "all":
            vendor_clause = "AND LOWER(TRIM(COALESCE(v.vendor, ''))) = ?"
            params.append(vendor)
        params.extend(tech_params)
        rows = execute_query(
            conn,
            f"""
            WITH v AS (
                {_metadata_union_sql()}
            )
            SELECT DISTINCT CAST(v.frequency_band AS TEXT) AS band
            FROM v
            WHERE v.frequency_band IS NOT NULL
              AND TRIM(CAST(v.frequency_band AS TEXT)) <> ''
              {vendor_clause}
              {tech_clause}
            ORDER BY band
            """,
            params,
        ).fetchall()
        conn.close()
        return jsonify({"success": True, "bands": [str(r["band"]) for r in rows]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

