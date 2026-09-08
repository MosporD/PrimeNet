# RF Optimization Workbench

Composed radio issues (capacity, coverage, neighbors, …) in one list.

| | |
|---|---|
| Route | `/rf-optimization` |
| API | `/api/rf-optimization/issues` |
| Package | `modules/rf_optimization/` |
| Detector | `core.radio.insights.rf_optimization` |
| Access | admin |
| Version | V1.0 |
| Shell | `templates/radio_module.html` |

See [`_radio-engine.md`](_radio-engine.md).

## Purpose

Workbench feed: several detectors composed, not a new data source.

## Approach

Prefer fixing the underlying detector over special-casing this page.

## History

- 2026-08-17: added. 2026-08-19: vs operator targets.

## Plans

None parked.
