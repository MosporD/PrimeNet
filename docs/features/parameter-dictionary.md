# Parameter Dictionary

Vendor parameter reference (Nokia + scraped Huawei HTML).

| | |
|---|---|
| Route | `/parameter-dictionary` |
| Module | `modules/parameter_dictionary/` |
| Access | all |
| Version | V1.1 |

## Purpose

Searchable MO/parameter docs. Huawei pages are **runtime-served scrapes**.

## Approach

- **Do not edit** `modules/parameter_dictionary/huawei_params/` (~19k HTML files).
- List uses an index cache (cold ~4 ms after 2026-08-19). Detail page can show network values vs default via CM store.
- `ai_service.py` is optional assist — keep it from blocking the dictionary if the model is down.

## History

- 2026-08-19: list index cache + network values vs default.
- 2026-09-02: Nokia/Huawei workspace uses full viewport (dropped 1400px content cap + nested 68vh table).

## Plans

**Parked:** browser-verify XML parser / generator / perf dictionary / CM audit. Parameter Dictionary layout widened 2026-09-02 — still worth a click-through.

## Watch-outs

Not Performance Dictionary (counters). Not CM Extractor (live values).
