"""Print SQLite table names and column headers for project DBs."""
import json
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DBS = [
    os.path.join("databases", "cells", "metadata.db"),
    os.path.join("databases", "cells", "nokia_pm_cells.db"),
    os.path.join("databases", "cells", "huawei_pm_cells.db"),
    os.path.join("databases", "cells", "ncm_users.db"),
    os.path.join("databases", "groups", "nokia_cell_groups.db"),
    os.path.join("databases", "groups", "huawei_cell_groups.db"),
]


def main():
    for name in DBS:
        path = os.path.join(ROOT, name)
        print(f"=== {name} ===")
        if not os.path.isfile(path):
            print("  (file missing)\n")
            continue
        try:
            con = sqlite3.connect(path)
            cur = con.cursor()
            tables = [
                r[0]
                for r in cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ).fetchall()
            ]
            out = {}
            for t in tables:
                cols = [
                    r[1]
                    for r in cur.execute(f'PRAGMA table_info("{t}")').fetchall()
                ]
                out[t] = cols
            con.close()
            print(json.dumps(out, indent=2))
        except Exception as e:
            print(f"  ERROR: {e}")
        print()


if __name__ == "__main__":
    main()
