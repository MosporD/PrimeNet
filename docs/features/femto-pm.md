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

## History

Inventory (2026-08-31): ~5.8 GB femto PM — keep SQLite.

## Plans

Stay SQLite.

## Watch-outs

Do not attach femto into Nokia/Huawei PM Explorer tables.
