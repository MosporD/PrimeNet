# Femto PM

Femtocell performance explorer. Own SQLite stores — **not** in the Postgres domain catalog.

| | |
|---|---|
| Route | `/femto-pm` |
| Module | `modules/femto_pm/` (`kpi_store.py`) |
| Access | all |
| Version | V1.0 |

## Purpose

KPIs for femto/home cells. Separate DBs under `databases/cells/` (`femto_pm_cells.db`, `femto_user_kpis.db`).

## Approach

Keep femto SQLite even after PM Postgres cutover. Do not route these paths through `pg_domains`.

## Progress

Dated work log: [`femto-pm.progress.md`](femto-pm.progress.md). Do not duplicate long history here — update the progress file when this feature changes. Keep **Plans** as the module NEXT.


## Plans

Stay SQLite.

## Watch-outs

Do not attach femto into Nokia/Huawei PM Explorer tables.
