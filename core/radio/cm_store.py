"""Normalized CM snapshot/change store for radio audits."""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timezone

from sync_config import DATABASES_ROOT


RADIO_DB_DIR = os.path.join(DATABASES_ROOT, "radio")
CM_STORE_DB = os.path.join(RADIO_DB_DIR, "cm_snapshots.db")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_connection() -> sqlite3.Connection:
    os.makedirs(RADIO_DB_DIR, exist_ok=True)
    conn = sqlite3.connect(CM_STORE_DB, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS cm_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor TEXT NOT NULL,
            ne_name TEXT,
            site_id TEXT,
            cell_name TEXT,
            technology TEXT,
            mo_class TEXT NOT NULL,
            dn TEXT NOT NULL,
            parameter TEXT NOT NULL,
            value TEXT,
            extracted_at TEXT NOT NULL,
            source_run_id TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_cm_snapshot_lookup
            ON cm_snapshot (vendor, dn, mo_class, parameter, extracted_at);

        CREATE INDEX IF NOT EXISTS idx_cm_snapshot_cell
            ON cm_snapshot (cell_name, technology, vendor);

        CREATE TABLE IF NOT EXISTS cm_audit_rule (
            id TEXT PRIMARY KEY,
            vendor TEXT,
            technology TEXT,
            mo_class TEXT,
            parameter TEXT NOT NULL,
            rule_type TEXT NOT NULL,
            expected_value TEXT,
            min_value REAL,
            max_value REAL,
            severity TEXT NOT NULL DEFAULT 'Medium',
            description TEXT,
            enabled INTEGER NOT NULL DEFAULT 1
        );
        """
    )
    _ensure_rule_columns(conn)
    _seed_rules(conn)
    conn.commit()


def _ensure_rule_columns(conn: sqlite3.Connection) -> None:
    existing = {str(row[1]) for row in conn.execute("PRAGMA table_info(cm_audit_rule)")}
    extras = {
        "band": "TEXT",
        "area": "TEXT",
        "approved_by": "TEXT",
        "approved_at": "TEXT",
        "baseline": "TEXT",
        "version": "INTEGER NOT NULL DEFAULT 1",
        "updated_at": "TEXT",
    }
    for name, ddl in extras.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE cm_audit_rule ADD COLUMN {name} {ddl}")


def _seed_rules(conn: sqlite3.Connection) -> None:
    defaults = [
        ("lte-cell-admin-state", None, "4G", None, "administrativeState", "not_empty", None, None, None, "High", "LTE cell administrative state should be populated."),
        ("lte-pci-range", None, "4G", None, "pci", "range", None, 0, 503, "High", "LTE PCI should be within 0..503."),
        ("nr-pci-range", None, "5G", None, "pci", "range", None, 0, 1007, "High", "NR PCI should be within 0..1007."),
        ("antenna-azimuth-range", None, None, None, "azimuth", "range", None, 0, 359, "Medium", "Antenna azimuth should be 0..359 degrees."),
        ("tilt-range", None, None, None, "electricalTilt", "range", None, -10, 20, "Medium", "Electrical tilt should be within an operational range."),
    ]
    conn.executemany(
        """
        INSERT OR IGNORE INTO cm_audit_rule
            (id, vendor, technology, mo_class, parameter, rule_type, expected_value, min_value, max_value, severity, description)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        defaults,
    )


