# PrimeNet — progress log

Dated log of verified work. Mark items done only after end-to-end verification.

**Current track:** Module gap-fix pass. Config dictionaries/XML/CM-audit shipped locally; SON ML pipeline also shipped.

**NEXT:** Browser-verify `/xml-parser`, `/excel-generator`, `/parameter-dictionary`, `/performance-dictionary`, `/cm-parameter-audit`. Then `/son-analytics` after `python scripts/pipeline/run_son_ml_job.py --force`.

## 2026-08-19 (SON ML)

- Done: Offline SON ML pipeline — cell-day feature store, PCA+IsolationForest (optional torch AE), weak-label cause mix, neighbor-graph scores, spatial DBSCAN clusters, read-only AMLE/CellMLB treatment scores
- Done: Isolated nightly job `scripts/pipeline/run_son_ml_job.py` after Network Health precalc (`SON_DISABLE_ML=1` kill switch). Flask never imports torch
- Done: SON UI — Anomaly/Topology categories, ML store age, thumbs feedback API; WoW clusters remain if ML store empty
- Modified: `modules/son_analytics/`, `modules/sync/scheduler.py`, `requirements.txt`, `requirements-ml.txt`, load-balancing preview tables

## 2026-08-19

- Done: Network Health scorecard uses operator `threshold_bad` (Retainability 2%, Accessibility 98%, Mobility 95%, Interference −95 dBm, Utilization 80%)
- Done: Radio detectors (capacity, neighbor quality, mobility, IRAT, overshooting HO SR, group health) score against those targets instead of hardcoded 70/95/96/97 cutoffs
- Done: NH APIs no longer 400 on missing KPI (defaults to first precomputed); vendor/rat/top_n hardened; "development stage" label removed
- Done: UI — category scorecard, groups panel, vs-target column, direction-aware delta colors, threshold line on charts, select-page default fix
- Done: TTL cache for expensive radio scans (inventory, neighbors, PM recipes, sleeping detector, sector health, insight builders). `?refresh=1` busts the cache. TTL default 900s (`NCM_RADIO_SECTION_TTL`).
- Done: Sector Health / Excel matrix no longer overlay Sleeping Cells (PM). Coverage is metadata.db only (active vs all configured).
- Done: XML Parser Save/Load Profile endpoints (were 404) + MO/golden-rule validation on upload
- Done: XML Generator pre-flight validation against dictionary, golden rules, and CM snapshot diff
- Done: Parameter Dictionary list index cache (cold ~4 ms) + network values vs default in the parameter detail
- Done: Performance Dictionary index-only list (was 1.76 s); Huawei MAE counter tab; KPI "ref" link from Performance Explorer; data-dependent unit test skips when cache missing
- Done: CM Parameter Audit golden rules: band/area scope, version, approval/baseline; detector honors the same scope
- **NEXT:** Browser-verify `/xml-parser`, `/excel-generator`, `/parameter-dictionary`, `/performance-dictionary`, `/cm-parameter-audit`

## 2026-08-17 (roadmap)

- Done: Nokia LB pipeline verify (rules + RAML XML dry-run + `/api/nokia-load-balancing/verify`). Live OSS import stays confirmation-gated; this host does not auto-push.
- Done: Huawei Load Balancing on Network Balance SQLite (CellMLB propose → Excel/MML). No U2020 push.
- Done: Neighbor 5G-5G + azimuth/freshness; sleeping-cell vs live FM; groups API on Network Health; Change Impact PM across RATs
- Done: Mobility Explorer, Alarm–PM Correlator, Group Health, IRAT/Vendor Border
- Done: KPI aliases for 2G/3G/5G; feature-access guards on radio insight modules; morning report composes the new outputs
- Modified: `app.py`, `core/radio/`, `core/module_access.py`, `core/module_versions.py`, `modules/nokia_load_balancing/`, `modules/huawei_load_balancing/`, new radio modules, `templates/dashboard.html`

## 2026-08-17

