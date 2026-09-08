# Sync / pipeline (ETL)

UI at `/sync`. Canonical pull/load lives in `pipeline/`; `modules/sync/` is the control plane + processors.

| | |
|---|---|
| UI | `modules/sync/routes.py`, `scheduler.py` |
| Processors | `pm_processor.py`, `metadata_processor.py`, `group_processor.py`, `db_migration.py` |
| Canonical ETL | `pipeline/orchestrators/`, `pipeline/paths.py` |
| Paths | `sync_config.py` |
| Access | authenticated (ops); scheduler is a separate process |

## Purpose

SFTP pull of Nokia/Huawei PM, metadata, groups, neighbors; load into canonical DBs; retention; Network Health / SON jobs after load.

## Approach

- New work goes in `pipeline/`, not ad-hoc `scripts/pipeline/` copies.
- Table names: `pm_table_name()` in `sync_config`. Huawei PM uses the same hourly tables as Nokia.
- Writes: `open_db(db_path)` so Postgres domains work when enabled.
- Prefer orchestrators (`orchestrate_hourly_full.py`, daily, watcher) over one-off scripts.
- Huawei daily raw stages in `raw/huawei/{cells,groups}/all/daily` then RAT-split.

## History

- 2026-08-02: scheduler RAM isolation.
- 2026-08-31: ingest paths wired through `open_db` for optional Postgres.

## Plans

Do not run a 14 GB Postgres migrate from this laptop. SON ML job is after NH precalc (`scripts/pipeline/run_son_ml_job.py`); `SON_DISABLE_ML=1` kill switch.

## Watch-outs

Group ingest `process_group_file` is currently **reset-mode disabled**. `RAW_PULL_CLEAR_BEFORE` / prune flags are sharp. Never commit `raw/` or `*.db`.
