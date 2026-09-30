# Sync / pipeline (ETL) — progress

Detailed dated log for this blueprint. Brief: [`sync.md`](sync.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

**Parked:** Local ETL kill switch remains `NCM_ENABLE_ETL=0` on laptop.

---
## 2026-09-30 (Metadata technology column, watcher visibility, GMT+3, error export)

- Root cause (metadata): loader `if_exists="replace"` rebuilt `metadata.cells_*` from CSV without `technology` / `updated_at` / unique `cell_name`; `metadata_processor.import_csv_to_cells` then failed on `technology`. Done: `db_migration.ensure_per_tech_table_shape` (adds columns, dedupes, unique index) called from both paths; processor now upserts `ON CONFLICT (cell_name)`. Verified on scratch copy of `cells_5g`.
- Found: `sync_log` shows "Hourly orchestrator skipped: another pipeline cycle is already running" every hour for 30+ h; watcher (primary loader) holds `_pipeline_cycle_lock` and its failures only reached the container log. Done: watcher cycles now write `pull_watcher` ok/error/crash rows with duration.
- Done: `TZ=Asia/Amman` + tzdata in Dockerfile; Postgres sessions `SET TIME ZONE` from `NCM_TIMEZONE`/`TZ` (default Asia/Amman). Rows written before deploy stay UTC.
- Done: `GET /api/sync/errors/export?days=30` CSV + "Export 30 days" button on ETL Diagnosis → Recent errors. `sync_log` is never pruned.
- NEXT: Rebuild primenet+scheduler; read `pull_watcher` errors to find the Nokia 4G / groups load failure.

## 2026-09-30 (Neighbor sync on Postgres)

- Root cause: `load_nokia_neighbor_raw_to_db.py` / `load_huawei_neighbor_wide_to_db.py` called pandas `DataFrame.to_sql` on `PgConn`; pandas falls back to SQLite mode and probes `sqlite_master ... type IN ('table','view')` → `pandas.errors.DatabaseError` on the first table.
- Done: shared `db.runtime.df_to_sql` (COPY on Postgres; all-empty columns → TEXT, integral floats → int so chunked 4G appends fit); 33 call sites → `.pipe(df_to_sql, ...)`.
- Done: `db.runtime.read_sql_query` for `pm_retention` + loader max-timestamp (pandas fallback returned column names as values; `PgCursor.fetchmany` was missing).
- Verified: live PG probe (replace + drifting append + `(%)` column + empty table; chunked/non-chunked reads). No local neighbor raw to run the full loader.
- NEXT: Push + rebuild 97.141; trigger Neighbor sync; check `[neighbor-raw]` / `[huawei-neighbor-wide]` row counts.

## 2026-09-29 (Postgres-only Daily load)

- How it works on PG: orchestrators call `pipeline/load/daily/load_all.py` → `scripts/pipeline/load_raw_csv_to_databases.py` with `--scope daily`. Stores open via `open_db` into `pm_*` / `groups_*` / `metadata` schemas. Catalog checks use `table_exists` / `list_tables` (adapter rewrites legacy `sqlite_master` SQL). Child Python runs with `-u` / `PYTHONUNBUFFERED=1` so per-file `[label] failed …` lines reach Docker logs.
- Root cause of empty PM: existence probe `SELECT 1 FROM sqlite_master …` was not rewritten → every file failed with `relation "sqlite_master" does not exist`.
- NEXT: Rebuild primenet+scheduler on 97.141; re-run Daily; confirm `[done] failed_files=0`.

## 2026-09-29 (No PM after cutover — diagnosis)

- State: all `pm_*` hourly tables still 0 rows; metadata RAT tables populated; daily schemas empty.
- Causes: `NCM_SYNC_RESET_MODE` default was parked (fixed → opt-in); scheduler pipeline lock still stuck (restart); daily/hourly failures had opaque `code=1` (now include stderr detail).
- NEXT: Server set `NCM_SYNC_RESET_MODE=0` (or omit), restart scheduler, redeploy, re-run hourly/daily from ETL Diagnosis.

- Done: `modules/sync/etl_diagnosis.py` + `/api/sync/diagnosis`; progress for hourly/daily/neighbor/category jobs; triggers for hourly_full / daily_full / neighbor_sync.
- Done: Re-registered daily `pull_metadata` cron (`METADATA_PULL_HOUR` / `METADATA_PULL_MINUTE`, default daily pull hour :20). Kill switch `NCM_DISABLE_METADATA_SCHEDULER=1`.
- NEXT: Server rebuild/restart scheduler; confirm `NCM_SYNC_RESET_MODE=0` and `pm` in `NCM_PG_DOMAINS` (or unset domains).

## From brief History (migrated 2026-09-17)

- 2026-09-11: `NCM_ENABLE_ETL` gate + local ETL data cleanup script.
- 2026-08-02: scheduler RAM isolation.
- 2026-08-31: ingest paths wired through `open_db` for optional Postgres.

## 2026-09-11 (ETL gate + local cleanup)

- Done: `core/etl_gate.py` — `NCM_ENABLE_ETL=0/1` master switch (loads `.env`); wired into bootstrap, scheduler, sync triggers, pipeline orchestrators/pull/load, PM Plus workers.
- Done: Local `.env` + `.env.example` set `NCM_ENABLE_ETL=0`; server scheduler entrypoint defaults to `1`.
- Done: `scripts/clear_local_etl_data.py` — wipes PM/raw/sync_downloads, keeps admin+metadata+geo.
