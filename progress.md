# PrimeNet — progress log

Dated log of verified work. Mark items done only after end-to-end verification.

**Current track:** Dark-mode contrast fixes across heatmap / femto / SON / CM / audit / XML / radio modules.

**Parked:** SON trust browser click-through (`/son-analytics` Topology). Server still may be on `afc1124f` until pull of bulk + these fixes. Huawei 4G identity in shared `pm_helpers` still prefers `LocalCell Id` (Health unchanged).

**NEXT:** Browser-verify dark-mode contrast fixes (heatmap, femto, CM extract scrollbars, parameter audit golden rules, XML plan validation, overshooting bg) and SON header without READ-ONLY.

## 2026-09-08 (dark-mode UI fixes)

- Done: Cell Heatmap status text, Femto Create KPI button, SON header (no READ-ONLY, standard topbar), CM Extractor scrollbars, Parameter Audit golden-rules panel, XML Parser plan validation, Overshooting/radio-module opaque dark background.
- Deploy note: server must `git pull` to `a575aeba+` then rebuild; these fixes are local until pushed.

## 2026-09-06 (UI unification)

- Done: Extracted login inline CSS → `static/css/login.css`; register + activation rebuilt on the same NexusCore constellation shell.
- Done: Module body page-classes for 11 templates; Documentation + SON logout; `common.js` theme toggle mounts on `.doc-header-right`; dark page-class allowlist expanded in `common.css`.
- Done: Dashboard legacy op-sites hide rule moved from inline `<style>` to `dashboard.css`.
- Not done: live browser pass (checklist last box).

## 2026-09-02 (SON ML rebuild)

- Done: Topology join no longer samples map lines. SQL aggregates Huawei `Local_cell_name`/`Target_Cell_Name` and Nokia `Source_LNCEL_name` + ECI→metadata `cell_name` (NetAct leaves Target LNCEL empty).
- Done: SON-only Huawei Cell Name keys (`prefer_cell_cols` on `_cell_daily_kpi_series`). Health still uses LocalCell Id. Huawei scores 27,547 cells (was ~124 numeric ids).
- Done: Loaded unused Nokia 4G export (`raw/nokia/neighbor/all/hourly/4G`, 2,354,489 rows) via `load_nokia_neighbor_raw_to_db.py --only-4g` (2G/3G untouched).
- Done: Graph isolation is 0 when no embedding neighbor (no fake 10.0). HO / recip / distance penalties still apply.
- Verified: Nokia 15,236/15,482 cells with neighbors, 5,417 graph≥55; Huawei 22,775/27,547 matched, 3,260 graph≥55. Tests 15/15 (`test_neighbor_graph.py` + `test_recommendations.py`).
- Not done: no browser click this session; treatment still heuristic (0 CM+PM pairs). No 2G/3G/5G ML. No closed-loop.


## 2026-09-02 (feature briefs)

- Done: Agent context briefs for every dashboard tile + shared platform (`docs/features/`). Not user manuals. Cursor rule `feature-briefs.mdc` loads them when those files are in play. Update History/Plans on the matching brief when a feature actually changes.

## 2026-08-31 (Postgres phases 2–4 plumbing)

- Done: Opt-in domain routing — `NCM_DATABASE_URL` + `NCM_PG_DOMAINS=app,metadata,neighbors,groups,balance,pm`. Unset = SQLite as today. `NCM_APP_DATABASE_URL` alone still means **app only**.
- Done: Separate Postgres schemas so Nokia/Huawei hourly table names can collide (`pm_nokia_hourly` vs `pm_huawei_hourly`). SQLite ATTACH aliases become schema-qualified `alias."table"`.
- Done: `db.runtime.open_db` / `store_available` used by Performance, ingest, neighbors, groups, SON PM helpers, pipeline loader. Femto / SON ML / KPI headers stay SQLite.
- Done: `python scripts/migrate_sqlite_domain_to_postgres.py --schema metadata` and `python scripts/migrate_all_sqlite_to_postgres.py` (chunked copy; does not delete SQLite files).
- Verified: adapter tests 16/16; `init_db` still SQLite; no Postgres URL set on this laptop.
- Not done: no live Postgres here — do not set the URL until the server has Postgres and migrate has been run. PM ingest on Postgres is not load-tested (14 GB).

## 2026-08-31 (Postgres phase 0–1)

- Done: Phase 0 inventory — `python scripts/inventory_sqlite_databases.py`. App DB `ncm_users.db` is 548 KB / 22 tables / 3879 rows (57 users). PM+femto are multi-GB; stay SQLite. ATTACH in `performance_meta_pm_conn` blocks PM Postgres.
- Done: Phase 1 opt-in — `NCM_APP_DATABASE_URL=postgresql://…` switches **only** `connect_app()` (users/sessions + other ncm_users tables). Unset = SQLite as today. Adapter tests 6/6. `init_db` still works on SQLite (57 users).
- Done: `scripts/migrate_ncm_users_to_postgres.py` copies SQLite → schema `app`. Optional Compose profile `app-db` for a local Postgres (not started by default).
- Not done: no live Postgres on this laptop; do not set the URL until the server has Postgres and the migrate script has been run.

## 2026-08-31 (platform hygiene)

**NEXT:** Rebuild SON ML so Topology can use the raised neighbor-line cap (`NEIGHBOR_MAX_LINES=100000`). Then click through `/son-analytics` in a browser (no browser MCP this session; APIs were verified via Flask test client).

## 2026-08-31 (platform hygiene)

- Done: Custom HTML 404 (`templates/404.html`, NexusCore constellation) + JSON `{"error":"Not found"}` for `/api/*`. Flask test client: HTML 404, API 404.
- Done: Public `/robots.txt` (`User-agent: *` / `Disallow: /`). `X-Robots-Tag: noindex, nofollow` on all responses.
- Done: Neighbor Relations Analyzer Excel export — `/api/network-map/neighbors/export` + **Export Excel** on `/neighbor-analysis`. Same filters as map lines. Workbook builder verified (`PK` xlsx). Live neighbor DB returned 0 lines in this session (export would 400 until a cell is drawn).
- **NEXT:** SON ML rebuild (above). Postgres cutover is opt-in on the server (`NCM_DATABASE_URL`); this laptop stays SQLite.

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
