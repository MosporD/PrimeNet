# Performance Explorer Plus

Nokia raw-counter warehouse and ad-hoc KPI studio.

| | |
|---|---|
| Route | `/performance-explorer-plus` |
| Module | `modules/performance_explorer_plus/` |
| Core | `core/pm_plus/` |
| Access | all (authenticated) |
| Version | V1.0 |

## Purpose

Ingest Nokia NBI 15‑minute `.gz` (TS 32.435) into a warehouse, roll up to hour/day, and let engineers build ratio-of-sums KPIs with completeness — separate from Excel-KPI `/performance`.

## Approach

- Continuous ingest workers (`scripts/pm_plus/run_ingest_worker.py`) — not inside Gunicorn.
- Streaming XML parse (`core/pm_plus/nokia_parser.py`); ledger for idempotent claims.
- SQLite fallback locally; set `PM_PLUS_DATABASE_URL` for Postgres schema `pm_plus`.
- KPI formulas evaluated at query time (`core/pm_plus/kpi_compiler.py`).
- Huawei later via `VendorAdapter` in `core/pm_plus/adapter.py` (stub only).

## Progress

Dated work log: [`performance-explorer-plus.progress.md`](performance-explorer-plus.progress.md). Do not duplicate long history here — update the progress file when this feature changes. Keep **Plans** as the module NEXT.


## Plans

Tune live SFTP workers against &lt;15 min lag SLO on production hosts. Enable Huawei adapter when SFTP paths exist.

## Watch-outs

- Do not confuse with `/performance` (pre-baked Excel KPIs) or `/performance-analytics` (Huawei MAE API).
- Day is built from raw ROP, not from hour (AVG correctness).
- Ingest must run as a separate process: `python scripts/pm_plus/run_ingest_worker.py`.
- Never commit `NOKIA_PM_FTP_*` passwords.
