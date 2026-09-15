# Optimization Cases

Persistent evidence → decision → proof workspace (CellSens-style loop for PrimeNet).

| | |
|---|---|
| Route | `/optimization-cases` |
| API | `/api/optimization-cases`, `/api/selection-context` |
| Package | `modules/optimization_cases/` + `core/cases/` |
| Store | `databases/cases/optimization_cases.db` |
| Access | admin |
| Version | V1.1 |
| Shell | dedicated workspace (not radio_module) |

## Purpose

Turn detector/SON issues into owned cases with correlated PM/CM/FM evidence, narrative, proposed change, execution ref, and before/after scorecard. Shared selection context syncs map polygons / pasted cell lists into cases.

## Approach

- `core/cases/store.py` — case CRUD + state machine (`open` → … → `closed`/`rejected`).
- `core/cases/correlator.py` — deterministic facts (CM, PM, alarms, neighbor_quality, overshoot pack); template narrative.
- `core/cases/identity.py` — Cases-only cell alias matching (does not flip shared Huawei NH key order).
- `core/cases/scorecard.py` — schema v2 with real post PM pull when `execution_ref` set; verdict improve/worsen/flat/inconclusive.
- `core/cases/impact.py` — Impact Score (PM) for list triage.
- `core/cases/gates.py` — conflict guard + golden-rule check before `approved` (override_note allowed).
- `core/cases/treatments.py` — trusted treatment outcome library.
- Morning Report: `POST /api/optimization-cases/from-morning-report` + bulk button on Morning Report.
- Complaint intake / cluster checklist / energy Cases / PM deeplinks in Cases UI.
- Phase 4: Performance + Plus consume selection; Plus NL→chips (no SQL); `scripts/cases_morning_digest.py` webhook.

## History

- 2026-09-14: V1 Case object, scorecard, correlator, selection context, workspace UI, Open Case from radio issues + SON, map polygon → selection.
- 2026-09-14: Cases uplift Phases 1–4 — real post scorecard, identity lite, morning bulk, cell history, evidence packs, governance, multipliers.

## Plans

- Harden golden-rule parse against structured proposed_change JSON.
- Expand neighbor/overshoot packs when live HO distance fields are richer.
- Optional AI narrative over verified facts only.

## Watch-outs

- Correlator uses existing `cm_store.detect_changes` + `pm.degraded_cells` + alarm join — empty stores yield narrative with gaps, not fake causality.
- Selection API lives on the cases blueprint (admin). Map users without cases access cannot persist server selection.
- No closed-loop OSS write from cases.
- Do not flip shared Huawei `LocalCell Id` preference in NH/`pm_helpers`.
