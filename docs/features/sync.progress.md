# Sync / pipeline (ETL) — progress

Detailed dated log for this blueprint. Brief: [`sync.md`](sync.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

**Parked:** Local ETL kill switch remains `NCM_ENABLE_ETL=0` on laptop.

---
## 2026-10-05 (Nokia/Huawei CM catalog on shared volume)

- Bug: `nokia_netact_inventory.json` / Huawei NE catalog lived under `/app/data` (image tree). Scheduler refreshed its private copy; PrimeNet web kept the baked-in stale file — RET / CM pickers missed new NetAct sites (e.g. 54792).
- Done: catalogs write to `NCM_DATA_ROOT/var/cm_catalogs/` (`core/cm_extractor/catalog_store.py`); legacy `<repo>/data/…` still read as fallback.
- NEXT: Rebuild/restart **scheduler + primenet**; trigger Nokia CM inventory once; confirm 54792 (or any new MRBTS) appears in RET Management search.

## 2026-10-05 (Teams webhook + Approver emails)

- Done: `core/events.py` posts Teams MessageCards to `NCM_TEAMS_WEBHOOK_URL` (fallback `NCM_EVENTS_WEBHOOK_URL`); embeds emails of users with `can_approve` (+ Owners).
- Done: Scheduler still emits `etl.{hourly,daily,neighbor}.{finished,failed}`; JSONL under `var/platform_events.jsonl`.
- Done: `GET /healthz` (+ `/api/healthz`) via `core/platform_health.py` — PM/neighbor freshness; debounced `platform.data_stale`.
- NEXT: Set `NCM_TEAMS_WEBHOOK_URL` on server; flag Approvers in Platform Admin; confirm one ETL finish card in Teams.

## 2026-10-04 (Neighbor lock separate from watcher)

- Found: neighbor at `:30` skipped whenever watcher held `_pipeline_cycle_lock` (~26–32 min every 30 min).
- Done: neighbor uses `_neighbor_cycle_lock` only; PM hourly/daily/watcher keep the shared pipeline lock. ETL diagnosis stuck-signal no longer treats neighbor skips as a PM lock storm.
- NEXT: Rebuild/restart **scheduler** on 97.141; confirm next `:30` neighbor run succeeds while watcher is mid-cycle.

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
