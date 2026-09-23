# Configuration Data Extractor

Live CM from Nokia NetAct / Huawei U2020. Mini-app. Lesson 08.

| | |
|---|---|
| Route | `/cm-extractor` |
| HTTP | `modules/cm_extractor/routes.py` (~32 endpoints) |
| Logic | `core/cm_extractor/` |
| Access | all (write/reimport still gated in-module) |
| Version | V1.1 |

## Purpose

Discover NEs, extract MO parameters, schedule jobs, Excel export, Nokia reimport (`actualImport`).

## Approach

- Identify which of the 7 phases you are in (setup → discover → pick → extract → jobs → reimport → notifications) then open the matching `core/cm_extractor/` file.
- CLI helpers in `modules/cm_extractor/__init__.py` beat the UI for learning.
- Input budget is larger (8 MB) in `app.py` for this API.
- **Do not auto-push** OSS from this laptop. Reimport is preview + confirm.
- Tests: `core/cm_extractor/test_*.py`.
- Neighbor/relation MOs (e.g. `EUTRANINTERFREQNCELL`) are high-cardinality — refuse >40 NEs; use smaller MML chunks.

## Progress

Dated work log: [`cm-extractor.progress.md`](cm-extractor.progress.md). Do not duplicate long history here — update the progress file when this feature changes. Keep **Plans** as the module NEXT.


## Plans

No drive-by MO list expansion. Vendor API refs: `docs/HUAWEI_CM_OPEN_API_REFERENCE.md`, `docs/CM_OPEN_API_RNC_BSC_REFERENCE.md`.

## Watch-outs

Nokia Load Balancing consumes this stack for `AMLEPR`. Site lists should come from PrimeNet metadata (`site_catalog.py`), not a parallel inventory.
East Amman Huawei 4G ≈220 eNodeBs — `CELL` is fine area-wide; inter-freq neighbor MOs need batched site picks.
