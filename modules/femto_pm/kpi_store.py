"""User-defined Femto KPI definitions (separate SQLite database)."""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime

from sync_config import DATABASES_ROOT

FEMTO_USER_KPI_DB = os.path.join(DATABASES_ROOT, "cells", "femto_user_kpis.db")
USER_KPI_TABLE = "FEMTO_USER_KPIS"

_DEFAULT_CATEGORIES = (
    "Accessibility",
    "Retainability",
    "Mobility",
    "Throughput",
    "Capacity",
    "Availability",
    "Custom",
)

_FORMULA_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*\*?")
_AGG_CALL_RE = re.compile(r"(SUM|AVG)\s*\(\s*([^)]+)\s*\)", re.IGNORECASE)


def user_kpi_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(FEMTO_USER_KPI_DB), exist_ok=True)
    conn = sqlite3.connect(FEMTO_USER_KPI_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    ensure_user_kpi_schema(conn)
    return conn


def ensure_user_kpi_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{USER_KPI_TABLE}" (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kpi_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            category_l1 TEXT NOT NULL DEFAULT 'Custom',
            formula TEXT NOT NULL,
            unit TEXT,
            description TEXT,
            created_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        f'CREATE INDEX IF NOT EXISTS idx_femto_user_kpi_cat ON "{USER_KPI_TABLE}" (category_l1, kpi_name)'
    )


def default_categories() -> list[str]:
    return list(_DEFAULT_CATEGORIES)


