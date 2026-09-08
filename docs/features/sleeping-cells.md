# Sleeping Cell Detector

Active in CM, traffic collapsed vs own daily baseline.

| | |
|---|---|
| Route | `/sleeping-cells` |
| API | `/api/sleeping-cells/issues` |
| Package | `modules/sleeping_cells/` (**has `logic.py`**) |
| Access | admin |
| Version | V1.1 |
| Shell | `templates/radio_module.html` |

See [`_radio-engine.md`](_radio-engine.md).

## Purpose

Silent outages: cell still configured Active, payload gone vs baseline. Optional live FM cross-check.

## Approach

This is the **one** radio tile with real module-local logic. Tune `detect_sleeping_cells` here, not by copying into Sector Health.

## History

- 2026-08-17: vs live FM. 2026-08-19: V1.1; Sector Health no longer overlays this.

## Plans

None parked.

## Watch-outs

Do not paint sleeping cells onto Sector Health coverage.
