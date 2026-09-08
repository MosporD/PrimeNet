# SON Optimization Insights

Read-only cluster / anomaly / topology insights. **No closed-loop.** 4G-focused ML store.

| | |
|---|---|
| Route | `/son-analytics` |
| Module | `modules/son_analytics/` (`logic.py`, `pm_helpers.py`, `ml/`) |
| Job | `scripts/pipeline/run_son_ml_job.py` (after NH precalc) |
| Access | admin |
| Version | V1.1 |

## Purpose

WoW clusters + optional ML scores (PCA/IF, neighbor-graph topology, spatial DBSCAN). Flask **never** imports torch.

## Approach

- Kill switch: `SON_DISABLE_ML=1`.
- `pm_helpers.py` is shared by Health/SON. Default cell-id order is unchanged (Huawei `LocalCell Id` before `Cell Name`). SON ML passes `prefer_cell_cols=["Cell Name"]` so Topology can join neighbor `Local_cell_name`.
- Neighbor graph: `ml/neighbor_agg.py` aggregates vendor 4G export tables (not the map-line 100k sampler). Nokia targets resolve ECI → metadata `cell_name`.
- Tests: `modules/son_analytics/test_recommendations.py`, `modules/son_analytics/ml/test_neighbor_graph.py`.

## History

- 2026-08-19: ML pipeline + UI categories + thumbs API.
- 2026-08-30: trust pass — floors, dedupe, HTTP-verified APIs. Topology empty (graph scores 10 under old 8k line cap). First `/api/son/summary` ~13 min, then 1h cache.
- 2026-09-02: rebuilt graph join. Nokia 4G neighbors loaded (2.35M rows). Huawei SON keys by Cell Name. Topology graph≥55: Nokia 5417, Huawei 3260.

## Plans

**NEXT:** browser-click `/son-analytics`. No 2G/3G/5G ML. No closed-loop.

## Watch-outs

Treatment scores are heuristic when CM+PM pairs are 0. Do not swap Huawei `LocalCell Id` vs `Cell Name` in the shared helper — that collapses Health cells to ~61 ids. Nokia 4G Target LNCEL is empty in NetAct HO analysis exports; SON must use `eci_id`.
