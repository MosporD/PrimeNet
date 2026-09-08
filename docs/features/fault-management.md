# Fault Management

Alarm / fault list.

| | |
|---|---|
| Route | `/fault-management` |
| Module | `modules/fault_management/` |
| Access | all |
| Version | V1.0 |

## Purpose

Show recent OSS/FM alarms. Alarm–PM correlation is a **different** tile (`/alarm-impact`).

## Approach

Do not merge correlator logic into this list UI. Live FM vs sleeping-cell checks live in sleeping-cells / alarm join helpers.

## History

- 2026-08-17: sleeping-cell vs live FM mentioned in the radio pack.

## Plans

None parked.

## Watch-outs

Nokia vs Huawei alarm payloads differ (`core/radio/alarm_join.py`).
