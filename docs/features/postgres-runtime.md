# Postgres runtime (opt-in)

Not a dashboard tile. Default remains SQLite until ``NCM_DATABASE_URL`` is set.

| | |
|---|---|
| Routing | `db/runtime.py` `open_db()` / `open_store()` / `store_available()` |
| Domains | `db/pg_domains.py` |
| SQL adapt | `db/app_sql.py` |
| Migrate | `scripts/migrate_ncm_users_to_postgres.py`, `scripts/migrate_sqlite_domain_to_postgres.py`, `scripts/migrate_all_sqlite_to_postgres.py` |

## Purpose

Optional cutover of canonical SQLite files to one Postgres server, **per domain**. Nokia and Huawei hourly tables share names (`"4G_Hourly"`) so each file is its own schema (`pm_nokia_hourly`, `pm_huawei_hourly`, …).

## Approach

- **Do not set** `NCM_DATABASE_URL` / `NCM_APP_DATABASE_URL` on this laptop without a running Postgres + migrate (for domains you copy).
- `NCM_APP_DATABASE_URL` alone = app schema only. `NCM_DATABASE_URL` with unset `NCM_PG_DOMAINS` = **all** groups (PM, femto, SON ML, NH precalc, KPI headers, CM, elevation, RRU, adjacency, WNCELG, cases, PM Plus, marketing, …).
- Subset via `NCM_PG_DOMAINS=app,metadata,pm,…`.
- Enabling `pm` requires `metadata` (same backend) or `performance_meta_pm_conn` raises.
- Fresh-start ops: migrate **app** only; leave other schemas empty and fill via ingest/jobs.
- Readers/writers: `open_db` / `open_store` / `store_available`, not raw `sqlite3.connect` + `os.path.isfile` for catalogued paths.

## Progress

Dated work log: [`postgres-runtime.progress.md`](postgres-runtime.progress.md). Do not duplicate long history here — update the progress file when this feature changes. Keep **Plans** as the module NEXT.


## Plans

Server cutover with full `NCM_PG_DOMAINS` (or unset = all). Migrate `app` only for users/sessions; everything else fresh ingest. PM ingest on PG not load-tested at 14 GB historical scale (empty start is fine).

## Watch-outs

`sync_config.use_postgresql()` is the old global stub. Domain routing is `is_domain_postgresql()` / `open_db()`. SQLite files stay as cold backup after any migrate you do run.
