"""Trusted treatment library — outcomes from case scorecards."""

from __future__ import annotations

import json
from typing import Any

from core.cases.db import connect, execute, fetchall, fetchone
from core.cases.schema import init_schema
from core.radio.scoring import utc_now_iso


def _dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def ensure_treatments_table() -> None:
    init_schema()
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS opt_treatments (
                treatment_key TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                improve_count INTEGER NOT NULL DEFAULT 0,
                worsen_count INTEGER NOT NULL DEFAULT 0,
                flat_count INTEGER NOT NULL DEFAULT 0,
                inconclusive_count INTEGER NOT NULL DEFAULT 0,
                last_verdict TEXT NOT NULL DEFAULT '',
                meta_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.commit()


def treatment_key(title: str, category: str = "") -> str:
    raw = f"{category}|{title}".strip().lower()
    return raw[:180] or "unknown"


def record_outcome(
    *,
    title: str,
    category: str = "",
    verdict: str = "",
    meta: dict | None = None,
) -> dict:
    ensure_treatments_table()
    key = treatment_key(title, category)
    verdict_n = str(verdict or "inconclusive").strip().lower()
    col = {
        "improve": "improve_count",
        "worsen": "worsen_count",
        "flat": "flat_count",
    }.get(verdict_n, "inconclusive_count")
    now = utc_now_iso()
    with connect() as conn:
        row = fetchone(conn, "SELECT * FROM opt_treatments WHERE treatment_key = ?", (key,))
        if not row:
            execute(
                conn,
                f"""
                INSERT INTO opt_treatments (
                    treatment_key, title, category, {col}, last_verdict, meta_json, updated_at
                ) VALUES (?, ?, ?, 1, ?, ?, ?)
                """,
                (key, title or key, category or "", verdict_n, _dumps(meta or {}), now),
            )
        else:
            execute(
                conn,
                f"""
                UPDATE opt_treatments
                SET {col} = {col} + 1,
                    last_verdict = ?,
                    title = ?,
                    category = ?,
                    meta_json = ?,
                    updated_at = ?
                WHERE treatment_key = ?
                """,
                (verdict_n, title or row["title"], category or row["category"], _dumps(meta or {}), now, key),
            )
        conn.commit()
        out = fetchone(conn, "SELECT * FROM opt_treatments WHERE treatment_key = ?", (key,))
    return dict(out) if out else {}


def list_trusted(*, min_improve: int = 3, limit: int = 50) -> list[dict]:
    ensure_treatments_table()
    with connect() as conn:
        rows = fetchall(
            conn,
            """
            SELECT * FROM opt_treatments
            WHERE improve_count >= ?
            ORDER BY improve_count DESC, worsen_count ASC
            LIMIT ?
            """,
            (max(1, int(min_improve)), max(1, min(int(limit), 200))),
        )
    return [dict(r) for r in rows]


def suggest_for(title: str, category: str = "") -> dict | None:
    ensure_treatments_table()
    key = treatment_key(title, category)
    with connect() as conn:
        row = fetchone(conn, "SELECT * FROM opt_treatments WHERE treatment_key = ?", (key,))
    if not row:
        return None
    d = dict(row)
    total = int(d.get("improve_count") or 0) + int(d.get("worsen_count") or 0) + int(d.get("flat_count") or 0)
    d["trusted"] = int(d.get("improve_count") or 0) >= 3 and int(d.get("improve_count") or 0) > int(d.get("worsen_count") or 0)
    d["sample_size"] = total
    return d
