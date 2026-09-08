# Network Health Overview

Precomputed KPI scorecard. Source of operator thresholds used by radio detectors.

| | |
|---|---|
| Route | `/network-health` |
| Module | `modules/network_health/` (`config.py`, `logic.py`, `precalc_job.py`, `precalc_store.py`) |
| Access | admin |
| Version | V1.1 |

## Purpose

Category scorecard (retainability, accessibility, mobility, interference, utilization) vs operator `threshold_bad`. Nightly precalc store; page reads it.

## Approach

- Change targets in `config.py` / presets — detectors import `score_vs_preset`.
- Missing KPI → default to first precomputed, do not 400.
- Precalc DB stays SQLite (not a Postgres domain).
- Groups panel uses groups DBs; `?refresh=1` busts TTL cache.

## History

- 2026-08-19: operator thresholds, vs-target column, groups panel, cache TTL.

## Plans

Scheduler already runs precalc before SON ML. Do not compute the full scorecard synchronously in the request.

## Watch-outs

`CATEGORY_PRESETS` is reused by the radio engine. A threshold change is a **network-wide** scoring change.
