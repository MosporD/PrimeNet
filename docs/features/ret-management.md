# RET Management

Remote electrical tilt read/propose.

| | |
|---|---|
| Route | `/ret-management` |
| Module | `modules/ret_management/` (`logic.py`, `test_logic.py`) |
| Access | all |
| Version | V1.0 |

## Purpose

Antenna RET values. Unit tests in `test_logic.py` — read those first.

## Approach

Treat tests as spec. Live writes to OSS follow the same confirmation culture as CM reimport — do not add silent push.

## History

- 2026-08-05: RET writes mentioned with admin activity.

## Plans

None parked.

## Watch-outs

RET is mechanical/electrical tilt, not load balancing.
