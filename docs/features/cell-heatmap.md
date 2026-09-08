# Network Coverage Heatmap

KPI heatmap over geography.

| | |
|---|---|
| Route | `/cell-heatmap` |
| Module | `modules/cell_heatmap/routes.py` |
| Access | all |
| Version | V1.0 |
| Data | `connect_metadata`, `connect_pm_db` |

## Purpose

Map points colored by a selected KPI for the current vendor/RAT/time.

## Approach

PM opens already go through `connect_pm_db` (Postgres-ready). Column discovery uses `PRAGMA table_info` (adapted on PG). Missing tables should stay empty results, not 500s.

## History

No major dated rewrite beyond shared PM/open_db plumbing (2026-08-31).

## Plans

None parked.

## Watch-outs

Type hints still say `sqlite3.Connection`; runtime may be `PgConn`.
