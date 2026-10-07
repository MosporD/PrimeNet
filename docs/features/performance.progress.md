# Performance Explorer — progress

Detailed dated log for this blueprint. Brief: [`performance.md`](performance.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

---
## 2026-10-07 (Nokia 4G empty — PG 63-byte column truncate)

- Symptom: Performance Explorer Nokia 4G cell query/export empty while SFTP had files; 2G/3G/5G + Huawei 4G OK; metadata cell list OK.
- Root cause: Nokia 4G CSV has a 94-byte KPI header; Postgres truncates idents to 63 bytes. Chunk 1 CREATE succeeded; chunk 2+ `ALTER … ADD COLUMN` saw the truncated name as already existing → whole load aborted/rolled back. Empty stub `4G_CELLS_HOURLY` left behind.
- Fix: `postgres_ident_truncate` in `db/runtime.py`; normalize names before append/ensure in loader; stream Nokia zip extract (no full `src.read()`).
- Recovered shared PG: hourly ~369k + daily ~474k Nokia 4G area-shard rows. Deploy loader/runtime fix to server so watcher keeps succeeding.
- NEXT: Deploy code to 97.141; confirm next watcher Nokia cells cycle loads 4G without error; smoke Performance export on a West Amman LNCEL.

## 2026-10-04 (Soft Steel UI retoken)

- Retokened Element/Ant blues + chart purples to Soft Steel Sky; shared header logout chip; removed title emoji; modal title h2 for heading order.
- NEXT: Smoke Groups mode + cell area tree on 97.141; confirm `pm` in `NCM_PG_DOMAINS` on server.

## 2026-10-01 (Groups not loading on Postgres)

- Root cause: raw groups fallback used `<> ""` (empty double-quoted identifier on PG) → `/api/performance/groups` 500; also matched KPI “Rate” columns as technology via loose `rat` substring.
- Done: empty-string rewrite in `db.app_sql`; groups SQL uses `''`; skip `groups`/`group_cells` in raw specs; exact tech/site column pick; per-table try/except on raw listing.
- Note: live env `NCM_PG_DOMAINS` without `pm` → cell tree (metadata) works, KPI columns / trends need `pm` enabled.
- NEXT: Smoke Groups mode + cell area tree on 97.141; confirm `pm` in `NCM_PG_DOMAINS` on server.

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
