# Performance Reports

Report builder / archive.

| | |
|---|---|
| Route | `/reports` |
| Module | `modules/reports/` (`routes.py`, `metadata_helpers.py`, `sector_coverage_data.py`) |
| Access | all |
| Version | V1.3 |

## Purpose

Build downloadable performance reports from metadata + PM; archive rows live in the app DB (`performance_reports`).

## Approach

App-table writes go through `connect_app()` / `execute_query` (Postgres-safe). Sector coverage is metadata, not Sleeping Cells overlay.

## Progress

Dated work log: [`reports.progress.md`](reports.progress.md). Do not duplicate long history here — update the progress file when this feature changes. Keep **Plans** as the module NEXT.


## Plans

None parked.

## Watch-outs

`last_insert_rowid` vs `RETURNING id` is handled in `database_enhanced._insert_return_id`.