def latest_snapshot_rows(limit: int = 5000) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            WITH latest AS (
                SELECT vendor, dn, mo_class, parameter, MAX(extracted_at) AS extracted_at
                FROM cm_snapshot
                GROUP BY vendor, dn, mo_class, parameter
            )
            SELECT s.*
            FROM cm_snapshot s
            JOIN latest l
              ON l.vendor = s.vendor
             AND l.dn = s.dn
             AND l.mo_class = s.mo_class
             AND l.parameter = s.parameter
             AND l.extracted_at = s.extracted_at
            ORDER BY s.extracted_at DESC
            LIMIT ?
            """,
            (max(1, limit),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_rules(*, include_disabled: bool = False) -> list[dict]:
    conn = get_connection()
    try:
        sql = "SELECT * FROM cm_audit_rule"
        if not include_disabled:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY severity, id"
        return [dict(r) for r in conn.execute(sql)]
    finally:
        conn.close()


def upsert_rule(payload: dict, *, actor: str = "") -> dict:
    rule_id = str(payload.get("id") or "").strip()
    if not rule_id:
        slug = "-".join(
            part for part in (
                str(payload.get("technology") or "any").lower(),
                str(payload.get("band") or "").lower(),
                str(payload.get("area") or "").lower(),
                str(payload.get("parameter") or "param").lower(),
            ) if part
        )
        rule_id = re.sub(r"[^a-z0-9]+", "-", slug).strip("-") or "rule"
    now = utc_now_iso()
    conn = get_connection()
    try:
        existing = conn.execute("SELECT version FROM cm_audit_rule WHERE id = ?", (rule_id,)).fetchone()
        version = int(existing["version"] or 1) + 1 if existing else 1
        min_value = payload.get("min_value")
        max_value = payload.get("max_value")
        try:
            min_value = float(min_value) if min_value not in (None, "") else None
        except (TypeError, ValueError):
            min_value = None
        try:
            max_value = float(max_value) if max_value not in (None, "") else None
        except (TypeError, ValueError):
            max_value = None
        conn.execute(
            """
            INSERT INTO cm_audit_rule (
                id, vendor, technology, mo_class, parameter, rule_type,
                expected_value, min_value, max_value, severity, description,
                enabled, band, area, approved_by, approved_at, baseline, version, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                vendor=excluded.vendor,
                technology=excluded.technology,
                mo_class=excluded.mo_class,
                parameter=excluded.parameter,
                rule_type=excluded.rule_type,
                expected_value=excluded.expected_value,
                min_value=excluded.min_value,
                max_value=excluded.max_value,
                severity=excluded.severity,
                description=excluded.description,
                enabled=excluded.enabled,
                band=excluded.band,
                area=excluded.area,
                baseline=excluded.baseline,
                version=excluded.version,
                updated_at=excluded.updated_at,
                approved_by=NULL,
                approved_at=NULL
            """,
            (
                rule_id,
                payload.get("vendor") or None,
                payload.get("technology") or None,
                payload.get("mo_class") or None,
                str(payload.get("parameter") or "").strip(),
                str(payload.get("rule_type") or "equals").strip(),
                payload.get("expected_value"),
                min_value,
                max_value,
                str(payload.get("severity") or "Medium"),
                payload.get("description"),
                1 if payload.get("enabled", True) else 0,
                payload.get("band") or None,
                payload.get("area") or None,
                None,
                None,
                payload.get("baseline") or None,
                version,
                now,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM cm_audit_rule WHERE id = ?", (rule_id,)).fetchone()
        return dict(row) if row else {"id": rule_id, "updated_by": actor}
    finally:
        conn.close()


def approve_rule(rule_id: str, *, actor: str, baseline: str = "") -> dict | None:
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE cm_audit_rule
            SET approved_by = ?, approved_at = ?, baseline = COALESCE(NULLIF(?, ''), baseline)
            WHERE id = ?
            """,
            (actor, utc_now_iso(), baseline, rule_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM cm_audit_rule WHERE id = ?", (rule_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


_BAND_RE = re.compile(
    r"\b(L18\+|L18NEW|L18PLUS|L18|L21|L26|L9|L8|L7|N78|N41|N28|N1)\b",
    re.IGNORECASE,
)


def infer_band(cell_name: str = "", technology: str = "") -> str:
    match = _BAND_RE.search(str(cell_name or ""))
    if not match:
        return ""
    token = match.group(1).upper().replace("L18NEW", "L18+").replace("L18PLUS", "L18+")
    return token


def parameter_network_values(
    parameter: str,
    *,
    mo_class: str = "",
    vendor: str = "",
    default_value: str = "",
    limit: int = 4000,
) -> dict:
    """Latest snapshot values for one parameter, with deviation vs dictionary default."""
    param = str(parameter or "").strip()
    if not param:
        return {"parameter": "", "rows": [], "distribution": [], "deviations": [], "total": 0}
    conn = get_connection()
    try:
        clauses = ["s.parameter = ?"]
        args: list = [param]
        if mo_class:
            clauses.append("(s.mo_class = ? OR s.mo_class LIKE ? OR s.mo_class LIKE ?)")
            args.extend([mo_class, f"%/{mo_class}", f"%:{mo_class}"])
        if vendor and vendor.lower() != "all":
            clauses.append("LOWER(s.vendor) = ?")
            args.append(vendor.lower())
        where = " AND ".join(clauses)
        rows = conn.execute(
            f"""
            WITH latest AS (
                SELECT vendor, dn, mo_class, parameter, MAX(extracted_at) AS extracted_at
                FROM cm_snapshot
                GROUP BY vendor, dn, mo_class, parameter
            )
            SELECT s.*
            FROM cm_snapshot s
            JOIN latest l
              ON l.vendor = s.vendor
             AND l.dn = s.dn
             AND l.mo_class = s.mo_class
             AND l.parameter = s.parameter
             AND l.extracted_at = s.extracted_at
            WHERE {where}
            ORDER BY s.extracted_at DESC
            LIMIT ?
            """,
            (*args, max(1, int(limit))),
        ).fetchall()
        items = [dict(r) for r in rows]
    finally:
        conn.close()

    counts: dict[str, int] = {}
    deviations: list[dict] = []
    default_text = str(default_value or "").strip()
    for item in items:
        value = "" if item.get("value") is None else str(item.get("value"))
        counts[value] = counts.get(value, 0) + 1
        if default_text and value != default_text:
            deviations.append({
                "cell_name": item.get("cell_name") or "",
                "site_id": item.get("site_id") or "",
                "dn": item.get("dn") or "",
                "vendor": item.get("vendor") or "",
                "technology": item.get("technology") or "",
                "value": value,
                "default": default_text,
            })
    distribution = sorted(
        ({"value": value, "count": count} for value, count in counts.items()),
        key=lambda row: -row["count"],
    )
    return {
        "parameter": param,
        "mo_class": mo_class,
        "default_value": default_text,
        "total": len(items),
        "distribution": distribution[:40],
        "deviations": deviations[:200],
        "deviation_count": len(deviations),
        "latest": items[0].get("extracted_at") if items else None,
    }


def detect_changes(limit: int = 500) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT vendor, dn, mo_class, parameter, cell_name, site_id, technology,
                   value, extracted_at
            FROM cm_snapshot
            ORDER BY vendor, dn, mo_class, parameter, extracted_at DESC
            """
        ).fetchall()
    finally:
        conn.close()

    grouped: dict[tuple, list[dict]] = {}
    for row in rows:
        item = dict(row)
        key = (item["vendor"], item["dn"], item["mo_class"], item["parameter"])
        grouped.setdefault(key, []).append(item)

    changes: list[dict] = []
    for key, items in grouped.items():
        if len(items) < 2:
            continue
        latest, previous = items[0], items[1]
        if str(latest.get("value")) == str(previous.get("value")):
            continue
        changes.append({
            "vendor": key[0],
            "dn": key[1],
            "mo_class": key[2],
            "parameter": key[3],
            "cell_name": latest.get("cell_name") or previous.get("cell_name"),
            "site_id": latest.get("site_id") or previous.get("site_id"),
            "technology": latest.get("technology") or previous.get("technology"),
            "old_value": previous.get("value"),
            "new_value": latest.get("value"),
            "changed_at": latest.get("extracted_at"),
            "previous_at": previous.get("extracted_at"),
        })
        if len(changes) >= limit:
            break
    return changes


def store_stats() -> dict:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS rows, COUNT(DISTINCT dn) AS dns, MAX(extracted_at) AS latest FROM cm_snapshot"
        ).fetchone()
        return dict(row) if row else {"rows": 0, "dns": 0, "latest": None}
    finally:
        conn.close()

