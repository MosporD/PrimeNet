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

## Progress

Dated work log: [`parameter-dictionary.progress.md`](parameter-dictionary.progress.md). Do not duplicate long history here — update the progress file when this feature changes. Keep **Plans** as the module NEXT.


## Plans

**Parked:** browser-verify XML parser / generator / perf dictionary / CM audit. Parameter Dictionary layout widened 2026-09-02 — still worth a click-through.

## Watch-outs

Not Performance Dictionary (counters). Not CM Extractor (live values).
