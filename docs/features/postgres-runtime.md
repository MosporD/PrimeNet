# Postgres runtime (opt-in)

Not a dashboard tile. Default remains SQLite.

| | |
|---|---|
| Routing | `db/runtime.py` `open_db()` / `store_available()` |
| Domains | `db/pg_domains.py` |
| SQL adapt | `db/app_sql.py` |
| Migrate | `scripts/migrate_ncm_users_to_postgres.py`, `scripts/migrate_sqlite_domain_to_postgres.py`, `scripts/migrate_all_sqlite_to_postgres.py` |

## Purpose

Optional cutover of canonical SQLite files to one Postgres server, **per domain**, for backup/HA. Nokia and Huawei hourly tables share names (`"4G_Hourly"`) so each file is its own schema (`pm_nokia_hourly`, `pm_huawei_hourly`, …).

## Approach

- **Do not set** `NCM_DATABASE_URL` / `NCM_APP_DATABASE_URL` on this laptop without a running Postgres + migrate.
- `NCM_APP_DATABASE_URL` alone = app schema only. `NCM_DATABASE_URL` with unset `NCM_PG_DOMAINS` = all groups. Subset via `NCM_PG_DOMAINS=app,metadata,neighbors,groups,balance,pm`.
- Enabling `pm` requires `metadata` (same backend) or `performance_meta_pm_conn` raises.
- Femto, SON ML, KPI headers, CM snapshots stay SQLite on purpose.
- New PM/metadata readers: `open_db(path)` + `store_available(path)`, not raw `sqlite3.connect` + `os.path.isfile`.

## History

- 2026-08-31: phase 0 inventory; phase 1 app DB adapter; phases 2–4 plumbing + migrate scripts. Tests 16/16 on SQLite. No live PG here.

## Plans

Cut over on the **server** after migrate. PM ingest on PG is not load-tested (~14 GB). Dashboard constellation pulse still uses SQLite `rowid` — will go quiet on PG until rewritten (visual only).

## Watch-outs

`sync_config.use_postgresql()` is the old global stub. Domain routing is `is_domain_postgresql()` / `open_db()`. SQLite files stay as cold backup after migrate.
