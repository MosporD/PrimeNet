# Performance Explorer Plus — progress

Detailed dated log for this blueprint. Brief: [`performance-explorer-plus.md`](performance-explorer-plus.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

**Parked:** PM Plus continuous worker on server (`NCM_ENABLE_ETL=1`).

**NEXT:** Tune live SFTP workers against <15 min lag SLO when on production hosts.

---
## From brief History (migrated 2026-09-17)

- 2026-09-11: V1 shipped — pilot, ingest worker, rollup, Explorer/Builder/Health UI, dashboard tile.
- 2026-09-11: Grain keys (gp/ne_type/stream); rule-aware cascade hour←ROP, day←ROP, week←day, month←week, year←month; NONE→SUM. Agg rules / catalog import live on **Admin Panel → PM Plus Rules** (not this UI).

## 2026-09-14 (PM Plus Admin Rules + sample ingest)

- Done: Agg Rules live on Admin → **PM Plus Rules** (`/admin-panel?section=pm-plus-rules`); removed from Explorer Plus. Smoke `scripts/_smoke_pm_plus_admin.py` — page 200, families/counters APIs OK, old PEP rules API 404.
- Done: Re-imported Nokia catalog (453 families / ~32k counters / 2831 KPIs).
- Done: Local hour sample ingest `run_hour_ingest.py --buckets 2 --max-files 30` — 30/30 ok, ~3.87M fact_15m / ~3.82M fact_hour; SFTP host 10.119.219.24 reachable (~75s discover). Day rollup not run this pass.
- Fixed: `core/cases/__init__.py` import mismatch (`open_complaint_case`) that briefly broke `app` import.

## 2026-09-11 (Performance Explorer Plus)

- Done: `core/pm_plus/` — streaming TS 32.435 parser, ledger, ingest cycle, hour→day rollup, KPI compiler, query/export, VendorAdapter (Huawei stub).
- Done: Scripts `scripts/pm_plus/run_pilot.py`, `run_ingest_worker.py`, `run_rollup.py`.
- Done: Module `/performance-explorer-plus` (Explorer / KPI Builder / Ingest Health) + dashboard tile; old `/performance` unchanged.
- Done: Unit tests 7/7 (`core.pm_plus.test_pm_plus`); pilot sample ingest ~0.02s.
- Store: SQLite fallback `databases/pm_plus/pm_plus.db`; Postgres via `PM_PLUS_DATABASE_URL`.
