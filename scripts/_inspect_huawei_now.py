import sqlite3
from sync_config import HUAWEI_PM_DB

c = sqlite3.connect(HUAWEI_PM_DB)
tabs = [r[0] for r in c.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
).fetchall()]
print("tables", tabs)
for t in tabs:
    n = c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
    cols = [x[1] for x in c.execute(f'PRAGMA table_info("{t}")').fetchall()]
    print(t, "rows", n, "cols", cols[:8])
c.close()
