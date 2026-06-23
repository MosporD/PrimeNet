"""Femto PM module routes."""

from flask import Blueprint, jsonify, render_template, request, redirect, url_for
from functools import wraps
import os
import re
import sqlite3
import ast

import time as _time

from database_enhanced import get_user_by_session
from sync_config import PROJECT_ROOT


femto_pm_bp = Blueprint(
    "femto_pm",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/femto-pm/static",
)


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


FEMTO_PM_DB = os.path.join(PROJECT_ROOT, "databases", "cells", "femto_pm_cells.db")
FEMTO_TABLE = "FEMTO_HOURLY"
FEMTO_VALUES_TABLE = "FEMTO_HOURLY_VALUES"
FEMTO_COUNTER_TABLE = "FEMTO_COUNTER_CATALOG"
FEMTO_COMPUTED_TABLE = "FEMTO_COMPUTED_KPIS"
_FIXED_COLS = {
    "id", "unique_id", "timestamp", "hnb_id", "fsn", "bsr_name", "op_mode",
    "vendor", "system_type", "gp_seconds", "cbt", "mts", "archive_path", "updated_at",
}
_FORMULA_OVERRIDES = {
    "Call Setup Success Rate (CSSR)": "(rrcConnEstabSuccSum / rrcConnEstabAttSum) * (s1SigConnEstabSucc / s1SigConnEstabAtt) * (erabEstabInitSuccNbrSum / erabEstabInitAttNbrSum) * 100",
    "Mean E-RAB Setup Time": "AVG(erabEstabTimeMeanQci.*)",
    "E-RAB Drop Rate (RLF)": "SUM(VS.ERABReleasedDueToRadioLinkFailurePerQCI.*) / (SUM(VS.AbnormalERABReleasePerQCI.*) + SUM(VS.NormalERABReleasePerQCI.*)) * 100",
    "UE Context Release Abnormal Rate": "SUM(ueContxtRelReqRadioNetwork.*) / ueCtxtRelReqSum * 100",
    "E-RAB Avg Session Time": "erabSessionTimeSum / erabSessionTimeUE",
    "Handover Failure Due to Radio": "(SUM(hoInterEnbOutAttCauseRadioNetwork.*) - SUM(hoInterEnbOutSuccCauseRadioNetwork.*)) / hoInterEnbOutAttSum * 100",
    "DL User Throughput (Avg)": "SUM(DRB.IPVolDl.QCI*) / SUM(DRB.IPTimeDl.QCI*)",
    "UL User Throughput (Avg)": "SUM(DRB.IPVolUl.QCI*) / SUM(DRB.IPTimeUl.QCI*)",
    "DL PRB Utilization": "prbTotDl",
    "UL PRB Utilization": "prbTotUl",
    "Avg Active DL UEs": "ueActiveDlSum",
    "Cell Availability": "(1 - VS.LTECellUnavailable / measurement_period_sec) * 100",
    "LBO IPv4 Allocation Success": "VS.LBO.IPV4.Alloct.Status",
}

_COMPUTED_KPI_META = {
    "Call Setup Success Rate (CSSR)": {"category_l1": "Accessibility", "unit": "%"},
    "Mean E-RAB Setup Time": {"category_l1": "Accessibility", "unit": "ms"},
    "E-RAB Drop Rate (RLF)": {"category_l1": "Retainability", "unit": "%"},
    "UE Context Release Abnormal Rate": {"category_l1": "Retainability", "unit": "%"},
    "E-RAB Avg Session Time": {"category_l1": "Retainability", "unit": "s"},
    "Handover Failure Due to Radio": {"category_l1": "Mobility", "unit": "%"},
    "DL User Throughput (Avg)": {"category_l1": "Throughput", "unit": "Mbps"},
    "UL User Throughput (Avg)": {"category_l1": "Throughput", "unit": "Mbps"},
    "DL PRB Utilization": {"category_l1": "Capacity", "unit": "%"},
    "UL PRB Utilization": {"category_l1": "Capacity", "unit": "%"},
    "Avg Active DL UEs": {"category_l1": "Capacity", "unit": ""},
    "Cell Availability": {"category_l1": "Availability", "unit": "%"},
    "LBO IPv4 Allocation Success": {"category_l1": "Accessibility", "unit": "%"},
}


_kpi_cache: dict = {"ts": 0.0, "names": []}
_KPI_CACHE_TTL = 300  # 5 minutes


