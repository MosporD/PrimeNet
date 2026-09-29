# Performance Explorer — progress

Detailed dated log for this blueprint. Brief: [`performance.md`](performance.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

---
## 2026-09-29 (Postgres-only)

- How it works on PG: `performance_meta_pm_conn` opens metadata schema and returns PM schema aliases (`pm_nokia_hourly`, …) for `alias."table"` SQL — no SQLite ATTACH. Table listing uses `list_tables` / adapted `sqlite_master` SQL. Data appears only after Daily/Hourly load into PG schemas.
- NEXT: Smoke Performance after Daily load on 97.141.

## From brief History (migrated 2026-09-17)

- 2026-08-05: chart layouts, site-search fix.
- 2026-08-31: PM opens go through `open_db` for optional Postgres.

## 2026-08-11

- Done: Network Balance ingest process monitor in Nokia Load Balancing UI
- Done: Performance Explorer site-search fix
- Done: Docker apt-get fix for networks that block HTTP
- Modified: `Dockerfile`, `modules/nokia_load_balancing/`, `modules/performance/`

## 2026-08-05

- Done: SMB auto-mount for Network Balance on Linux Docker
- Done: Performance chart layouts, search deep links, RET writes, admin activity
- Done: Huawei HedEx in-page TOC links
- Done: Nokia NE list site-ID resolution cache
- Modified: `deploy/`, `docker-compose.yml`, `core/cm_extractor/nokia_discovery.py`, `modules/performance/`, `modules/ret_management/`, `modules/ran_features/hdx.py`

## 2026-07-30

- Done: UI zoom pointer sync, Performance Explorer loading UX + site select-all
