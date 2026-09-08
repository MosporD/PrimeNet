# Radio API

Tiny helper: area list for the shared filter bar.

| | |
|---|---|
| Route | `/api/radio/areas` |
| Module | `modules/radio_api/routes.py` (~15 lines) |
| Core | `core.radio.metadata.list_areas()` |
| Access | authenticated (same as radio modules) |

## Purpose

Populate area dropdowns. Not a dashboard card.

## Approach

Keep it a one-call wrapper. New shared radio metadata endpoints belong in `core/radio/metadata.py` first.

## History

Introduced with the radio filter shell.

## Plans

None. Do not grow this into a second radio engine.
