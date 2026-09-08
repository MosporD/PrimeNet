# Alarm–PM Correlator

Join recent FM alarms to degraded PM cells.

| | |
|---|---|
| Route | `/alarm-impact` |
| Package | `modules/alarm_impact/` |
| Detector | `core.radio.alarm_impact.alarm_impact` |
| Join | `core/radio/alarm_join.py` |
| Access | admin |
| Version | V1.0 |
| Shell | `templates/radio_module.html` |

See [`_radio-engine.md`](_radio-engine.md).

## Purpose

Show which poor-KPI cells also have live/recent alarms.

## Approach

Alarm fetch is best-effort per vendor. Empty alarm source → issues without alarm enrichment, not a 500.

## History

- 2026-08-17: added.

## Plans

None parked.

## Watch-outs

Fault Management (`/fault-management`) is the raw list. This is the join.
