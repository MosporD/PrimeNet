# Capacity Hotspots

High-utilization cells.

| | |
|---|---|
| Route | `/capacity-hotspots` |
| API | `/api/capacity-hotspots/issues` |
| Package | `modules/capacity_hotspots/` |
| Detector | `core.radio.insights.capacity_hotspots` |
| Access | admin |
| Version | V1.0 |
| Shell | `templates/radio_module.html` |

See [`_radio-engine.md`](_radio-engine.md).

## Purpose

Rank cells that breach utilization `threshold_bad` (default 80%).

## Approach

KPI recipes live in `core/radio/pm.py`. Do not hardcode 80 in the thin module.

## History

- 2026-08-17 / 2026-08-19: pack + operator targets.

## Plans

None parked.
