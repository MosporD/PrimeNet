"""Marketing Portal storage.

Portal-owned SQLite database. Per NexusCore architecture rule 4 no other
portal reads this file, and this portal reads no other portal's store.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator

from .config import database_path

_INIT_LOCK = threading.Lock()
_initialised_for: str | None = None

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS portal_user_role (
    identity_user_id TEXT PRIMARY KEY,
    username         TEXT,
    role             TEXT NOT NULL,
    assigned_by      TEXT,
    assigned_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_event (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    actor       TEXT,
    actor_role  TEXT,
    action      TEXT NOT NULL,
    entity_type TEXT,
    entity_id   TEXT,
    summary     TEXT,
    detail      TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_event (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_event (occurred_at DESC);

CREATE TABLE IF NOT EXISTS offer (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    code           TEXT NOT NULL UNIQUE,
    name           TEXT NOT NULL,
    family         TEXT NOT NULL,
    description    TEXT,
    state          TEXT NOT NULL DEFAULT 'draft',
    price_amount   REAL,
    price_currency TEXT,
    price_period   TEXT,
    promo_amount   REAL,
    promo_ends_on  TEXT,
    commitment_months INTEGER,
    valid_from     TEXT,
    valid_to       TEXT,
    eligibility    TEXT,
    terms_url      TEXT,
    owner          TEXT,
    created_at     TEXT NOT NULL,
    created_by     TEXT,
    updated_at     TEXT NOT NULL,
    updated_by     TEXT
);
CREATE INDEX IF NOT EXISTS idx_offer_state ON offer (state);
CREATE INDEX IF NOT EXISTS idx_offer_family ON offer (family);

CREATE TABLE IF NOT EXISTS segment (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    definition  TEXT NOT NULL,
    refresh     TEXT NOT NULL DEFAULT 'manual',
    owner       TEXT,
    archived    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    created_by  TEXT,
    updated_at  TEXT NOT NULL,
    updated_by  TEXT
);
CREATE INDEX IF NOT EXISTS idx_segment_archived ON segment (archived);

CREATE TABLE IF NOT EXISTS campaign (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    code          TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    objective     TEXT NOT NULL,
    state         TEXT NOT NULL DEFAULT 'draft',
    description   TEXT,
    segment_id    INTEGER REFERENCES segment (id) ON DELETE SET NULL,
    holdout_pct   REAL NOT NULL DEFAULT 0,
    budget_amount REAL,
    budget_currency TEXT,
    starts_on     TEXT,
    ends_on       TEXT,
    owner         TEXT,
    created_at    TEXT NOT NULL,
    created_by    TEXT,
    updated_at    TEXT NOT NULL,
    updated_by    TEXT
);
CREATE INDEX IF NOT EXISTS idx_campaign_state ON campaign (state);
CREATE INDEX IF NOT EXISTS idx_campaign_dates ON campaign (starts_on, ends_on);

CREATE TABLE IF NOT EXISTS campaign_channel (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL REFERENCES campaign (id) ON DELETE CASCADE,
    channel     TEXT NOT NULL,
    template_ref TEXT,
    send_window TEXT,
    notes       TEXT,
    UNIQUE (campaign_id, channel)
);

CREATE TABLE IF NOT EXISTS campaign_offer (
    campaign_id INTEGER NOT NULL REFERENCES campaign (id) ON DELETE CASCADE,
    offer_id    INTEGER NOT NULL REFERENCES offer (id) ON DELETE CASCADE,
    PRIMARY KEY (campaign_id, offer_id)
);

CREATE TABLE IF NOT EXISTS consent_record (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    identifier_type TEXT NOT NULL,
    identifier      TEXT NOT NULL,
    channel         TEXT NOT NULL,
    status          TEXT NOT NULL,
    source          TEXT NOT NULL,
    evidence_ref    TEXT,
    captured_at     TEXT NOT NULL,
    expires_at      TEXT,
    notes           TEXT,
    recorded_at     TEXT NOT NULL,
    recorded_by     TEXT,
    UNIQUE (identifier_type, identifier, channel)
);
CREATE INDEX IF NOT EXISTS idx_consent_identifier ON consent_record (identifier);
CREATE INDEX IF NOT EXISTS idx_consent_status ON consent_record (status);

CREATE TABLE IF NOT EXISTS suppression_entry (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    identifier_type TEXT NOT NULL,
    identifier      TEXT NOT NULL,
    scope           TEXT NOT NULL DEFAULT 'global',
    scope_ref       TEXT,
    reason          TEXT NOT NULL,
    notes           TEXT,
    added_at        TEXT NOT NULL,
    added_by        TEXT,
    expires_at      TEXT,
    released_at     TEXT,
    released_by     TEXT
);
CREATE INDEX IF NOT EXISTS idx_suppression_identifier ON suppression_entry (identifier);
CREATE INDEX IF NOT EXISTS idx_suppression_active ON suppression_entry (released_at);

CREATE TABLE IF NOT EXISTS contact_policy (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL UNIQUE,
    channel       TEXT NOT NULL DEFAULT 'all',
    max_contacts  INTEGER NOT NULL,
    window_days   INTEGER NOT NULL,
    quiet_from    TEXT,
    quiet_to      TEXT,
    timezone      TEXT,
    applies_to    TEXT NOT NULL DEFAULT 'all',
    active        INTEGER NOT NULL DEFAULT 1,
    notes         TEXT,
    created_at    TEXT NOT NULL,
    created_by    TEXT,
    updated_at    TEXT NOT NULL,
    updated_by    TEXT
);
"""


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def init_schema(path: str | None = None) -> str:
    """Create the portal database and schema if they do not exist."""
    global _initialised_for
    target = path or database_path()
    with _INIT_LOCK:
        if _initialised_for == target:
            return target
        _ensure_parent_dir(target)
        conn = sqlite3.connect(target)
        try:
            conn.executescript(_SCHEMA)
            conn.execute(
                "INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(SCHEMA_VERSION),),
            )
            conn.commit()
        finally:
            conn.close()
        _initialised_for = target
        return target


def connect(path: str | None = None) -> sqlite3.Connection:
    """Open a connection with the portal's standard pragmas."""
    target = init_schema(path)
    conn = sqlite3.connect(target, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


@contextmanager
def cursor(path: str | None = None) -> Iterator[sqlite3.Connection]:
    """Transactional helper: commits on success, rolls back on error."""
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rows_to_dicts(rows) -> list[dict]:
    return [dict(row) for row in rows]
