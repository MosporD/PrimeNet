"""SQLite persistence for license grants and revocations."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path


class LicenseStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS activations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instance_id TEXT NOT NULL,
                    issued_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    token_id TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS idx_activations_instance
                    ON activations(instance_id);

                CREATE TABLE IF NOT EXISTS revocations (
                    instance_id TEXT PRIMARY KEY,
                    revoked_at INTEGER NOT NULL,
                    reason TEXT
                );
                """
            )

    def record_activation(self, instance_id: str, expires_at: int, token_id: str) -> None:
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO activations (instance_id, issued_at, expires_at, token_id)
                VALUES (?, ?, ?, ?)
                """,
                (instance_id, now, expires_at, token_id),
            )

    def is_revoked(self, instance_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM revocations WHERE instance_id = ?",
                (instance_id,),
            ).fetchone()
        return row is not None

    def revoke(self, instance_id: str, reason: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO revocations (instance_id, revoked_at, reason)
                VALUES (?, ?, ?)
                ON CONFLICT(instance_id) DO UPDATE SET
                    revoked_at = excluded.revoked_at,
                    reason = excluded.reason
                """,
                (instance_id, int(time.time()), reason),
            )

    def unrevoke(self, instance_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM revocations WHERE instance_id = ?", (instance_id,))
