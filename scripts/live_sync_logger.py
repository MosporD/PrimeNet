"""
Live sync logger for a separate terminal window.

Polls sync_log and prints new entries as they are written by scheduler/jobs.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.runtime import connect_app, execute_query, is_app_postgresql
from sync_config import NCMUSERS_DB


def _connect():
    return connect_app()


def _last_id(conn) -> int:
    try:
        row = execute_query(conn, "SELECT COALESCE(MAX(id), 0) AS n FROM sync_log").fetchone()
        if not row:
            return 0
        if isinstance(row, dict):
            return int(row.get("n") or 0)
        return int(row[0] or 0)
    except Exception:
        return 0


def main() -> int:
    interval = 1.5
    try:
        interval = max(0.5, float(os.getenv("SYNC_LOGGER_POLL_SEC", "1.5")))
    except ValueError:
        pass
    backend = "postgres" if is_app_postgresql() else "sqlite"
    print(f"Live sync logger ({backend})")
    print(f"DB: {NCMUSERS_DB if backend == 'sqlite' else os.getenv('NCM_APP_DATABASE_URL', '')}")
    conn = _connect()
    last = _last_id(conn)
    print(f"Watching sync_log from id > {last}")
    try:
        while True:
            time.sleep(interval)
            try:
                rows = execute_query(
                    conn,
                    "SELECT id, started_at, sync_type, technology, status, rows_affected, message "
                    "FROM sync_log WHERE id > ? ORDER BY id ASC",
                    (last,),
                ).fetchall()
            except Exception:
                conn.close()
                conn = _connect()
                continue
            for row in rows:
                rid = row["id"] if isinstance(row, dict) else row[0]
                last = max(last, int(rid))
                started = row["started_at"] if isinstance(row, dict) else row[1]
                stype = row["sync_type"] if isinstance(row, dict) else row[2]
                tech = row["technology"] if isinstance(row, dict) else row[3]
                status = row["status"] if isinstance(row, dict) else row[4]
                n = row["rows_affected"] if isinstance(row, dict) else row[5]
                msg = row["message"] if isinstance(row, dict) else row[6]
                stamp = started or datetime.now().isoformat(timespec="seconds")
                print(f"[{stamp}] {stype}/{tech} {status} rows={n} {msg or ''}")
    except KeyboardInterrupt:
        print("stopped")
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
