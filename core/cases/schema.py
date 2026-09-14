"""SQLite schema for optimization cases."""

from __future__ import annotations

from core.cases import config
from core.cases.db import connect


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS opt_cases (
    case_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'open',
    severity TEXT NOT NULL DEFAULT 'Medium',
    score REAL NOT NULL DEFAULT 0,
    category TEXT NOT NULL DEFAULT '',
    source_module TEXT NOT NULL DEFAULT '',
    source_issue_id TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    vendor TEXT NOT NULL DEFAULT '',
    technology TEXT NOT NULL DEFAULT '',
    area TEXT NOT NULL DEFAULT '',
    site_id TEXT NOT NULL DEFAULT '',
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
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    closed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_opt_cases_state ON opt_cases(state);
CREATE INDEX IF NOT EXISTS idx_opt_cases_owner ON opt_cases(owner);
CREATE INDEX IF NOT EXISTS idx_opt_cases_updated ON opt_cases(updated_at DESC);

CREATE TABLE IF NOT EXISTS opt_case_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES opt_cases(case_id)
);

CREATE INDEX IF NOT EXISTS idx_opt_case_events_case ON opt_case_events(case_id, created_at);

CREATE TABLE IF NOT EXISTS selection_contexts (
    username TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'cells',
    payload_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);
"""


def init_schema() -> None:
    config.CASES_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
