"""Normalized CM snapshot/change store for radio audits."""

from __future__ import annotations

import os
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
    _seed_rules(conn)
    conn.commit()


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


def list_rules() -> list[dict]:
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM cm_audit_rule WHERE enabled = 1 ORDER BY severity, id")]
    finally:
        conn.close()


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

