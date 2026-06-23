import os
import sys
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from modules.performance.routes import (  # noqa: E402
    _resolve_pm_table_sqlite,
    _resolve_pm_axis_columns_sqlite,
    _filter_trend_rows_by_hours,
)
from modules.sync.metadata_active_sql import perf_per_tech_union_sql  # noqa: E402


def probe(vendor: str, technology: str) -> None:
    mc = sqlite3.connect("databases/cells/metadata.db")
    mc.row_factory = sqlite3.Row
    u = perf_per_tech_union_sql()
    row = mc.execute(
        f"SELECT cell_name,vendor,technology,site_id FROM ({u}) WHERE vendor=? AND technology=? LIMIT 1",
        (vendor, technology),
    ).fetchone()
    mc.close()
    if not row:
        print(vendor, technology, "NO_CELL_IN_UNION")
        return

    cell = dict(row)["cell_name"]
    pm_db = "databases/cells/nokia_pm_cells.db" if vendor == "Nokia" else "databases/cells/huawei_pm_cells.db"
    pm = sqlite3.connect(pm_db)
    pm.row_factory = sqlite3.Row
    pm_tech = "4G" if technology in ("4G-FDD", "4G-TDD") else technology
    table = _resolve_pm_table_sqlite(pm, vendor, pm_tech, cell, None)
    ccol, tcol = (None, None) if not table else _resolve_pm_axis_columns_sqlite(pm, table)
    if not table or not ccol or not tcol:
        print(vendor, technology, cell, "NO_TABLE_OR_AXIS", table, ccol, tcol)
        pm.close()
        return
    rows = [
        dict(r)
        for r in pm.execute(
            f'SELECT "{ccol}" AS cell_name, "{tcol}" AS timestamp FROM "{table}" '
            f'WHERE LOWER(TRIM(CAST("{ccol}" AS TEXT))) = LOWER(TRIM(?)) '
            f'ORDER BY "{tcol}" ASC',
            (cell,),
        ).fetchall()
    ]
    rows168 = _filter_trend_rows_by_hours(rows, 168)
    print(vendor, technology, "db", pm_db, "table", table, "rows", len(rows), "rows_168h", len(rows168))
    pm.close()


if __name__ == "__main__":
    for v, t in [
        ("Nokia", "2G"),
        ("Nokia", "3G"),
        ("Nokia", "4G-FDD"),
        ("Nokia", "5G"),
        ("Huawei", "2G"),
        ("Huawei", "3G"),
        ("Huawei", "4G-FDD"),
    ]:
        probe(v, t)
