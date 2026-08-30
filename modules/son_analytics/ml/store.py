"""SQLite store for SON ML features, scores, and operator feedback."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone

from sync_config import DATABASES_ROOT

_ML_DIR = os.path.join(DATABASES_ROOT, "son_analytics")
_ML_DB = os.path.join(_ML_DIR, "ml.db")
_MODEL_DIR = os.path.join(_ML_DIR, "models")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def db_path() -> str:
    return _ML_DB


def model_dir() -> str:
    os.makedirs(_MODEL_DIR, exist_ok=True)
    return _MODEL_DIR


def ensure_db_dir() -> None:
    os.makedirs(_ML_DIR, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    ensure_db_dir()
    conn = sqlite3.connect(_ML_DB, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS son_ml_build (
            vendor TEXT NOT NULL,
            rat TEXT NOT NULL,
            built_at TEXT NOT NULL,
            pm_fingerprint TEXT NOT NULL,
            model_versions_json TEXT NOT NULL DEFAULT '{}',
            row_count INTEGER NOT NULL DEFAULT 0,
            score_count INTEGER NOT NULL DEFAULT 0,
            build_seconds REAL,
            PRIMARY KEY (vendor, rat)
        );

        CREATE TABLE IF NOT EXISTS son_cell_day (
            cell_name TEXT NOT NULL,
            vendor TEXT NOT NULL,
            rat TEXT NOT NULL,
            day TEXT NOT NULL,
            kpi_json TEXT NOT NULL DEFAULT '{}',
            z_json TEXT NOT NULL DEFAULT '{}',
            latitude REAL,
            longitude REAL,
            area TEXT,
            site_id TEXT,
            layer TEXT,
            nbr_count REAL,
            nbr_ho_attempts REAL,
            nbr_ho_sr REAL,
            nbr_distance_km REAL,
            nbr_missing_recip REAL,
            PRIMARY KEY (cell_name, vendor, rat, day)
        );

        CREATE INDEX IF NOT EXISTS idx_son_cell_day_lookup
            ON son_cell_day (vendor, rat, day);

        CREATE TABLE IF NOT EXISTS son_score (
            cell_name TEXT NOT NULL,
            vendor TEXT NOT NULL,
            rat TEXT NOT NULL,
            day TEXT NOT NULL,
            anomaly_score REAL,
            embedding_json TEXT NOT NULL DEFAULT '[]',
            top_kpis_json TEXT NOT NULL DEFAULT '[]',
            cause_probs_json TEXT NOT NULL DEFAULT '{}',
            graph_score REAL,
            spatial_cluster_id TEXT,
            spatial_coherence TEXT,
            model_name TEXT,
            fallback_used INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (cell_name, vendor, rat, day)
        );

        CREATE INDEX IF NOT EXISTS idx_son_score_day
            ON son_score (vendor, rat, day);

        CREATE TABLE IF NOT EXISTS son_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            rec_id TEXT NOT NULL,
            label TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS son_treatment_meta (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            trained_at TEXT,
            sample_count INTEGER NOT NULL DEFAULT 0,
            model_path TEXT,
            heuristic INTEGER NOT NULL DEFAULT 1,
            notes TEXT
        );
        """
    )


def pm_fingerprint(vendor: str, rat: str) -> str:
    import hashlib

    from modules.son_analytics.pm_helpers import PM_DATA_SCOPE, vendor_pm_sources

    parts: list[str] = []
    for _vlabel, db_path, table in vendor_pm_sources(vendor, rat, PM_DATA_SCOPE):
        if db_path and os.path.isfile(db_path):
            parts.append(f"{db_path}|{table}|{os.path.getsize(db_path)}")
        else:
            parts.append(f"{db_path}|{table}|missing")
    blob = "\n".join(sorted(parts))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def get_build_meta(vendor: str, rat: str) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM son_ml_build WHERE vendor = ? AND rat = ?",
            (vendor, rat),
        ).fetchone()
        if not row:
            return None
        meta = dict(row)
        meta["model_versions"] = json.loads(meta.pop("model_versions_json") or "{}")
        meta["is_stale"] = meta.get("pm_fingerprint") != pm_fingerprint(vendor, rat)
        return meta
    finally:
        conn.close()


