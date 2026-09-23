# Optimization Cases — progress

Detailed dated log for this blueprint. Brief: [`optimization-cases.md`](optimization-cases.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

---
## From brief History (migrated 2026-09-17)

- 2026-09-14: V1 Case object, scorecard, correlator, selection context, workspace UI, Open Case from radio issues + SON, map polygon → selection.
- 2026-09-14: Cases uplift Phases 1–4 — real post scorecard, identity lite, morning bulk, cell history, evidence packs, governance, multipliers.

## 2026-09-14 (Cases uplift Phases 1–4)

- Done: Real post-KPI scorecard (schema v2) + verdict on `execution_ref`.
- Done: `core/cases/identity.py` lite for correlator/scorecard joins only.
- Done: Morning Report `from-morning-report` API + bulk button; 7d `source_issue_id` dedupe.
- Done: Same-cell case history (30d) in Case detail.
- Done: Phase 2 packs — PM deeplink, neighbor/overshoot facts, complaint intake, cluster checklist.
- Done: Phase 3 — Impact Score (PM), conflict + golden gates, energy Cases, trusted treatments (+ SON prefer).
- Done: Phase 4 — selection consume in Performance/Plus; NL→chips (no SQL); digest script.
- Tests: expand `core.cases.test_cases` (scorecard post, identity, morning dedupe, conflict, impact/treatments, NL).

## 2026-09-14 (Optimization Cases A–C)

- Done: `core/cases/` — schema/store/state machine, deterministic correlator, scorecard v1, per-user selection context.
- Done: Module `/optimization-cases` workspace + APIs; dashboard tile; admin nav.
- Done: Radio modules **Open Optimization Case**; SON detail **Open Optimization Case**; Network Map polygon **Use as selection**.
- Done: Unit tests `core.cases.test_cases` (4/4); smoke script `scripts/_smoke_optimization_cases.py`.
