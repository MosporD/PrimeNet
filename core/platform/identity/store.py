"""Parameterized SQLite users/sessions for NexusCore and NexPulse.

PrimeNet continues to use ``database_enhanced`` / ``ncm_users.db``. These
helpers are for platforms that own a separate users database and cookie.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

_lock = threading.Lock()
_schema_ready: set[str] = set()


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.sha256((password + salt).encode()).hexdigest()
    return f"{salt}${pwd_hash}"


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        salt, pwd_hash = password_hash.split("$")
        test_hash = hashlib.sha256((password + salt).encode()).hexdigest()
        return test_hash == pwd_hash
    except (ValueError, AttributeError):
        return False


def _connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_schema(db_path: str) -> None:
    key = os.path.abspath(db_path)
    if key in _schema_ready:
        return
    with _lock:
        if key in _schema_ready:
            return
        conn = _connect(db_path)
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    full_name TEXT,
                    role TEXT DEFAULT 'user',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP,
                    is_active INTEGER DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    session_token TEXT UNIQUE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(session_token);
                CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
                """
            )
            conn.commit()
            _schema_ready.add(key)
        finally:
            conn.close()


def user_count(db_path: str) -> int:
    ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
        return int(row["c"] if row else 0)
    finally:
        conn.close()


def create_user(
    db_path: str,
    *,
    username: str,
    email: str,
    password: str,
    role: str = "admin",
    full_name: str | None = None,
) -> int:
    ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            """
            INSERT INTO users (username, email, password_hash, full_name, role, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (username.strip(), email.strip(), _hash_password(password), full_name, role),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def ensure_bootstrap_admin(
    db_path: str,
    *,
    username: str | None,
    password: str | None,
    email: str | None = None,
    role: str = "admin",
) -> bool:
    """Create the first admin when the DB is empty and credentials are provided."""
    ensure_schema(db_path)
    if user_count(db_path) > 0:
        return False
    username = (username or "").strip()
    password = password or ""
    if not username or not password:
        print(
            f"[WARNING] {db_path}: no users and bootstrap admin env not set — login will fail until seeded."
        )
        return False
    email = (email or f"{username}@local").strip()
    create_user(db_path, username=username, email=email, password=password, role=role)
    print(f"[OK] Bootstrapped admin '{username}' in {db_path}")
    return True


def authenticate(db_path: str, username: str, password: str) -> dict | None:
    ensure_schema(db_path)
    username = (username or "").strip()
    if not username or password is None:
        return None
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM users WHERE LOWER(username) = LOWER(?) AND is_active = 1",
            (username,),
        ).fetchall()
        candidates = [dict(r) for r in rows]
        verified = [u for u in candidates if _verify_password(password, u["password_hash"])]
        if not verified:
            return None
        exact = [u for u in verified if u.get("username") == username]
        user = exact[0] if len(exact) == 1 else verified[0]
        conn.execute(
            "UPDATE users SET last_login = ? WHERE id = ?",
            (datetime.now().isoformat(timespec="seconds"), user["id"]),
        )
        conn.commit()
        return user
    finally:
        conn.close()


def create_session(db_path: str, user_id: int) -> str:
    ensure_schema(db_path)
    token = secrets.token_urlsafe(32)
    try:
        lifetime_hours = int(os.getenv("SESSION_LIFETIME_HOURS", "2"))
    except (TypeError, ValueError):
        lifetime_hours = 2
    lifetime_hours = max(1, min(lifetime_hours, 24 * 30))
    expires_at = datetime.now() + timedelta(hours=lifetime_hours)
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO sessions (user_id, session_token, expires_at) VALUES (?, ?, ?)",
            (user_id, token, expires_at.isoformat(timespec="seconds")),
        )
        conn.commit()
        return token
    finally:
        conn.close()


def get_user_by_session(db_path: str, session_token: str | None) -> dict | None:
    if not session_token:
        return None
    ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT u.* FROM users u
            JOIN sessions s ON u.id = s.user_id
            WHERE s.session_token = ? AND s.expires_at > ? AND u.is_active = 1
            """,
            (session_token, datetime.now().isoformat(timespec="seconds")),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_session(db_path: str, session_token: str | None) -> None:
    if not session_token:
        return
    ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        conn.execute("DELETE FROM sessions WHERE session_token = ?", (session_token,))
        conn.commit()
    finally:
        conn.close()
