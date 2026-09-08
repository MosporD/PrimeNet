# Performance Reports

Report builder / archive.

| | |
|---|---|
| Route | `/reports` |
| Module | `modules/reports/` (`routes.py`, `metadata_helpers.py`, `sector_coverage_data.py`) |
| Access | all |
| Version | V1.1 |

## Purpose

Build downloadable performance reports from metadata + PM; archive rows live in the app DB (`performance_reports`).

## Approach

App-table writes go through `connect_app()` / `execute_query` (Postgres-safe). Sector coverage is metadata, not Sleeping Cells overlay.

## History

- 2026-08-19: Sector Health / Excel matrix coverage = metadata only.
- Last-insert unified for app Postgres (2026-08-31 phase 1).

## Plans

None parked.

## Watch-outs

`last_insert_rowid` vs `RETURNING id` is handled in `database_enhanced._insert_return_id`.