- Done: Refreshed this log from git — previous NEXT items (AMLE verify, Power BI embed, constellation checks) were stale vs `main`
- Done: Integrated graphify — AST code map at `graphify-out/` (7110 nodes, 18838 edges, 245 communities, 0 LLM tokens). CLI: `python -m graphify` (exe often not on PATH)
- Done: Graphify maps embedded on `/documentation` (Overview → Code map / Call flow); Lesson 12 removed
- Done: Documentation page fills `--ui-vh` (was `100vh` under 0.67 zoom)
- Done: Course/ARCHITECTURE catch-up — load balancing, Power BI, feature access, vendor creds, Docker
- Modified: `progress.md`, `AGENTS.md`, `docs/course/`, `docs/ARCHITECTURE.md`, `modules/documentation/`
- **NEXT:** Browser-verify `/nokia-load-balancing` with NetAct CM credentials

## 2026-08-11

- Done: Network Balance ingest process monitor in Nokia Load Balancing UI
- Done: Performance Explorer site-search fix
- Done: Docker apt-get fix for networks that block HTTP
- Modified: `Dockerfile`, `modules/nokia_load_balancing/`, `modules/performance/`

## 2026-08-05

- Done: SMB auto-mount for Network Balance on Linux Docker
- Done: Performance chart layouts, search deep links, RET writes, admin activity
- Done: Huawei HedEx in-page TOC links
- Done: Nokia NE list site-ID resolution cache
- Modified: `deploy/`, `docker-compose.yml`, `core/cm_extractor/nokia_discovery.py`, `modules/performance/`, `modules/ret_management/`, `modules/ran_features/hdx.py`

## 2026-08-03

- Done: Nokia Load Balancing (`modules/nokia_load_balancing/`, `/nokia-load-balancing`) — admin AMLE workflow. Legacy `/amle-optimizer` redirects here (not a separate module)
- Done: Huawei Load Balancing stub (`modules/huawei_load_balancing/`)
- Done: Network Balance share auto-load (`\\RNO-WAN\Network Balance`) + daily Nokia/Huawei CSV ingest → SQLite
- Done: File discovery from Mover.py logic (vendor/date from filename)
- Done: Live CM extract (`NOKLTE:AMLEPR`) via existing CM Extractor client
- Done: Proposed RAML XML + Excel export; rules in `modules/nokia_load_balancing/config.py`
- Modified: `app.py`, `core/module_access.py`, `core/module_versions.py`, `templates/dashboard.html`, `sync_config.py`, `db/runtime.py`, `modules/sync/scheduler.py`, `.env.example`

## 2026-08-02

- Done: Scheduler RAM isolation — stream pipeline output, isolate network-health precalc
- Modified: `core/load_monitor.py`, `core/subprocess_runner.py`, `modules/sync/scheduler.py`

## 2026-07-30

- Done: UI zoom pointer sync, Performance Explorer loading UX + site select-all

## 2026-07-28

- Done: XML uploads allow DOCTYPE via defusedxml
- Done: CM Extractor site lists driven from PrimeNet metadata

## 2026-07-23

- Done: PrimeNet `report_date` / `report_time` columns for PM charts
- Done: Neighbor sync on its own cadence with full SQLite replace

## 2026-07-22

- Done: Power BI link-out gallery (`modules/power_bi/`) — catalog-driven list, opens reports in Power BI Service
- Done: Dashboard card + nav for Power BI Reports (`/power-bi`); dark-mode tokens; theme checklist in `docs/FRONTEND_THEME.md`
- Done: Admin-configurable feature access; Developer Documentation module; onboarding course (`docs/course`)
- Done: Per-user vendor credentials; adaptive RAM limits for ingest / heavy PM queries
- **Backlog:** Power BI embed-token flow when workspace gets Premium/Fabric; verify gallery light + dark

## 2026-07-06

- In progress: dashboard / module UI unification (constellation theme, shared CSS) — `checklist.md` still open
- Modified: `templates/dashboard.html`, `login.html`, `register.html`, `radio_module.html`
- Modified: `static/css/dashboard.css`, `constellation.css`, `radio_modules.css`, `static/js/common.js`, `constellation.js`
- Modified: module templates under `modules/*/templates/` (admin, network health, performance, etc.)
- **Backlog:** verify constellation background + module pages in browser; confirm mobile layout on `radio_module.html`

## Template

```
## YYYY-MM-DD
- Done: <what was verified>
- **NEXT**: <single immediate task>
```
