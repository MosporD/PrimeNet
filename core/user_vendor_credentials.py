"""Per-user vendor CM credentials (Nokia MantaRay / Huawei U2020) for RET management."""

from __future__ import annotations

import base64
import hashlib
import os
import sqlite3
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from database_enhanced import get_db
from db.runtime import execute_query

VENDORS = frozenset({'nokia', 'huawei'})


def _resolve_app_secret() -> str:
    """Match Flask session secret resolution in app.py (env first, then app config)."""
    secret = (os.getenv('FLASK_SECRET_KEY') or os.getenv('SECRET_KEY') or '').strip()
    if secret:
        return secret
    try:
        from flask import current_app

        cfg_secret = current_app.config.get('SECRET_KEY')
        if cfg_secret:
            return str(cfg_secret).strip()
    except RuntimeError:
        pass
    return ''


def _fernet() -> Fernet:
    secret = _resolve_app_secret()
    if not secret:
        raise RuntimeError(
            'Application secret is not configured. Set FLASK_SECRET_KEY in .env '
            'so vendor credentials can be stored securely across restarts.'
        )
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def _encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def _decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError('Stored vendor credential could not be decrypted.') from exc


def ensure_user_vendor_credentials_schema(conn: sqlite3.Connection | None = None) -> None:
    close_after = False
    if conn is None:
        conn = get_db()
        close_after = True
    if not isinstance(conn, sqlite3.Connection):
        if close_after:
            conn.close()
        return
    conn.execute('''
        CREATE TABLE IF NOT EXISTS user_vendor_credentials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            vendor TEXT NOT NULL,
            username TEXT NOT NULL,
            password_encrypted TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, vendor),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_user_vendor_credentials_user '
        'ON user_vendor_credentials(user_id)'
    )
    conn.commit()
    if close_after:
        conn.close()


def get_user_vendor_credentials(user_id: int, vendor: str) -> dict[str, str] | None:
    vendor = (vendor or '').strip().lower()
    if vendor not in VENDORS:
        raise ValueError(f'Unsupported vendor: {vendor}')
    conn = get_db()
    ensure_user_vendor_credentials_schema(conn if isinstance(conn, sqlite3.Connection) else None)
    row = execute_query(conn, '''
        SELECT username, password_encrypted
        FROM user_vendor_credentials
        WHERE user_id = ? AND vendor = ?
    ''', (user_id, vendor)).fetchone()
    conn.close()
    if not row:
        return None
    username = str(row['username'] if isinstance(row, dict) else row[0]).strip()
    encrypted = str(row['password_encrypted'] if isinstance(row, dict) else row[1]).strip()
    if not username or not encrypted:
        return None
    return {
        'username': username,
        'password': _decrypt(encrypted),
    }


def save_user_vendor_credentials(
    user_id: int,
    vendor: str,
    username: str,
    password: str,
) -> None:
    vendor = (vendor or '').strip().lower()
    if vendor not in VENDORS:
        raise ValueError(f'Unsupported vendor: {vendor}')
    username = (username or '').strip()
    password = password or ''
    if not username:
        raise ValueError('Username is required')
    if not password:
        raise ValueError('Password is required')

    conn = get_db()
    ensure_user_vendor_credentials_schema(conn if isinstance(conn, sqlite3.Connection) else None)
    execute_query(conn, '''
        INSERT INTO user_vendor_credentials (user_id, vendor, username, password_encrypted)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, vendor) DO UPDATE SET
            username = excluded.username,
            password_encrypted = excluded.password_encrypted,
            updated_at = CURRENT_TIMESTAMP
    ''', (user_id, vendor, username, _encrypt(password)))
    conn.commit()
    conn.close()


def delete_user_vendor_credentials(user_id: int, vendor: str) -> bool:
    vendor = (vendor or '').strip().lower()
    if vendor not in VENDORS:
        raise ValueError(f'Unsupported vendor: {vendor}')
    conn = get_db()
    ensure_user_vendor_credentials_schema(conn if isinstance(conn, sqlite3.Connection) else None)
    cur = execute_query(conn, '''
        DELETE FROM user_vendor_credentials WHERE user_id = ? AND vendor = ?
    ''', (user_id, vendor))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


def list_user_vendor_credential_status(user_id: int) -> dict[str, dict[str, Any]]:
    conn = get_db()
    ensure_user_vendor_credentials_schema(conn if isinstance(conn, sqlite3.Connection) else None)
    rows = execute_query(conn, '''
        SELECT vendor, username, updated_at
        FROM user_vendor_credentials
        WHERE user_id = ?
    ''', (user_id,)).fetchall()
    conn.close()

    status = {
        'nokia': {'configured': False, 'username': '', 'updated_at': None},
        'huawei': {'configured': False, 'username': '', 'updated_at': None},
    }
    for row in rows:
        item = dict(row) if not isinstance(row, dict) else row
        vendor = str(item.get('vendor') or '').lower()
        if vendor not in status:
            continue
        status[vendor] = {
            'configured': True,
            'username': str(item.get('username') or '').strip(),
            'updated_at': item.get('updated_at'),
        }
    return status
