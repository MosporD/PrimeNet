# Postgres runtime (required)

Not a dashboard tile. PrimeNet is **Postgres-only**: the app will not start without a Postgres URL.

| | |
|---|---|
| Routing | `db/runtime.py` `open_db()` / `open_store()` / `store_available()` |
| Domains | `db/pg_domains.py` (`require_postgres_url`) |
| SQL adapt | `db/app_sql.py` (SQLite-shaped SQL → Postgres) |
| Migrate | `scripts/migrate_ncm_users_to_postgres.py`, `scripts/migrate_sqlite_domain_to_postgres.py` (one-shot from cold SQLite backups) |

## Purpose

One Postgres server hosts every catalogued store as its own schema (`app`, `metadata`, `pm_nokia_hourly`, …). Nokia and Huawei hourly table names collide, so vendors never share a PM search_path.

## Laptop runbook

1. Set `NCM_DATABASE_URL` in `.env` to the remote Postgres server (`postgresql://USER:PASSWORD@HOST:5432/primenet`). Do not start a local Postgres container and do not create a local data volume.
2. `pip install "psycopg[binary]"` if needed
3. `python scripts/migrate_ncm_users_to_postgres.py` (users/sessions only) — only when the remote `app` schema is empty
4. Leave PM/metadata empty; fill with Daily/Hourly ingest or a small CSV load
5. Smoke: `python -c "from db.pg_domains import require_postgres_url; from db.runtime import connect_app; require_postgres_url(); c=connect_app(); print(c.execute('select current_schema()').fetchone()); c.close()"`

## Approach

- Startup (`deploy/bootstrap.py` and entrypoints) calls `require_postgres_url()`.
- `open_db` / `open_store` never open SQLite files for catalogued paths.
- Unset `NCM_PG_DOMAINS` with `NCM_DATABASE_URL` enables all groups.
- Readers/writers use `list_tables` / `table_exists` / `execute_query`, not raw `sqlite3.connect`.
- Thin SQL adapter remains until call sites speak native Postgres catalog SQL.

## Progress

Dated work log: [`postgres-runtime.progress.md`](postgres-runtime.progress.md).

## Plans

Server rebuild/redeploy with Postgres-only gate; re-run Daily load and confirm `failed_files=0`. Keep SQL adapter until call sites use native `information_schema`. Run `python -m graphify update .` after pull if the local graph extract is stale.

## Watch-outs

`sync_config.use_postgresql()` is a legacy stub. Domain routing is `is_domain_postgresql()` / `open_db()`. Enabling `pm` requires `metadata` (same backend).
