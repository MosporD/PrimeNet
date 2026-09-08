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

## History

- 2026-08-19: index-only list, Huawei MAE tab, KPI ref from Explorer.

## Plans

**Parked:** browser-verify.

## Watch-outs

Not Parameter Dictionary. Cache miss ≠ code bug.
