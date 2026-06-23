import os
from sync_config import PROJECT_ROOT, HUAWEI_PM_DB
from scripts.pipeline.load_raw_csv_to_databases import _load_folder_tabular_to_db


def main() -> int:
    folder = os.path.join(PROJECT_ROOT, "raw", "huawei", "cells")
    loaded, failed = _load_folder_tabular_to_db(
        folder,
        HUAWEI_PM_DB,
        "huawei-cells",
        incremental=True,
    )
    print("loaded", loaded, "failed", failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
