# SON Optimization Insights — progress

Detailed dated log for this blueprint. Brief: [`son-analytics.md`](son-analytics.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

**Parked:** SON trust click-through; Huawei 4G identity in shared `pm_helpers` still prefers `LocalCell Id`.

**NEXT:** Browser-click `/son-analytics`.

---
## From brief History (migrated 2026-09-17)

- 2026-09-08: Removed READ-ONLY header badge; SON topbar aligned to standard module header.
- 2026-08-19: ML pipeline + UI categories + thumbs API.
- 2026-08-30: trust pass — floors, dedupe, HTTP-verified APIs. Topology empty (graph scores 10 under old 8k line cap). First `/api/son/summary` ~13 min, then 1h cache.
- 2026-09-02: rebuilt graph join. Nokia 4G neighbors loaded (2.35M rows). Huawei SON keys by Cell Name. Topology graph≥55: Nokia 5417, Huawei 3260.

## 2026-09-08 (dark-mode UI fixes)

- Done: Cell Heatmap status text, Femto Create KPI button, SON header (no READ-ONLY, standard topbar), CM Extractor scrollbars, Parameter Audit golden-rules panel, XML Parser plan validation, Overshooting/radio-module opaque dark background.
- Deploy note: server must `git pull` to `a575aeba+` then rebuild; these fixes are local until pushed.

## 2026-09-02 (SON ML rebuild)

- Done: Topology join no longer samples map lines. SQL aggregates Huawei `Local_cell_name`/`Target_Cell_Name` and Nokia `Source_LNCEL_name` + ECI→metadata `cell_name` (NetAct leaves Target LNCEL empty).
- Done: SON-only Huawei Cell Name keys (`prefer_cell_cols` on `_cell_daily_kpi_series`). Health still uses LocalCell Id. Huawei scores 27,547 cells (was ~124 numeric ids).
- Done: Loaded unused Nokia 4G export (`raw/nokia/neighbor/all/hourly/4G`, 2,354,489 rows) via `load_nokia_neighbor_raw_to_db.py --only-4g` (2G/3G untouched).
- Done: Graph isolation is 0 when no embedding neighbor (no fake 10.0). HO / recip / distance penalties still apply.
- Verified: Nokia 15,236/15,482 cells with neighbors, 5,417 graph≥55; Huawei 22,775/27,547 matched, 3,260 graph≥55. Tests 15/15 (`test_neighbor_graph.py` + `test_recommendations.py`).
- Not done: no browser click this session; treatment still heuristic (0 CM+PM pairs). No 2G/3G/5G ML. No closed-loop.

## 2026-08-30 (SON trust)

- Done: isolated branch `son/trust-insights`; progress parked off CM Extractor
- Done: `test_recommendations.py` — Cluster min-size / spatial key, Anomaly floor 70 + skip clustered + missed_by_wow + alias dedupe, Topology floor 55, rules-only fallback. `python modules/son_analytics/test_recommendations.py` — 10/10
- Done: `python scripts/pipeline/run_son_ml_job.py --force` — Nokia 15466 scores / 807841 cell-days (445s); Huawei 122 scores / 4176 cell-days (131s); treatment still heuristic (0 CM+PM pairs). Job now stamps PM fingerprint at save so a rebuild is not immediately self-stale
- Done: HTTP verify (minimal Flask app, admin session): page 200 Read-only + filters; ml-status available; summary Cluster 12 / Anomaly 36 / Topology 0; category/severity/vendor filters do not leak; detail + thumbs; refresh 200; missing id 404
- Done: load errors no longer swallowed in `son_analytics.js`; Anomaly/Topology dedupe vendor-alias keys
- Diagnose (not fixed here): Huawei cells named like `144.0` because `pm_helpers` prefers `LocalCell Id` (61 distinct) over `Cell Name` (27k). Topology empty because graph scores were all 10 (no neighbor match under the old 8000-line cap) — cap raised, needs another ML rebuild to take effect
- First `/api/son/summary` ~13 min (WoW scan of daily PM); cached 1h after that

## 2026-08-19 (SON ML)

- Done: Offline SON ML pipeline — cell-day feature store, PCA+IsolationForest (optional torch AE), weak-label cause mix, neighbor-graph scores, spatial DBSCAN clusters, read-only AMLE/CellMLB treatment scores
- Done: Isolated nightly job `scripts/pipeline/run_son_ml_job.py` after Network Health precalc (`SON_DISABLE_ML=1` kill switch). Flask never imports torch
- Done: SON UI — Anomaly/Topology categories, ML store age, thumbs feedback API; WoW clusters remain if ML store empty
- Modified: `modules/son_analytics/`, `modules/sync/scheduler.py`, `requirements.txt`, `requirements-ml.txt`, load-balancing preview tables
