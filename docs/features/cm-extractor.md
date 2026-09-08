# Configuration Data Extractor

Live CM from Nokia NetAct / Huawei U2020. Mini-app. Lesson 08.

| | |
|---|---|
| Route | `/cm-extractor` |
| HTTP | `modules/cm_extractor/routes.py` (~32 endpoints) |
| Logic | `core/cm_extractor/` |
| Access | all (write/reimport still gated in-module) |
| Version | V1.0 |

## Purpose

Discover NEs, extract MO parameters, schedule jobs, Excel export, Nokia reimport (`actualImport`).

## Approach

- Identify which of the 7 phases you are in (setup → discover → pick → extract → jobs → reimport → notifications) then open the matching `core/cm_extractor/` file.
- CLI helpers in `modules/cm_extractor/__init__.py` beat the UI for learning.
- Input budget is larger (8 MB) in `app.py` for this API.
- **Do not auto-push** OSS from this laptop. Reimport is preview + confirm.
- Tests: `core/cm_extractor/test_*.py`.

## History

Long-lived. Job scheduler uses `connect_app()` (2026-08-31). Sample Huawei workbook under `uploads/cm_extractor/samples/`.

## Plans

No drive-by MO list expansion. Vendor API refs: `docs/HUAWEI_CM_OPEN_API_REFERENCE.md`, `docs/CM_OPEN_API_RNC_BSC_REFERENCE.md`.

## Watch-outs

Nokia Load Balancing consumes this stack for `AMLEPR`. Site lists should come from PrimeNet metadata (`site_catalog.py`), not a parallel inventory.