def save_build_meta(
    vendor: str,
    rat: str,
    *,
    fingerprint: str,
    model_versions: dict,
    row_count: int,
    score_count: int,
    build_seconds: float,
) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO son_ml_build (
                vendor, rat, built_at, pm_fingerprint, model_versions_json,
                row_count, score_count, build_seconds
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(vendor, rat) DO UPDATE SET
                built_at = excluded.built_at,
                pm_fingerprint = excluded.pm_fingerprint,
                model_versions_json = excluded.model_versions_json,
                row_count = excluded.row_count,
                score_count = excluded.score_count,
                build_seconds = excluded.build_seconds
            """,
            (
                vendor,
                rat,
                _utc_now_iso(),
                fingerprint,
                json.dumps(model_versions),
                int(row_count),
                int(score_count),
                float(build_seconds),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def replace_cell_days(vendor: str, rat: str, rows: list[dict]) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM son_cell_day WHERE vendor = ? AND rat = ?",
            (vendor, rat),
        )
        conn.executemany(
            """
            INSERT INTO son_cell_day (
                cell_name, vendor, rat, day, kpi_json, z_json,
                latitude, longitude, area, site_id, layer,
                nbr_count, nbr_ho_attempts, nbr_ho_sr, nbr_distance_km, nbr_missing_recip
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r["cell_name"],
                    vendor,
                    rat,
                    r["day"],
                    json.dumps(r.get("kpis") or {}),
                    json.dumps(r.get("z") or {}),
                    r.get("latitude"),
                    r.get("longitude"),
                    r.get("area") or "",
                    str(r.get("site_id") or ""),
                    r.get("layer") or "",
                    r.get("nbr_count"),
                    r.get("nbr_ho_attempts"),
                    r.get("nbr_ho_sr"),
                    r.get("nbr_distance_km"),
                    r.get("nbr_missing_recip"),
                )
                for r in rows
            ],
        )
        conn.commit()
    finally:
        conn.close()


def replace_scores(vendor: str, rat: str, rows: list[dict]) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM son_score WHERE vendor = ? AND rat = ?",
            (vendor, rat),
        )
        conn.executemany(
            """
            INSERT INTO son_score (
                cell_name, vendor, rat, day, anomaly_score, embedding_json,
                top_kpis_json, cause_probs_json, graph_score,
                spatial_cluster_id, spatial_coherence, model_name, fallback_used
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r["cell_name"],
                    vendor,
                    rat,
                    r["day"],
                    r.get("anomaly_score"),
                    json.dumps(r.get("embedding") or []),
                    json.dumps(r.get("top_kpis") or []),
                    json.dumps(r.get("cause_probs") or {}),
                    r.get("graph_score"),
                    r.get("spatial_cluster_id"),
                    r.get("spatial_coherence"),
                    r.get("model_name") or "",
                    1 if r.get("fallback_used") else 0,
                )
                for r in rows
            ],
        )
        conn.commit()
    finally:
        conn.close()


def update_spatial_fields(updates: list[tuple[str, str, str, str, str]]) -> None:
    """(spatial_cluster_id, spatial_coherence, cell_name, vendor, rat) tuples."""
    if not updates:
        return
    conn = get_connection()
    try:
        conn.executemany(
            """
            UPDATE son_score
            SET spatial_cluster_id = ?, spatial_coherence = ?
            WHERE cell_name = ? AND vendor = ? AND rat = ?
            """,
            updates,
        )
        conn.commit()
    finally:
        conn.close()


def latest_day(vendor: str | None = None, rat: str | None = None) -> str | None:
    conn = get_connection()
    try:
        sql = "SELECT MAX(day) FROM son_score"
        params: list[str] = []
        if vendor and rat:
            sql += " WHERE vendor = ? AND rat = ?"
            params = [vendor, rat]
        row = conn.execute(sql, params).fetchone()
        return row[0] if row and row[0] else None
    finally:
        conn.close()


def load_latest_scores(*, vendor: str | None = None, rat: str | None = None) -> list[dict]:
    conn = get_connection()
    try:
        clauses = []
        params: list[object] = []
        if vendor:
            clauses.append("vendor = ?")
            params.append(vendor)
        if rat:
            clauses.append("rat = ?")
            params.append(rat)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"""
            SELECT s.* FROM son_score s
            JOIN (
                SELECT cell_name, vendor, rat, MAX(day) AS day
                FROM son_score
                {where}
                GROUP BY cell_name, vendor, rat
            ) m ON s.cell_name = m.cell_name AND s.vendor = m.vendor
               AND s.rat = m.rat AND s.day = m.day
        """
        rows = []
        for row in conn.execute(sql, params):
            item = dict(row)
            item["embedding"] = json.loads(item.pop("embedding_json") or "[]")
            item["top_kpis"] = json.loads(item.pop("top_kpis_json") or "[]")
            item["cause_probs"] = json.loads(item.pop("cause_probs_json") or "{}")
            item["fallback_used"] = bool(item.get("fallback_used"))
            rows.append(item)
        return rows
    finally:
        conn.close()


def load_latest_cell_days(*, vendor: str | None = None, rat: str | None = None) -> list[dict]:
    conn = get_connection()
    try:
        clauses = []
        params: list[object] = []
        if vendor:
            clauses.append("vendor = ?")
            params.append(vendor)
        if rat:
            clauses.append("rat = ?")
            params.append(rat)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"""
            SELECT d.* FROM son_cell_day d
            JOIN (
                SELECT cell_name, vendor, rat, MAX(day) AS day
                FROM son_cell_day
                {where}
                GROUP BY cell_name, vendor, rat
            ) m ON d.cell_name = m.cell_name AND d.vendor = m.vendor
               AND d.rat = m.rat AND d.day = m.day
        """
        out = []
        for r in conn.execute(sql, params):
            item = dict(r)
            item["kpis"] = json.loads(item.pop("kpi_json") or "{}")
            item["z"] = json.loads(item.pop("z_json") or "{}")
            out.append(item)
        return out
    finally:
        conn.close()


def load_cell_history(cell_name: str, vendor: str, rat: str) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT day, kpi_json FROM son_cell_day
            WHERE cell_name = ? AND vendor = ? AND rat = ?
            ORDER BY day
            """,
            (cell_name, vendor, rat),
        ).fetchall()
        out = []
        for r in rows:
            out.append({"day": r["day"], "kpis": json.loads(r["kpi_json"] or "{}")})
        return out
    finally:
        conn.close()


