# Layer Coverage Gaps

Missing coverage-layer cells (metadata).

| | |
|---|---|
| Route | `/layer-coverage` |
| API | `/api/layer-coverage/issues` |
| Package | `modules/layer_coverage/` |
| Detector | `core.radio.insights.layer_coverage_gaps` |
| Access | admin |
| Version | V1.0 |
| Shell | `templates/radio_module.html` |

See [`_radio-engine.md`](_radio-engine.md).

## Purpose

Sites missing an expected layer (e.g. no 4G where 3G exists). Metadata-driven.

## Approach

Do not require PM. Area filter is supported on this builder.

## History

- 2026-08-17 / 2026-08-19: pack + targets.

## Plans

None parked.
