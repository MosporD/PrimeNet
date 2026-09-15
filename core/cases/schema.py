"""SQLite schema for optimization cases."""

from __future__ import annotations

from core.cases import config
from core.cases.db import connect


TABLES_SQL = """
CREATE TABLE IF NOT EXISTS opt_cases (
    case_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'open',
    severity TEXT NOT NULL DEFAULT 'Medium',
    score REAL NOT NULL DEFAULT 0,
    impact_score REAL NOT NULL DEFAULT 0,
    category TEXT NOT NULL DEFAULT '',
    source_module TEXT NOT NULL DEFAULT '',
    source_issue_id TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    vendor TEXT NOT NULL DEFAULT '',
    technology TEXT NOT NULL DEFAULT '',
    area TEXT NOT NULL DEFAULT '',
    site_id TEXT NOT NULL DEFAULT '',
    ticket_id TEXT NOT NULL DEFAULT '',
    owner TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    recommendation TEXT NOT NULL DEFAULT '',
    proposed_change TEXT NOT NULL DEFAULT '',
    execution_ref TEXT NOT NULL DEFAULT '',
    narrative TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    cells_json TEXT NOT NULL DEFAULT '[]',
    selection_json TEXT NOT NULL DEFAULT '{}',
    scorecard_json TEXT NOT NULL DEFAULT '{}',
    checklist_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS opt_case_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES opt_cases(case_id)
);

CREATE TABLE IF NOT EXISTS selection_contexts (
    username TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'cells',
    payload_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

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

INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_opt_cases_state ON opt_cases(state);
CREATE INDEX IF NOT EXISTS idx_opt_cases_owner ON opt_cases(owner);
CREATE INDEX IF NOT EXISTS idx_opt_cases_updated ON opt_cases(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_opt_cases_source_issue ON opt_cases(source_issue_id);
CREATE INDEX IF NOT EXISTS idx_opt_cases_impact ON opt_cases(impact_score DESC);
CREATE INDEX IF NOT EXISTS idx_opt_case_events_case ON opt_case_events(case_id, created_at);
"""

_MIGRATE_COLS = (
    ("impact_score", "REAL NOT NULL DEFAULT 0"),
    ("ticket_id", "TEXT NOT NULL DEFAULT ''"),
    ("checklist_json", "TEXT NOT NULL DEFAULT '{}'"),
)


def init_schema() -> None:
    config.CASES_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(TABLES_SQL)
        # Additive migrations for DBs created before new columns (before indexes that need them)
        existing = {
            str(r[1])
            for r in conn.execute("PRAGMA table_info(opt_cases)").fetchall()
        }
        for col, decl in _MIGRATE_COLS:
            if col not in existing:
                conn.execute(f"ALTER TABLE opt_cases ADD COLUMN {col} {decl}")
        conn.executescript(INDEXES_SQL)
        conn.commit()
