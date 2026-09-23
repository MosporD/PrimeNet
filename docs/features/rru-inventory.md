# Radio Hardware Inventory Report

Nokia RMOD_R hardware Sankey — now the **Hardware** tab of Configuration Dashboard.

| | |
|---|---|
| Route | `/configuration-dashboard?tab=hardware` (legacy `/rru-inventory` redirects) |
| Module | `modules/rru_inventory/` (engine) · UI in `modules/configuration_dashboard/` |
| Access | all |
| Version | V1.2 (engine) |

## Purpose

Daily NetAct inventory of physical radio modules. UI reads a persisted snapshot only (no NetAct on Load). Tech from `activeGsmCellsList` / `activeWcdmaCellsList` / `activeLteCellsList` / `activeNrCellsList`; 3G/4G expand to band labels via local metadata; RRU type from `productName`. Unused (all lists empty) stays filterable.

## Approach

Shared Configuration Dashboard ingest at **04:00** (`RRU_INVENTORY_CRON_HOUR` / `MINUTE`) runs full-network `RMOD_R` **and** `WNCELG` into separate snapshot DBs. Admin → Data Sync triggers the same job. Hardware UI: Configuration Dashboard → Hardware tab.

See also: [`configuration-dashboard.md`](configuration-dashboard.md).

## Progress

Dated work log: [`rru-inventory.progress.md`](rru-inventory.progress.md). Do not duplicate long history here — update the progress file when this feature changes. Keep **Plans** as the module NEXT.

## Plans

None parked — product surface moved to Configuration Dashboard.

## Watch-outs

`active*CellsList` are StructuredValue / list params — NetAct rejects `@activeGsmCellsList` ("scalar value required"). Ingest uses `dn()` + `getManagedObjects`, not parameter query expressions.
Disable with `NCM_DISABLE_RRU_INVENTORY_INGEST=1` (gates shared RMOD+WNCELG job). Scheduler registers only when ETL/scheduler is enabled on the server.
