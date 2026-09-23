# Configuration Dashboard

Hardware (`RMOD_R`) Sankey + WNCELG site-group split view. Shared daily Nokia pull.

| | |
|---|---|
| Route | `/configuration-dashboard` |
| Module | `modules/configuration_dashboard/` (+ Hardware engine in `modules/rru_inventory/`) |
| Access | all |
| Version | V1.1 |

## Purpose

One place for Nokia configuration inventory snapshots: radio hardware flow (Area → Tech/band → RRU) and whether each MRBTS site has multiple `WNCELG` groups (split) or a single group (no split).

## Approach

Tabs: **Hardware** (existing RMOD_R Sankey / Excel from `rmod_snapshot.db`) and **WNCELG** (Area → Split / No split → group-count Sankey from `wncelg_snapshot.db`, same layer toggles + status chips + site filter). UI reads snapshots only — no NetAct on Load.

Shared ingest at **04:00** (`RRU_INVENTORY_CRON_HOUR` / `MINUTE`) pulls full-network `RMOD_R` then `WNCELG` via the shared Nokia account. Admin → Data Sync triggers the same job. Disable with `NCM_DISABLE_RRU_INVENTORY_INGEST=1`.

Split rule: `group_count > 1` per site → **split**, else **no_split**.

Legacy `/rru-inventory` redirects to `?tab=hardware`.

## Progress

Dated work log: [`configuration-dashboard.progress.md`](configuration-dashboard.progress.md).

## Plans

None parked.

## Watch-outs

WNCELG MO class is resolved from the NetAct catalog (abbreviation `WNCELG`); fallback `com.nokia.srbts.wcdma:WNCELG`. Hardware list-param ingest still uses `getManagedObjects` for `active*CellsList` (scalar query rejected).
