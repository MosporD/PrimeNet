# Postgres runtime (required) — progress

Detailed dated log for this blueprint. Brief: [`postgres-runtime.md`](postgres-runtime.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

---
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
