# Huawei Load Balancing

CellMLB proposals from the same Network Balance store. **Not a stub** (course Lesson 07 is stale).

| | |
|---|---|
| Route | `/huawei-load-balancing` |
| Module | `modules/huawei_load_balancing/` (`logic.py`, `config.py`) |
| Shared store | `modules/nokia_load_balancing/balance_store.py` |
| Access | admin |
| Version | V1.2 |

## Purpose

NOK Huawei sectors → CellMLB propose → Excel/MML. **No U2020 push.**

## Approach

Reuse Nokia ingest/snapshots (`vendor="Huawei"`). Do not invent a second balance DB. Do not add U2020 write unless Malek asks (and then confirmation-gate like Nokia).

## History

- 2026-08-17: Huawei LB on Network Balance SQLite (propose → Excel/MML). No U2020 push.

## Plans

No OSS push. Course still says “stub” — ignore that.

## Watch-outs

`huawei_configured()` is CM extractor config, not a guarantee U2020 is reachable from this laptop.
