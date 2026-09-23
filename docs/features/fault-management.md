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

## Progress

Dated work log: [`fault-management.progress.md`](fault-management.progress.md). Do not duplicate long history here — update the progress file when this feature changes. Keep **Plans** as the module NEXT.


## Plans

None parked.

## Watch-outs

Nokia vs Huawei alarm payloads differ (`core/radio/alarm_join.py`).
