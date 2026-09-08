# Group / Cluster Health

Group-level PM health (BSC/RNC/performance groups).

| | |
|---|---|
| Route | `/group-health` |
| Package | `modules/group_health/` |
| Detector | `core.radio.groups.group_health` |
| Access | admin |
| Version | V1.0 |
| Shell | `templates/radio_module.html` |

See [`_radio-engine.md`](_radio-engine.md).

## Purpose

Scan vendor group DBs for degraded controller/group KPIs.

## Approach

Builder may **not** take `area` (aggregates span areas) — `make_radio_module` already handles that. Group ingest is currently disabled in reset mode (`group_processor.process_group_file`).

## History

- 2026-08-17: groups API on Network Health + this module. 2026-08-19: vs-target.

## Plans

None parked.

## Watch-outs

Network Health has a groups **panel**; this tile is the issue list.