def store_status() -> dict:
    conn = get_connection()
    try:
        builds = [dict(r) for r in conn.execute("SELECT * FROM son_ml_build").fetchall()]
        score_n = conn.execute("SELECT COUNT(*) FROM son_score").fetchone()[0]
        day = conn.execute("SELECT MAX(day) FROM son_score").fetchone()[0]
        treat = conn.execute("SELECT * FROM son_treatment_meta WHERE id = 1").fetchone()
        latest_built = max((b.get("built_at") or "" for b in builds), default="")
        stale = False
        for b in builds:
            try:
                if b.get("pm_fingerprint") != pm_fingerprint(b["vendor"], b["rat"]):
                    stale = True
            except Exception:
                stale = True
        return {
            "available": bool(builds) and int(score_n or 0) > 0,
            "built_at": latest_built or None,
            "latest_day": day,
            "score_count": int(score_n or 0),
            "is_stale": stale,
            "builds": builds,
            "treatment": dict(treat) if treat else None,
        }
    finally:
        conn.close()


def save_feedback(username: str, rec_id: str, label: str) -> dict:
    token = str(label or "").strip().lower()
    if token not in ("up", "down"):
        raise ValueError("label must be up or down")
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO son_feedback (username, rec_id, label, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (str(username or "").strip() or "unknown", str(rec_id or "").strip(), token, _utc_now_iso()),
        )
        conn.commit()
        return {"ok": True, "label": token}
    finally:
        conn.close()


def save_treatment_meta(*, sample_count: int, model_path: str | None, heuristic: bool, notes: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO son_treatment_meta (id, trained_at, sample_count, model_path, heuristic, notes)
            VALUES (1, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                trained_at = excluded.trained_at,
                sample_count = excluded.sample_count,
                model_path = excluded.model_path,
                heuristic = excluded.heuristic,
                notes = excluded.notes
            """,
            (_utc_now_iso(), int(sample_count), model_path, 1 if heuristic else 0, notes),
        )
        conn.commit()
    finally:
        conn.close()


def load_treatment_meta() -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM son_treatment_meta WHERE id = 1").fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
