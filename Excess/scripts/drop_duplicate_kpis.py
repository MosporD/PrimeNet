import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sync_config import (
    NOKIA_PM_DB,
    HUAWEI_PM_DB,
    NOKIA_PM_DAILY_DB,
    HUAWEI_PM_DAILY_DB,
    NOKIA_GROUPS_DB,
    HUAWEI_GROUPS_DB,
    NOKIA_GROUPS_DAILY_DB,
    HUAWEI_GROUPS_DAILY_DB,
)


DUPLICATE_KPIS = [
    "RH303:Handover Success Rate(%)",
    "K3034:TCHH Traffic Volume(Erl)",
    "Drop Call Rate",
    "CS RAB Congestion Num",
    "TCH raw block.1",
    "Act HS-DSCH  end usr thp",
    "Expect cell size",
    "Avg PDCP cell thp UL",
    "TRS_SLOT_PDSCH (M55308C00017)",
]


def main() -> None:
    dbs = [
        NOKIA_PM_DB,
        HUAWEI_PM_DB,
        NOKIA_PM_DAILY_DB,
        HUAWEI_PM_DAILY_DB,
        NOKIA_GROUPS_DB,
        HUAWEI_GROUPS_DB,
        NOKIA_GROUPS_DAILY_DB,
        HUAWEI_GROUPS_DAILY_DB,
    ]

    for db in dbs:
        if not db or not os.path.exists(db):
            print(f"[skip missing] {db}")
            continue
        print(f"\nDB {db}")
        conn = sqlite3.connect(db, timeout=3)
        try:
            conn.execute("PRAGMA busy_timeout=3000")
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]
            for table in tables:
                cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
                for kpi in DUPLICATE_KPIS:
                    if kpi not in cols:
                        continue
                    try:
                        conn.execute(f'ALTER TABLE "{table}" DROP COLUMN "{kpi}"')
                        print(f" dropped {kpi} from {table}")
                    except Exception as exc:
                        print(f" failed {kpi} from {table}: {exc}")
            conn.commit()
        except Exception as exc:
            print(f" [skip locked/error] {db}: {exc}")
        finally:
            conn.close()

    print("\nDone")


if __name__ == "__main__":
    main()
