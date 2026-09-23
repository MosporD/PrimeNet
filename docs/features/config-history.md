# Config History

Timeline of configuration changes.

| | |
|---|---|
| Route | `/config-history` |
| Module | `modules/config_history/` |
| Access | all |
| Version | V1.0 |

## Purpose

Browse recorded CM changes (snapshot/audit trail).

## Approach

Backed by CM snapshot store / app tables — check `routes.py` before assuming a new DB. Change Impact is the **KPI correlation** tile, not this timeline.

## Progress

Dated work log: [`config-history.progress.md`](config-history.progress.md). Do not duplicate long history here — update the progress file when this feature changes. Keep **Plans** as the module NEXT.


## Plans

None parked.
