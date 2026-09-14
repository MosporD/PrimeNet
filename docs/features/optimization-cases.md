# Optimization Cases

Persistent evidence → decision → proof workspace (CellSens-style loop for PrimeNet).

| | |
|---|---|
| Route | `/optimization-cases` |
| API | `/api/optimization-cases`, `/api/selection-context` |
| Package | `modules/optimization_cases/` + `core/cases/` |
| Store | `databases/cases/optimization_cases.db` |
| Access | admin |
| Version | V1.0 |
| Shell | dedicated workspace (not radio_module) |

## Purpose

Turn detector/SON issues into owned cases with correlated PM/CM/FM evidence, narrative, proposed change, execution ref, and before/after scorecard. Shared selection context syncs map polygons / pasted cell lists into cases.

## Approach

- `core/cases/store.py` — case CRUD + state machine (`open` → … → `closed`/`rejected`).
- `core/cases/correlator.py` — deterministic facts only (CM deltas, PM degradation, alarms); template narrative (no LLM).
- `core/cases/scorecard.py` — schema v1 baseline/post/control/completeness/rollback warning.
- `core/cases/selection.py` — per-user selection context; client mirror in `static/js/selection_context.js`.
- Radio modules: **Open Optimization Case** in `radio_modules.js` → `POST /api/optimization-cases/from-issue`.
- Network Map: polygon **Use as selection** → selection context → Cases.

## History

- 2026-09-14: V1 Case object, scorecard, correlator, selection context, workspace UI, Open Case from radio issues + SON, map polygon → selection.

## Plans

- Post-change KPI pull into scorecard (replace placeholder when execution_ref set).
- Wire Network Health / SON thumbs directly (radio Open Case already covers radio_module detectors).
- Optional AI narrative over verified facts only.

## Watch-outs

- Correlator uses existing `cm_store.detect_changes` + `pm.degraded_cells` + alarm join — empty stores yield narrative with gaps, not fake causality.
- Selection API lives on the cases blueprint (admin). Map users without cases access cannot persist server selection.
- No closed-loop OSS write from cases.
