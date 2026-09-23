# Performance Dictionary

KPI / counter reference (Nokia Performance pack + Huawei MAE).

| | |
|---|---|
| Route | `/performance-dictionary` |
| Module | `modules/performance_dictionary/` |
| Access | all |
| Version | V1.1 |

## Purpose

Look up counter meanings. Explorer “ref” links land here.

## Approach

Index-only list (was 1.76 s). Tests skip when cache files are missing. Do not parse full Nokia HTML on every list request.

## Progress

Dated work log: [`performance-dictionary.progress.md`](performance-dictionary.progress.md). Do not duplicate long history here — update the progress file when this feature changes. Keep **Plans** as the module NEXT.


## Plans

**Parked:** browser-verify.

## Watch-outs

Not Parameter Dictionary. Cache miss ≠ code bug.
