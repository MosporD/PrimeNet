"""
Remove local SQLite PM / group database files (destructive).

Usage:
  python scripts/drop_legacy_performance_storage.py --confirm
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sync_config import (  # noqa: E402
    HUAWEI_PM_DB,
    HUAWEI_PM_DAILY_DB,
    HUAWEI_GROUPS_DAILY_DB,
    HUAWEI_GROUPS_DB,
    NOKIA_PM_DB,
    NOKIA_PM_DAILY_DB,
    NOKIA_GROUPS_DAILY_DB,
    NOKIA_GROUPS_DB,
)


def _remove_sqlite(path: str) -> bool:
    p = Path(path)
    if not p.is_file():
        return False
    try:
        conn = sqlite3.connect(str(p), timeout=2)
        conn.close()
    except Exception:
        pass
    p.unlink(missing_ok=True)
    return True


def main() -> int:
    if "--confirm" not in sys.argv:
        print("Refusing to run without --confirm")
        return 1

    removed = 0
    for db_path in (
        NOKIA_PM_DB,
        HUAWEI_PM_DB,
        NOKIA_PM_DAILY_DB,
        HUAWEI_PM_DAILY_DB,
        NOKIA_GROUPS_DB,
        HUAWEI_GROUPS_DB,
        NOKIA_GROUPS_DAILY_DB,
        HUAWEI_GROUPS_DAILY_DB,
    ):
        if _remove_sqlite(db_path):
            removed += 1

    print(f"[done] removed_sqlite_files={removed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