def _femto_conn():
    conn = sqlite3.connect(FEMTO_PM_DB, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def _sql_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return bool(row)


def _counter_hierarchy(name: str) -> tuple[str, str, str]:
    parts = name.split(".")
    first = parts[0] if parts else name
    is_acronym = first.isupper() and len(first) <= 10
    if is_acronym and len(parts) >= 3:
        return parts[0], parts[1], ".".join(parts[2:])
    if is_acronym and len(parts) == 2:
        return parts[0], parts[1], parts[1]
    if len(parts) >= 2:
        return "Raw Counters", first, name
    return "Raw Counters", "General", name


def _counter_catalog_columns(conn: sqlite3.Connection) -> set[str]:
    if not _table_exists(conn, FEMTO_COUNTER_TABLE):
        return set()
    return {str(r[1]) for r in conn.execute(f'PRAGMA table_info("{FEMTO_COUNTER_TABLE}")').fetchall()}


def _ensure_catalog_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{FEMTO_COMPUTED_TABLE}" (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT,
            kpi_name TEXT NOT NULL UNIQUE,
            category_l1 TEXT,
            formula TEXT,
            unit TEXT,
            description TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{FEMTO_COUNTER_TABLE}" (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            counter_name TEXT NOT NULL UNIQUE,
            l1 TEXT,
            l2 TEXT,
            l3 TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        f'CREATE INDEX IF NOT EXISTS idx_femto_counter_l123 ON "{FEMTO_COUNTER_TABLE}" (l1, l2, l3)'
    )
    cols = _counter_catalog_columns(conn)
    for col, ddl in (
        ("counter_id", "TEXT"),
        ("description", "TEXT"),
        ("seen_in_pm", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if col not in cols:
            conn.execute(f'ALTER TABLE "{FEMTO_COUNTER_TABLE}" ADD COLUMN {col} {ddl}')


def _seed_computed_kpis(conn: sqlite3.Connection) -> None:
    rows = []
    for idx, (kpi_name, formula) in enumerate(_FORMULA_OVERRIDES.items(), start=1):
        meta = _COMPUTED_KPI_META.get(kpi_name, {})
        rows.append(
            {
                "code": str(idx),
                "kpi_name": kpi_name,
                "category_l1": meta.get("category_l1") or "Other",
                "formula": formula,
                "unit": meta.get("unit") or "",
                "description": "",
            }
        )
    conn.executemany(
        f"""
        INSERT OR IGNORE INTO "{FEMTO_COMPUTED_TABLE}"
            (code, kpi_name, category_l1, formula, unit, description, updated_at)
        VALUES (:code, :kpi_name, :category_l1, :formula, :unit, :description, CURRENT_TIMESTAMP)
        """,
        rows,
    )


def _seed_counter_catalog(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, FEMTO_VALUES_TABLE):
        return
    names = [
        str(r[0]).strip()
        for r in conn.execute(
            f'SELECT DISTINCT kpi_name FROM "{FEMTO_VALUES_TABLE}" WHERE TRIM(kpi_name) <> "" ORDER BY kpi_name'
        ).fetchall()
        if str(r[0]).strip()
    ]
    if not names:
        return
    batch = []
    for name in names:
        l1, l2, l3 = _counter_hierarchy(name)
        batch.append({"counter_name": name, "l1": l1, "l2": l2, "l3": l3})
        if len(batch) >= 500:
            conn.executemany(
                f"""
                INSERT OR IGNORE INTO "{FEMTO_COUNTER_TABLE}"
                    (counter_name, l1, l2, l3, updated_at)
                VALUES (:counter_name, :l1, :l2, :l3, CURRENT_TIMESTAMP)
                """,
                batch,
            )
            batch.clear()
    if batch:
        conn.executemany(
            f"""
            INSERT OR IGNORE INTO "{FEMTO_COUNTER_TABLE}"
                (counter_name, l1, l2, l3, updated_at)
            VALUES (:counter_name, :l1, :l2, :l3, CURRENT_TIMESTAMP)
            """,
            batch,
        )


def _ensure_femto_catalog(conn: sqlite3.Connection) -> None:
    """Create catalog tables and seed from PM data so the UI does not scan millions of rows."""
    _ensure_catalog_tables(conn)
    computed_n = conn.execute(f'SELECT COUNT(*) FROM "{FEMTO_COMPUTED_TABLE}"').fetchone()[0]
    if not computed_n:
        _seed_computed_kpis(conn)
    counter_n = conn.execute(f'SELECT COUNT(*) FROM "{FEMTO_COUNTER_TABLE}"').fetchone()[0]
    if not counter_n and _table_exists(conn, FEMTO_VALUES_TABLE):
        _seed_counter_catalog(conn)
    conn.commit()
    _kpi_cache["names"] = []
    _kpi_cache["ts"] = 0.0


def _available_kpi_cols(conn: sqlite3.Connection) -> list[str]:
    now = _time.time()
    if _kpi_cache["names"] and now - _kpi_cache["ts"] < _KPI_CACHE_TTL:
        return _kpi_cache["names"]
    if _table_exists(conn, FEMTO_VALUES_TABLE):
        rows = conn.execute(
            f'SELECT DISTINCT kpi_name FROM "{FEMTO_VALUES_TABLE}" ORDER BY kpi_name'
        ).fetchall()
        result = sorted([str(r[0]) for r in rows if str(r[0]).strip()])
    else:
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{FEMTO_TABLE}")').fetchall()]
        result = sorted([c for c in cols if c not in _FIXED_COLS])
    _kpi_cache["names"] = result
    _kpi_cache["ts"] = now
    return result


def _fetch_catalog(conn: sqlite3.Connection) -> dict:
    kpis = []
    counters = {}
    if _table_exists(conn, FEMTO_COMPUTED_TABLE):
        rows = conn.execute(
            f'SELECT code, kpi_name, category_l1, formula, unit, description FROM "{FEMTO_COMPUTED_TABLE}" ORDER BY category_l1, kpi_name'
        ).fetchall()
        kpis = [dict(r) for r in rows]
    if _table_exists(conn, FEMTO_COUNTER_TABLE):
        rows = conn.execute(
            f'SELECT counter_name, l1, l2, l3 FROM "{FEMTO_COUNTER_TABLE}" ORDER BY l1, l2, l3, counter_name'
        ).fetchall()
        for r in rows:
            l1 = str(r["l1"] or "Other")
            l2 = str(r["l2"] or "Other")
            l3 = str(r["l3"] or "Other")
            counters.setdefault(l1, {}).setdefault(l2, {}).setdefault(l3, []).append(str(r["counter_name"]))
    return {"kpis": kpis, "counters": counters}


def _pattern_regex(pattern: str) -> re.Pattern:
    text = re.escape(str(pattern or "").strip()).replace(r"\*", ".*")
    return re.compile(rf"^{text}$")


def _evaluate_formula(kpi_name: str, formula: str, row_map: dict) -> float | None:
    raw_formula = (_FORMULA_OVERRIDES.get(kpi_name) or formula or "").strip()
    if not raw_formula:
        return None
    expr = raw_formula.replace("%", "")
    expr = expr.replace("(already a mean)", "")
    expr = expr.replace("(already a mean per QCI)", "")
    expr = expr.replace("(depends on Nokia impl)", "")
    expr = expr.replace("(bits/sec via unit scaling)", "")
    expr = expr.replace("(sample count)", "1")
    expr = expr.replace("(status counter, 1=OK)", "")
    expr = expr.strip()

    placeholders: dict[str, str] = {}

    def stash(code: str) -> str:
        key = f"__P{len(placeholders)}__"
        placeholders[key] = code
        return key

    expr = re.sub(r"SUM\(([^)]+)\)", lambda m: stash(f"sum_pattern({m.group(1).strip()!r})"), expr)
    expr = re.sub(r"AVG\(([^)]+)\)", lambda m: stash(f"avg_pattern({m.group(1).strip()!r})"), expr)
    expr = expr.replace("count(QCIs)", stash("count_qcis()"))

    allowed = {"measurement_period_sec"} | set(placeholders.keys())

    def repl_token(match: re.Match) -> str:
        token = match.group(0)
        if token in allowed:
            return token
        return f"value_of({token!r})"

    expr = re.sub(r"[A-Za-z_][A-Za-z0-9_.]*\*?", repl_token, expr)
    for key, val in placeholders.items():
        expr = expr.replace(key, val)

    def value_of(name: str) -> float:
        value = row_map.get(name)
        try:
            return float(value) if value is not None else 0.0
        except Exception:
            return 0.0

    def sum_pattern(pattern: str) -> float:
        rx = _pattern_regex(pattern)
        total = 0.0
        found = False
        for key, value in row_map.items():
            if not rx.match(str(key)):
                continue
            try:
                total += float(value)
                found = True
            except Exception:
                continue
        return total if found else 0.0

    def avg_pattern(pattern: str) -> float:
        rx = _pattern_regex(pattern)
        vals = []
        for key, value in row_map.items():
            if not rx.match(str(key)):
                continue
            try:
                vals.append(float(value))
            except Exception:
                continue
        return (sum(vals) / len(vals)) if vals else 0.0

    def count_qcis() -> float:
        return max(1.0, float(len([k for k in row_map if str(k).startswith("erabEstabTimeMeanQci.") and row_map.get(k) is not None])))

    def _safe_eval_math(expression: str) -> float:
        names = {
            "value_of": value_of,
            "sum_pattern": sum_pattern,
            "avg_pattern": avg_pattern,
            "count_qcis": count_qcis,
            "measurement_period_sec": value_of("measurement_period_sec"),
        }
        allowed_funcs = {"value_of", "sum_pattern", "avg_pattern", "count_qcis"}

        def walk(node):
            if isinstance(node, ast.Expression):
                return walk(node.body)
            if isinstance(node, ast.Constant):
                if isinstance(node.value, (int, float, str)):
                    return node.value
                raise ValueError("Unsupported constant")
            if isinstance(node, ast.Name):
                if node.id not in names:
                    raise ValueError("Unknown identifier")
                return names[node.id]
            if isinstance(node, ast.UnaryOp):
                val = walk(node.operand)
                if isinstance(node.op, ast.UAdd):
                    return +float(val)
                if isinstance(node.op, ast.USub):
                    return -float(val)
                raise ValueError("Unsupported unary operator")
            if isinstance(node, ast.BinOp):
                left = float(walk(node.left))
                right = float(walk(node.right))
                if isinstance(node.op, ast.Add):
                    return left + right
                if isinstance(node.op, ast.Sub):
                    return left - right
                if isinstance(node.op, ast.Mult):
                    return left * right
                if isinstance(node.op, ast.Div):
                    return 0.0 if right == 0 else left / right
                if isinstance(node.op, ast.Pow):
                    return left ** right
                raise ValueError("Unsupported binary operator")
            if isinstance(node, ast.Call):
                if not isinstance(node.func, ast.Name) or node.func.id not in allowed_funcs:
                    raise ValueError("Unsupported function")
                func = names[node.func.id]
                args = [walk(a) for a in node.args]
                return func(*args)
            raise ValueError("Unsupported expression")

        parsed = ast.parse(expression, mode="eval")
        return float(walk(parsed))

    try:
        result = _safe_eval_math(expr)
        if result is None:
            return None
        result = float(result)
        if result == float("inf") or result == float("-inf"):
            return None
        return result
    except Exception:
        return None


def _series_rows_for_device(conn: sqlite3.Connection, unique_id: str, selected: list[str], limit: int) -> tuple[list[str], list[dict]]:
    ts_rows = conn.execute(
        f"""
        SELECT timestamp, gp_seconds
        FROM "{FEMTO_TABLE}"
        WHERE unique_id = ?
        ORDER BY timestamp ASC
        LIMIT ?
        """,
        (unique_id, limit),
    ).fetchall()
    if not ts_rows:
        return selected, []

    ts_list = [str(r["timestamp"]) for r in ts_rows if str(r["timestamp"] or "").strip()]
    if not ts_list:
        return selected, []

    placeholders = ", ".join(["?"] * len(ts_list))
    value_rows = conn.execute(
        f"""
        SELECT timestamp, kpi_name, kpi_value
        FROM "{FEMTO_VALUES_TABLE}"
        WHERE unique_id = ?
          AND timestamp IN ({placeholders})
        """,
        [unique_id] + ts_list,
    ).fetchall()

    computed_defs = {}
    if _table_exists(conn, FEMTO_COMPUTED_TABLE):
        placeholders = ", ".join(["?"] * len(selected)) if selected else "''"
        rows = conn.execute(
            f'SELECT kpi_name, formula FROM "{FEMTO_COMPUTED_TABLE}" WHERE kpi_name IN ({placeholders})',
            selected,
        ).fetchall() if selected else []
        computed_defs = {str(r["kpi_name"]): str(r["formula"] or "") for r in rows}

    by_ts: dict[str, dict] = {
        str(r["timestamp"]): {"timestamp": str(r["timestamp"]), "measurement_period_sec": r["gp_seconds"]}
        for r in ts_rows
    }
    for r in value_rows:
        ts = str(r["timestamp"] or "")
        if not ts or ts not in by_ts:
            continue
        by_ts[ts][str(r["kpi_name"])] = r["kpi_value"]

    rows = []
    for ts in ts_list:
        base = by_ts.get(ts, {"timestamp": ts})
        out = {"timestamp": ts}
        for name in selected:
            if name in computed_defs:
                out[name] = _evaluate_formula(name, computed_defs[name], base)
            else:
                out[name] = base.get(name)
        rows.append(out)
    return selected, rows


@femto_pm_bp.route("/femto-pm")
@login_required
def femto_pm_page():
    user = get_current_user()
    return render_template("femto_pm.html", user=format_user(user))


@femto_pm_bp.route("/api/femto-pm/devices")
def femto_pm_devices():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    if not os.path.isfile(FEMTO_PM_DB):
        return jsonify({"success": True, "devices": []})
    conn = _femto_conn()
    try:
        rows = conn.execute(
            f"""
            SELECT unique_id,
                   MAX(COALESCE(NULLIF(TRIM(bsr_name), ''), unique_id)) AS bsr_name,
                   MAX(timestamp) AS latest_timestamp,
                   COUNT(*) AS points
            FROM "{FEMTO_TABLE}"
            WHERE unique_id IS NOT NULL AND TRIM(unique_id) <> ''
            GROUP BY unique_id
            ORDER BY latest_timestamp DESC
            """
        ).fetchall()
        devices = [dict(r) for r in rows]
        return jsonify({"success": True, "devices": devices})
    finally:
        conn.close()


@femto_pm_bp.route("/api/femto-pm/catalog")
def femto_pm_catalog():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    if not os.path.isfile(FEMTO_PM_DB):
        return jsonify({"success": True, "kpis": [], "counters": {}})
    conn = _femto_conn()
    try:
        _ensure_femto_catalog(conn)
        payload = _fetch_catalog(conn)
        return jsonify({"success": True, **payload})
    finally:
        conn.close()


@femto_pm_bp.route("/api/femto-pm/kpi-columns")
def femto_pm_kpi_columns():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    if not os.path.isfile(FEMTO_PM_DB):
        return jsonify({"success": True, "columns": []})
    conn = _femto_conn()
    try:
        if _table_exists(conn, FEMTO_COMPUTED_TABLE):
            rows = conn.execute(
                f'SELECT kpi_name FROM "{FEMTO_COMPUTED_TABLE}" ORDER BY kpi_name'
            ).fetchall()
            return jsonify({"success": True, "columns": [str(r[0]) for r in rows]})
        return jsonify({"success": True, "columns": _available_kpi_cols(conn)})
    finally:
        conn.close()


@femto_pm_bp.route("/api/femto-pm/trend")
def femto_pm_trend():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    unique_id = (request.args.get("unique_id") or "").strip()
    if not unique_id:
        return jsonify({"error": "unique_id is required"}), 400
    kpi_raw = (request.args.get("kpi") or "").strip()
    req_kpis = [k.strip() for k in kpi_raw.split(",") if k.strip()]
    limit = request.args.get("limit", 240, type=int) or 240
    limit = max(1, min(limit, 2000))
    if not os.path.isfile(FEMTO_PM_DB):
        return jsonify({"success": True, "rows": [], "columns": []})

    conn = _femto_conn()
    try:
        raw_allow = set(_available_kpi_cols(conn))
        computed_allow = set()
        if _table_exists(conn, FEMTO_COMPUTED_TABLE):
            rows = conn.execute(f'SELECT kpi_name FROM "{FEMTO_COMPUTED_TABLE}"').fetchall()
            computed_allow = {str(r[0]) for r in rows if str(r[0]).strip()}
        allow = raw_allow | computed_allow
        selected = [k for k in req_kpis if k in allow] if req_kpis else sorted(list(allow))[:5]
        if not selected:
            return jsonify({"success": True, "rows": [], "columns": []})

        columns, rows = _series_rows_for_device(conn, unique_id, selected, limit)
        return jsonify({
            "success": True,
            "columns": ["timestamp"] + columns,
            "rows": rows,
            "unique_id": unique_id,
        })
    finally:
        conn.close()

