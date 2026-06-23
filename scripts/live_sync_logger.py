"""
Live sync logger for a separate terminal window.

Polls sync_log and prints new entries as they are written by scheduler/jobs.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sync_config import NCMUSERS_DB


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(NCMUSERS_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    return conn


def _last_id(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT COALESCE(MAX(id), 0) AS n FROM sync_log").fetchone()
        return int((row["n"] if row else 0) or 0)
    except Exception:
        return 0


def main() -> int:
    interval = 1.5
    try:
        interval = max(0.5, float(os.getenv("SYNC_LOGGER_POLL_SEC", "1.5")))
    except Exception:
        interval = 1.5

    print("=" * 72)
    print("PrimeNet Live Sync Logger")
    print(f"DB: {NCMUSERS_DB}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 72)

    conn = _connect()
    last_seen = _last_id(conn)

    while True:
        try:
            rows = conn.execute(
                """
                SELECT id, started_at, sync_type, technology, status, rows_affected, message
                FROM sync_log
                WHERE id > ?
                ORDER BY id ASC
                """,
                (last_seen,),
            ).fetchall()
            for row in rows:
                last_seen = int(row["id"] or last_seen)
                print(
                    f"[{row['started_at']}] #{row['id']} "
                    f"{row['sync_type']}:{row['technology']} "
                    f"{row['status']} rows={row['rows_affected']} "
                    f"{(row['message'] or '').strip()}"
                )
        except KeyboardInterrupt:
            print("\nStopping live sync logger.")
            break
        except Exception as exc:
            print(f"[logger-warning] {exc}")
            time.sleep(interval)
            try:
                conn.close()
            except Exception:
                pass
            conn = _connect()
        time.sleep(interval)

    try:
        conn.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