def list_user_kpis(conn: sqlite3.Connection | None = None) -> list[dict]:
    own = conn is None
    if own:
        conn = user_kpi_conn()
    try:
        rows = conn.execute(
            f"""
            SELECT id, kpi_name, category_l1, formula, unit, description,
                   created_by, created_at, updated_at
            FROM "{USER_KPI_TABLE}"
            ORDER BY category_l1, kpi_name
            """
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        if own:
            conn.close()


def get_user_kpi(conn: sqlite3.Connection, kpi_id: int) -> dict | None:
    row = conn.execute(
        f"""
        SELECT id, kpi_name, category_l1, formula, unit, description,
               created_by, created_at, updated_at
        FROM "{USER_KPI_TABLE}"
        WHERE id = ?
        """,
        (kpi_id,),
    ).fetchone()
    return _row_to_dict(row) if row else None


def get_user_kpi_by_name(conn: sqlite3.Connection, kpi_name: str) -> dict | None:
    row = conn.execute(
        f"""
        SELECT id, kpi_name, category_l1, formula, unit, description,
               created_by, created_at, updated_at
        FROM "{USER_KPI_TABLE}"
        WHERE kpi_name = ? COLLATE NOCASE
        """,
        (kpi_name.strip(),),
    ).fetchone()
    return _row_to_dict(row) if row else None


def create_user_kpi(conn: sqlite3.Connection, payload: dict, created_by: str = "") -> dict:
    name = str(payload.get("kpi_name") or "").strip()
    formula = str(payload.get("formula") or "").strip()
    if not name:
        raise ValueError("KPI name is required")
    if not formula:
        raise ValueError("Formula is required")
    category = str(payload.get("category_l1") or "Custom").strip() or "Custom"
    unit = str(payload.get("unit") or "").strip()
    description = str(payload.get("description") or "").strip()
    cur = conn.execute(
        f"""
        INSERT INTO "{USER_KPI_TABLE}"
            (kpi_name, category_l1, formula, unit, description, created_by, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (name, category, formula, unit, description, created_by or None),
    )
    conn.commit()
    return get_user_kpi(conn, int(cur.lastrowid)) or {}


def update_user_kpi(conn: sqlite3.Connection, kpi_id: int, payload: dict) -> dict:
    existing = get_user_kpi(conn, kpi_id)
    if not existing:
        raise ValueError("KPI not found")
    name = str(payload.get("kpi_name") or existing["kpi_name"]).strip()
    formula = str(payload.get("formula") or existing["formula"]).strip()
    if not name:
        raise ValueError("KPI name is required")
    if not formula:
        raise ValueError("Formula is required")
    category = str(payload.get("category_l1") or existing["category_l1"] or "Custom").strip() or "Custom"
    unit = str(payload.get("unit") or existing.get("unit") or "").strip()
    description = str(payload.get("description") or existing.get("description") or "").strip()
    conn.execute(
        f"""
        UPDATE "{USER_KPI_TABLE}"
        SET kpi_name = ?, category_l1 = ?, formula = ?, unit = ?,
            description = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (name, category, formula, unit, description, kpi_id),
    )
    conn.commit()
    return get_user_kpi(conn, kpi_id) or {}


def delete_user_kpi(conn: sqlite3.Connection, kpi_id: int) -> bool:
    cur = conn.execute(f'DELETE FROM "{USER_KPI_TABLE}" WHERE id = ?', (kpi_id,))
    conn.commit()
    return cur.rowcount > 0


def user_kpi_defs_map(conn: sqlite3.Connection | None = None) -> dict[str, str]:
    rows = list_user_kpis(conn) if conn is None else [
        _row_to_dict(r)
        for r in conn.execute(
            f'SELECT kpi_name, formula FROM "{USER_KPI_TABLE}"'
        ).fetchall()
    ]
    return {str(r["kpi_name"]): str(r["formula"] or "") for r in rows if str(r.get("kpi_name") or "").strip()}


def formula_tokens(formula: str) -> list[str]:
    text = str(formula or "")
    reserved = {"SUM", "AVG", "measurement_period_sec"}
    tokens: list[str] = []
    for match in _FORMULA_TOKEN_RE.finditer(text):
        token = match.group(0)
        upper = token.upper()
        if upper in reserved:
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens


def formula_to_sql_preview(formula: str, kpi_name: str = "my_kpi") -> str:
    """Render a readable SQL-style preview from the user formula."""
    expr = str(formula or "").strip()
    safe_name = re.sub(r"[^\w\s-]", "", str(kpi_name or "my_kpi")).strip() or "my_kpi"
    safe_name = safe_name.replace(" ", "_")

    def agg_to_sql(match: re.Match) -> str:
        fn = match.group(1).upper()
        pattern = match.group(2).strip().replace("*", "%")
        if fn == "SUM":
            return f"SUM(CASE WHEN kpi_name LIKE '{pattern}' THEN kpi_value ELSE 0 END)"
        return f"AVG(CASE WHEN kpi_name LIKE '{pattern}' THEN kpi_value END)"

    sql_expr = _AGG_CALL_RE.sub(agg_to_sql, expr)
    sql_expr = sql_expr.replace("measurement_period_sec", "gp_seconds")

    counter_tokens = [t for t in formula_tokens(expr) if t != "measurement_period_sec"]
    pivot_parts = []
    for token in counter_tokens:
        if "*" in token:
            continue
        pivot_parts.append(
            f"MAX(CASE WHEN kpi_name = '{token}' THEN kpi_value END) AS \"{token}\""
        )
    pivot_sql = ",\n       ".join(pivot_parts) if pivot_parts else "kpi_name, kpi_value"

    return (
        f"SELECT\n"
        f"    unique_id,\n"
        f"    timestamp,\n"
        f"    {sql_expr} AS \"{safe_name}\"\n"
        f"FROM (\n"
        f"    SELECT unique_id, timestamp, gp_seconds,\n"
        f"           {pivot_sql}\n"
        f"    FROM FEMTO_HOURLY_VALUES v\n"
        f"    JOIN FEMTO_HOURLY h USING (unique_id, timestamp)\n"
        f"    WHERE unique_id = :device_id\n"
        f"      AND timestamp BETWEEN :from_ts AND :to_ts\n"
        f"    GROUP BY unique_id, timestamp\n"
        f") counters\n"
        f"ORDER BY timestamp;"
    )


def validate_formula(
    formula: str,
    known_counters: set[str] | list[str] | None = None,
) -> dict:
    text = str(formula or "").strip()
    errors: list[str] = []
    warnings: list[str] = []
    if not text:
        errors.append("Formula cannot be empty.")
    if len(text) > 2000:
        errors.append("Formula is too long (max 2000 characters).")
    if re.search(r"[;\"'`]|--|/\*|\*/", text):
        errors.append("Only counter math is allowed (no SQL keywords or quotes).")
    allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_().+-*/%, \t\n")
    if any(ch not in allowed_chars for ch in text):
        errors.append("Formula contains unsupported characters.")

    known = {str(c).strip() for c in (known_counters or []) if str(c).strip()}
    tokens = formula_tokens(text)
    unknown = []
    for token in tokens:
        if token == "measurement_period_sec":
            continue
        if "*" in token:
            if known:
                pattern = re.compile("^" + re.escape(token).replace(r"\*", ".*") + "$")
                if not any(pattern.match(c) for c in known):
                    unknown.append(token)
            continue
        if known and token not in known:
            unknown.append(token)
    if unknown:
        warnings.append(f"Unknown counter(s): {', '.join(sorted(set(unknown))[:8])}")

    paren_balance = 0
    for ch in text:
        if ch == "(":
            paren_balance += 1
        elif ch == ")":
            paren_balance -= 1
        if paren_balance < 0:
            errors.append("Unbalanced parentheses.")
            break
    if paren_balance > 0:
        errors.append("Unbalanced parentheses.")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "tokens": tokens,
        "sql_preview": formula_to_sql_preview(text) if text and not errors else "",
    }


def _row_to_dict(row: sqlite3.Row | dict | None) -> dict:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return {k: row[k] for k in row.keys()}
