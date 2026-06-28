"""
Import Femto KPI and counter catalogs into the Femto PM database.

This loads:
- FEMTO_COMPUTED_KPIS: user-defined computed KPI definitions and formulas
- FEMTO_COUNTER_CATALOG: raw counter hierarchy for L1 -> L2 -> L3 drilldown
"""

from __future__ import annotations

import csv
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sync_config import DATABASES_ROOT


FEMTO_PM_DB = Path(DATABASES_ROOT) / "cells" / "femto_pm_cells.db"
KPI_CSV = Path.home() / "Downloads" / "kpis.csv"
COUNTER_CSV = Path.home() / "Downloads" / "counters.csv"
COMPUTED_TABLE = "FEMTO_COMPUTED_KPIS"
COUNTER_TABLE = "FEMTO_COUNTER_CATALOG"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(FEMTO_PM_DB, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{COMPUTED_TABLE}" (
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
        CREATE TABLE IF NOT EXISTS "{COUNTER_TABLE}" (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            counter_name TEXT NOT NULL UNIQUE,
            l1 TEXT,
            l2 TEXT,
            l3 TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(f'CREATE INDEX IF NOT EXISTS idx_femto_counter_l123 ON "{COUNTER_TABLE}" (l1, l2, l3)')


def _read_kpis() -> list[dict]:
    rows: list[dict] = []
    with KPI_CSV.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            name = (row.get("KPI Name") or "").strip()
            if not name:
                continue
            rows.append(
                {
                    "code": (row.get("\ufeff#") or row.get("#") or "").strip(),
                    "kpi_name": name,
                    "category_l1": (row.get("Category (L1)") or "").strip(),
                    "formula": (row.get("Formula (numerator / denominator)") or "").strip(),
                    "unit": (row.get("Unit") or "").strip(),
                    "description": (row.get("Description") or "").strip(),
                }
            )
    return rows


def _read_counters() -> list[dict]:
    rows: list[dict] = []
    with COUNTER_CSV.open("r", encoding="cp1252", newline="") as fh:
        reader = csv.DictReader(fh)
        field_map = {str(k): str(k).replace("�", "—").strip() for k in (reader.fieldnames or [])}
        for row in reader:
            name = (row.get("Counter Name") or "").strip()
            if not name:
                continue
            l1_key = next((k for k, v in field_map.items() if v == "L1 — Domain (3GPP)"), "")
            l2_key = next((k for k, v in field_map.items() if v == "L2 — Feature Area"), "")
            l3_key = next((k for k, v in field_map.items() if v == "L3 — Counter Family"), "")
            rows.append(
                {
                    "counter_name": name,
                    "l1": (row.get(l1_key) or "").strip(),
                    "l2": (row.get(l2_key) or "").strip(),
                    "l3": (row.get(l3_key) or "").strip(),
                }
            )
    return rows


def main() -> int:
    if not KPI_CSV.exists():
        print(f"[error] KPI CSV not found: {KPI_CSV}")
        return 1
    if not COUNTER_CSV.exists():
        print(f"[error] Counter CSV not found: {COUNTER_CSV}")
        return 1

    kpis = _read_kpis()
    counters = _read_counters()

    FEMTO_PM_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = _conn()
    _ensure_tables(conn)
    conn.execute(f'DELETE FROM "{COMPUTED_TABLE}"')
    conn.execute(f'DELETE FROM "{COUNTER_TABLE}"')

    conn.executemany(
        f"""
        INSERT INTO "{COMPUTED_TABLE}" (code, kpi_name, category_l1, formula, unit, description, updated_at)
        VALUES (:code, :kpi_name, :category_l1, :formula, :unit, :description, CURRENT_TIMESTAMP)
        """,
        kpis,
    )
    conn.executemany(
        f"""
        INSERT INTO "{COUNTER_TABLE}" (counter_name, l1, l2, l3, updated_at)
        VALUES (:counter_name, :l1, :l2, :l3, CURRENT_TIMESTAMP)
        """,
        counters,
    )
    conn.commit()
    conn.close()

    print(f"[done] imported computed_kpis={len(kpis)} counters={len(counters)} db={FEMTO_PM_DB}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
