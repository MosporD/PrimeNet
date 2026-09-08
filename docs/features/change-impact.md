# Change Impact Tracker

CM change vs KPI shift.

| | |
|---|---|
| Route | `/change-impact` |
| API | `/api/change-impact/issues` |
| Package | `modules/change_impact/` |
| Detector | `core.radio.insights.change_impact` |
| Store | `core/radio/cm_store.py` snapshots |
| Access | admin |
| Version | V1.0 |
| Shell | `templates/radio_module.html` |

See [`_radio-engine.md`](_radio-engine.md).

## Purpose

Correlate configuration snapshots with PM across RATs.

## Approach

Snapshot pipeline is CM extract → `cm_store`. Do not require a live OSS pull inside the issues request.

## History

- 2026-08-17: PM across RATs.

## Plans

None parked.
