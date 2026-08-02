"""PostgreSQL connections for the PM warehouse (schema ``pm``).

The activation gate in ``core/activation_gate.py`` monkeypatches only
``sqlite3.connect``; psycopg is invisible to it. Every warehouse connection
therefore calls ``require_activation()`` explicitly so the licence lock covers
the warehouse exactly as it covers the SQLite databases.
"""

from __future__ import annotations

import os

import psycopg
from psycopg import Connection


def _dsn() -> str:
    dsn = (os.getenv("NCM_PG_DSN") or "").strip()
    if dsn:
        return dsn
    host = os.getenv("NCM_PG_HOST", "127.0.0.1")
    port = os.getenv("NCM_PG_PORT", "5432")
    db = os.getenv("NCM_PG_DB", "pm_pilot")
    user = os.getenv("NCM_PG_USER", "primenet")
    pw = os.getenv("NCM_PG_PASSWORD", "primenet_pilot")
    return f"host={host} port={port} dbname={db} user={user} password={pw}"


def _require_activation() -> None:
    try:
        from core.activation_gate import require_activation
    except ImportError:  # standalone use outside the repo
        return
    require_activation()


def connect(autocommit: bool = False) -> Connection:
    _require_activation()
    conn = psycopg.connect(_dsn(), autocommit=autocommit)
    conn.execute("SET search_path TO pm, public")
    return conn
