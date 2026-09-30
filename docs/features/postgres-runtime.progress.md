# Postgres runtime (required) — progress

Detailed dated log for this blueprint. Brief: [`postgres-runtime.md`](postgres-runtime.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

---
## 2026-09-30 (SQLite-lenient numeric CAST)

- Root cause: metadata text like azimuth `IBS` hit `CAST(x AS REAL)` → Postgres `invalid input syntax for type real` (SQLite returns 0). ~106 numeric CASTs in 10 files (Performance, Network Map, Adjacency GIS, Cell Heatmap, site catalog, neighbor agg).
- Done: `rewrite_numeric_casts` in `db/app_sql.py` → `public.ncm_real` / `public.ncm_int` (leading numeric prefix, else 0; NULL stays NULL). Functions created once per process in `_connect_postgres`.
- Verified: parity vs SQLite CAST 11/12 (only `'1e3'` AS INTEGER differs); `/api/performance/cells` South Jordan 13278 / West Amman 10441 on live PG; adapter tests 30 passed.
- NEXT: Push + rebuild 97.141; smoke Performance tree, Network Map, Adjacency GIS.

## 2026-09-30 (Login 500 after `%` escape)

- Root cause: `bf81e7e0` made `qmark_to_percent` non-idempotent. Callers that pre-adapt (`database_enhanced._exec`, `task_scheduler/routes.py`, `metadata_processor`) get adapted twice in `PgConn`, so `%s` → `%%s` → `the query has 0 placeholders but 1 parameters were passed` (login 500).
- Done: `qmark_to_percent` keeps existing `%%` and `%s` (outside single-quoted literals), escapes lone `%` only.
- Verified: live PG — `authenticate_user` fails on `bf81e7e0` app_sql, OK after fix; adapter tests 27 passed (idempotency + pre-adapted cursor case).
- NEXT: Push + rebuild 97.141; log in; then re-run Hourly/Daily.

## 2026-09-29 (psycopg `%` in PM column names)

- Root cause: PM counter headers like `CSSR(%)` reached psycopg unescaped → `only '%s', '%b', '%t' are allowed as placeholders, got '%)'` on every Huawei cells/groups hourly+daily load.
- Done: `qmark_to_percent` escapes `%` → `%%`; `PgConn.execute` / `PgCursor.execute` always pass params (`()` when None) so psycopg collapses `%%` on no-param DDL too (else `ALTER TABLE ADD COLUMN "X(%)"` would create `X(%%)`).
- Tests: `scripts/test_app_db_adapter.py` 23 passed (INSERT / ALTER / CREATE with `(%)` columns, via psycopg's query parser).
- NEXT: Commit + rebuild primenet/scheduler on 97.141; re-run Hourly + Daily; confirm `failed_files=0`.

## 2026-09-29 (Postgres-only 1B)

- Done: `require_postgres_url()` in `db/pg_domains.py`; wired into `deploy/bootstrap.py`, `primenet_app.py`, `nexuscore_app.py`, `nexpulse_app.py`.
- Done: `open_db` / `open_store` / `store_available` / `performance_meta_pm_conn` are Postgres-only (no SQLite ATTACH fallback).
- Done: `rewrite_sqlite_master` handles existence probes; `table_exists` / `list_tables` helpers.
- Done: `.env.example` + brief rewritten for Compose `app-db` laptop runbook.
- NEXT: Server rebuild; Daily load verify; finish blueprint catalog sweeps using `list_tables`.

## 2026-09-28 (full catalog → Postgres)

- Done: Extended `NCM_PG_DOMAINS` / `ALL_GROUPS` with femto, son_ml, nh_precalc, kpi_headers, cm, elevation, rru, adjacency, wncelg, cases, pm_plus, marketing.
- Done: `open_store()` helper; wired leftover module stores + groups/femto/KPI headers/marketing through `open_db`/`store_available`.
- Done: Fresh-start plan = migrate `app` only; other schemas empty until ingest.
- NEXT: Server pull/rebuild; set full domains (or unset = all); migrate `--schema app` only.

## From brief History (migrated 2026-09-17)

- 2026-08-31: phase 0 inventory; phase 1 app DB adapter; phases 2–4 plumbing + migrate scripts. Tests 16/16 on SQLite. No live PG here.

## 2026-08-31 (Postgres phases 2–4 plumbing)

- Done: Opt-in domain routing — `NCM_DATABASE_URL` + `NCM_PG_DOMAINS=app,metadata,neighbors,groups,balance,pm`. Unset = SQLite as today. `NCM_APP_DATABASE_URL` alone still means **app only**.
- Done: Separate Postgres schemas so Nokia/Huawei hourly table names can collide (`pm_nokia_hourly` vs `pm_huawei_hourly`). SQLite ATTACH aliases become schema-qualified `alias."table"`.
- Done: `db.runtime.open_db` / `store_available` used by Performance, ingest, neighbors, groups, SON PM helpers, pipeline loader. Femto / SON ML / KPI headers stay SQLite.
- Done: `python scripts/migrate_sqlite_domain_to_postgres.py --schema metadata` and `python scripts/migrate_all_sqlite_to_postgres.py` (chunked copy; does not delete SQLite files).
- Verified: adapter tests 16/16; `init_db` still SQLite; no Postgres URL set on this laptop.
- Not done: no live Postgres here — do not set the URL until the server has Postgres and migrate has been run. PM ingest on Postgres is not load-tested (14 GB).

## 2026-08-31 (Postgres phase 0–1)

- Done: Phase 0 inventory — `python scripts/inventory_sqlite_databases.py`. App DB `ncm_users.db` is 548 KB / 22 tables / 3879 rows (57 users). PM+femto are multi-GB; stay SQLite. ATTACH in `performance_meta_pm_conn` blocks PM Postgres.
- Done: Phase 1 opt-in — `NCM_APP_DATABASE_URL=postgresql://…` switches **only** `connect_app()` (users/sessions + other ncm_users tables). Unset = SQLite as today. Adapter tests 6/6. `init_db` still works on SQLite (57 users).
- Done: `scripts/migrate_ncm_users_to_postgres.py` copies SQLite → schema `app`. Optional Compose profile `app-db` for a local Postgres (not started by default).
- Not done: no live Postgres on this laptop; do not set the URL until the server has Postgres and the migrate script has been run.
