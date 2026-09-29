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

1. Set in `.env`: `NCM_APP_POSTGRES_PASSWORD`, matching `NCM_DATABASE_URL=postgresql://primenet:<password>@127.0.0.1:5432/primenet`.
2. `docker compose --profile app-db up -d postgres`
3. `pip install "psycopg[binary]"` if needed
4. `python scripts/migrate_ncm_users_to_postgres.py` (users/sessions only)
5. Leave PM/metadata empty; fill with Daily/Hourly ingest or a small CSV load
6. Smoke: `python -c "from db.pg_domains import require_postgres_url; from db.runtime import connect_app; require_postgres_url(); c=connect_app(); print(c.execute('select current_schema()').fetchone()); c.close()"`

Reset volume (destructive): `docker compose --profile app-db down -v`

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
