# Performance Explorer Plus — progress

Detailed dated log for this blueprint. Brief: [`performance-explorer-plus.md`](performance-explorer-plus.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

**Parked:** None — continuous worker is deploy/ops (checklist below), not a code gap.

**NEXT:** On server, run the deploy checklist; then tune SFTP workers against <15 min lag SLO.

---

## 2026-10-07 (PM Plus continuous worker — deploy checklist)

Run on the **server** only (laptop keeps `NCM_ENABLE_ETL=0`):

1. Server `.env`: `NCM_ENABLE_ETL=1` (or unset so `deploy/entrypoint.sh` / `deploy/run_scheduler.py` default to `1`). Do **not** flip laptop `.env`.
2. Confirm `PM_PLUS_DATABASE_URL` (or `pm_plus` in `NCM_PG_DOMAINS`) + `NOKIA_PM_FTP_*` / `PM_PLUS_*` worker envs from `.env.example`.
3. Start a **separate** process (not Gunicorn, not the Excel `scheduler` compose service):
   - Smoke once: `python scripts/pm_plus/run_ingest_worker.py --once --buckets 2`
   - Continuous: `python scripts/pm_plus/run_ingest_worker.py` (tmux/systemd/sidecar). Poll default `PM_PLUS_POLL_INTERVAL_SEC` (30s).
4. Alt without Excel ETL on that host: `python scripts/pm_plus/run_ingest_worker.py --ignore-etl-gate`.
5. UI: `/performance-explorer-plus` → Ingest Health — lag/backlog; aim &lt;15 min when workers are up.
6. Optional rollup: `python scripts/pm_plus/run_rollup.py`.

Compose today has no `pm-plus-ingest` service — keep it as a sidecar/systemd unit until one is added.

---
## 2026-09-29 (Postgres-only)

- How it works on PG: catalogued stores open via `open_db` / `open_store` into Postgres schemas (`NCM_DATABASE_URL` required). No SQLite file fallback for this module's data plane.
- NEXT: Smoke primary routes after Daily load on server PG.

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
