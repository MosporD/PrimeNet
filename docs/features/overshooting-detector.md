# Overshooting Detector

Long neighbor + distance + HO evidence.

| | |
|---|---|
| Route | `/overshooting-detector` |
| API | `/api/overshooting-detector/issues` |
| Package | `modules/overshooting_detector/` |
| Detector | `core.radio.insights.overshooting_candidates` |
| Access | admin |
| Version | V1.0 |
| Shell | `templates/radio_module.html` |

See [`_radio-engine.md`](_radio-engine.md).

## Purpose

Cells serving too far (HO SR / distance / elevation helpers).

## Approach

Elevation lookups: `core/elevation.py` / `/elevation`. Do not pull new DEM formats without asking.

## History

- 2026-08-17: HO SR overshooting. 2026-08-19: vs-target.

## Plans

None parked.
