# Radio Morning Report

Daily digest of the radio detectors.

| | |
|---|---|
| Route | `/radio-morning-report` |
| API | `/api/radio-morning-report/issues` |
| Package | `modules/radio_morning_report/` |
| Detector | `core.radio.insights.radio_morning_report` |
| Access | admin |
| Version | V1.0 |
| Shell | `templates/radio_module.html` |

See [`_radio-engine.md`](_radio-engine.md).

## Purpose

Compose capacity / neighbor / overshooting / sleeping / … into one briefing list.

## Approach

Fix child detectors; this page only composes. Keep `limit` modest (default 100).

## History

- 2026-08-17: composes the new radio outputs.

## Plans

None parked.
