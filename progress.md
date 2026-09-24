# PrimeNet — progress log

Dated log of verified work. Mark items done only after end-to-end verification.

**Current track:** Configuration Dashboard V1.0 (Hardware + WNCELG shared ingest).

**Parked:** SON trust click-through. Huawei 4G identity in shared `pm_helpers` still prefers `LocalCell Id`. PM Plus continuous worker on server (`NCM_ENABLE_ETL=1`). Local ETL kill switch remains `NCM_ENABLE_ETL=0` on laptop. RET hologram ground reach from performance/TA (needs per-cell PM pipeline + RET↔cell map) — for now geometric h/tan(tilt) clamped 100–1000 m. Pattern detail is cosmetic side lobes/nulls — upgrade to analytic/real patterns if the look is wrong.

**NEXT:** Open `/adjacency-gis` — Map view switcher + BCCH highlighter smoke.

## 2026-09-24 (Adjacency GIS — basemap switcher)

- Left-panel Map view (Roadmap default; Street / Satellite / etc.).

## 2026-09-24 (Adjacency GIS — BCCH highlighter)

- Co-channel + ±1 adjacent BCCH overlay on 2G metadata map; Roadmap default.

## 2026-09-23 (Sector Health All Cells — layer activity)

- All Cells Excel marks each tech/band Active vs Inactive (same metadata activity rules as the map).
- Vendor labels: Huawei / Nokia Thin, Huawei TDD / Nokia Thin, Huawei TDD / Nokia.

## 2026-09-23 (Adjacency GIS — Network Map fork)

- Replaced weird custom map with Network Map copy, 2G-only from `metadata.db`.

## 2026-09-23 (Platform Admin entry)

- Platform Admin only from NexusCore portals topbar; removed from PrimeNet dashboard / Eng Admin and stopped common.js per-module Admin inject.

## 2026-09-23 (Reverse proxy + Platform Admin)

- Docker nginx proxy (one public port, hostname routing); users/module access on NexusCore `/admin`; PrimeNet Admin ops-only.

## 2026-09-20 (Dark mode — cascade safety net)

- Root cause: module CSS after `common.css` beat non-`!important` dark rules; blanket `span` color flattened chips/fonts.
- Done: `theme-dark-final.css` injected last by `common.js`; button `!important`; span flatten removed; dark blocks on 8 modules that had none; `scripts/audit_dark_mode.py` + cascade simulate.

## 2026-09-20 (Central SSO + portal allow-list)

- One NexusCore login; shared `nexus_session`; Admin portal checkboxes on `ncm_users.db`.

## 2026-09-20 (Adjacency GIS — Huawei CM)

- Huawei GTRX/G2GNCELL ingest + per-vendor snapshots; scheduled 04:45; Admin Nokia/Huawei/both buttons.

## 2026-09-20 (Configuration Dashboard — Hardware + WNCELG)

- Done: New `/configuration-dashboard` (replaces RRU tile); shared daily RMOD_R + WNCELG ingest; WNCELG Sankey Area → Split/No-split → group count.

## 2026-09-20 (Adjacency GIS — Nokia Phase 1)

- New module `/adjacency-gis`: 2G NCL GIS (BTS/TRX BCCH + ADCE), scheduled snapshot, map audits (uni/bi, overshoot, NCL>32, co-channel).

## 2026-09-17 (RMOD list-param fix)

- Root cause: NetAct rejects `@active*CellsList` (scalar required) — StructuredValue/list.
- Done: Ingest lists DNs via `dn()` / queryMOLites, then `getManagedObjects` for full params incl. cell lists.
- Tests: managed-object list emptiness + tech mapping.

## 2026-09-17 (Radio Hardware Inventory — daily snapshot)

- Done: SQLite snapshot store; scheduler cron **04:00**; Admin manual run (`/api/admin/rru-inventory/run`).
- Done: Module UI reads snapshot (not live); Excel download; status pill for last build.
- Tests: `test_logic` + `test_store` — 9 passed.

## 2026-09-17 (Radio Hardware Inventory Report — RMOD_R)

- Done: New module `/rru-inventory` (display name **Radio Hardware Inventory Report**) — live Nokia `RMOD_R`, Area → Tech → `productName` Sankey (D3 vendored).
- Tech from `activeGsm/Wcdma/Lte/NrCellsList`; unused (all empty) filterable in UI; multi-RAT fans out per tech.
- Wired: `primenet_app`, `module_access`, `module_versions`, dashboard card, feature brief.
- Tests: `modules/rru_inventory/test_logic.py` — 7 passed. Live NetAct not configured on laptop.

## 2026-09-17 (Hologram coverage realism)

- Done: Lobe length from RET downtilt (° below horizon) × band tier (2G/L900 > L1800/L1800+ > L2100/3G).
- Done: AAU Left/Right → 30° HPBW half-beams at ±15° from sector azimuth.
- Done: Rectangular site cabin + headframe + panels; N/S/E/W compass; canvas ~+50%.
- Load RET / table edits rebuild hologram from degrees.

## 2026-09-17 (CM Extract — East Amman neighbor + admin logging)

- Root cause: East Amman Huawei 4G ≈220 eNodeBs; `CELL` is fine area-wide, but `EUTRANINTERFREQNCELL` is high-cardinality and overwhelms U2020 MML / timeouts.
- Done: Refuse neighbor/relation MOs above 40 NEs with a clear error; smaller MML chunks (10) for those MOs; dictionary MO technology for LTE NE filtering.
- Done: CM extract activity logging (`cm_extract_start` / success / fail / async / download) + Admin User Admin panel + Activity Log action filter.
- Tests: `core/cm_extractor/test_huawei_controller_scope.py` extended.

## 2026-09-17 (RET label truth table)

- Done: `infer_ret_tech_from_label` is the only RET→tech mapper (Nokia `sectorID` / Huawei `Subunit Name`).
- Mapping: 2G; 3G; 4G/4G2→4G; LTE+TDD→4G-TDD; AAU+Left/Right→4G-AAU-*; Capacity→4G-L1800+; F#→3G; Band→4G; Letter+digit layers 1→4G/2→2G/3→3G/4→4G-L1800+; NA→Not Used.
- Hologram `TECH_COLORS` / `TECH_ORDER` updated for the new keys (metadata 4G-FDD/5G kept as fallback).
- Tests: 43 passed in ret_management logic/site_layout.

## 2026-09-17 (RET hologram — per-tech toggles + mesh lobes)

- Done: `_ret_tech` from Huawei `Subunit Name` / Nokia `sectorID`.
- Done: One hologram lobe per sector×tech; rail toggles All/None/per-tech.
- Done: Wireframe mesh envelope (reference-style) instead of smooth filled surface.
- Tests: ret_management logic/site_layout.

## 2026-09-16 (RET Management smoke — Nokia 1003 / Huawei 1020)

- Done: Restarted PrimeNet on :8001 with new templates; `scripts/_smoke_ret_management.py` green.
- UI: page + `three.min.js` + hologram assets OK; pitch default 30°.
- Nokia site `51003`/`1003`: layout 3 lobes @ 50/150/340; 18 RETU rows → 12 mapped (A/B/C forms), 6 unmapped empty `sectorID`, 0 orphans.
- Huawei site `1020`: layout 3 lobes @ 60/190/320; 12/12 RETSUBUNIT mapped from `1020_{A|B|C}-…`.
- Fix: unreadable personal vendor ciphertext now falls back to shared CM account (was hard 400).

## 2026-09-16 (RET Management — sector join + 3D hologram)

- Done: Huawei sector from `Subunit Name` form `{SiteId}_{Sector}-…` only (no Actual Sector ID / subunit fallbacks).
- Done: Nokia sector from `sectorID` forms `D4-L1800` / `F1_F2-A1-3G-…`; site from `baseStationID`.
- Done: `normalize_sector_key` treats metadata `1003_A` as sector A→1 (was collapsing whole site).
- Done: Hologram prefers metadata azimuth; three.js 3D mast + cos^n lobes (60° HPBW), default 30° camera tilt; `three.min.js` vendored.
- Tests: `modules/ret_management/test_logic.py` + `test_site_layout.py` — 41 passed.

## 2026-09-14 (Cases uplift Phases 1–4)

- Done: Real post-KPI scorecard (schema v2) + verdict on `execution_ref`.
- Done: `core/cases/identity.py` lite for correlator/scorecard joins only.
- Done: Morning Report `from-morning-report` API + bulk button; 7d `source_issue_id` dedupe.
- Done: Same-cell case history (30d) in Case detail.
- Done: Phase 2 packs — PM deeplink, neighbor/overshoot facts, complaint intake, cluster checklist.
- Done: Phase 3 — Impact Score (PM), conflict + golden gates, energy Cases, trusted treatments (+ SON prefer).
- Done: Phase 4 — selection consume in Performance/Plus; NL→chips (no SQL); digest script.
- Tests: expand `core.cases.test_cases` (scorecard post, identity, morning dedupe, conflict, impact/treatments, NL).

## 2026-09-14 (PM Plus Admin Rules + sample ingest)

- Done: Agg Rules live on Admin → **PM Plus Rules** (`/admin-panel?section=pm-plus-rules`); removed from Explorer Plus. Smoke `scripts/_smoke_pm_plus_admin.py` — page 200, families/counters APIs OK, old PEP rules API 404.
- Done: Re-imported Nokia catalog (453 families / ~32k counters / 2831 KPIs).
- Done: Local hour sample ingest `run_hour_ingest.py --buckets 2 --max-files 30` — 30/30 ok, ~3.87M fact_15m / ~3.82M fact_hour; SFTP host 10.119.219.24 reachable (~75s discover). Day rollup not run this pass.
- Fixed: `core/cases/__init__.py` import mismatch (`open_complaint_case`) that briefly broke `app` import.

## 2026-09-16 (NexPulse Phase 2 — network targeting bridge)

- Done: PrimeNet `modules/portal_api` — Bearer-token endpoints for technology footprint, congested sites (Capacity Hotspots), serviceability (layer coverage).
- Done: NexPulse `providers_primenet.PrimeNetNetworkFootprint` registered when `NEXUS_PRIMENET_API_URL` + `NEXUS_PORTAL_API_TOKEN` are set (`python app.py` wires local defaults).
- Done: Campaign readiness blocks approval when the audience uses network attributes but the API is offline; capacity pressure is advisory (soft gate at 25 congested sites).
- Done: Campaign detail network panel + overview provider status when connected.
- Tests: `portals/marketing/test_network_bridge.py`.
- **NEXT:** Phase 2 remaining — campaign performance/holdout reporting, creative library, promo/quota engine.

## 2026-09-16 (Suite launcher + shared activation for testing)

- Done: `python app.py` starts NexusCore (8000) + PrimeNet (8001) + NexPulse (8002).
- Done: Shared activation gate for testing — unlock once at PrimeNet `/activation`; NexusCore/NexPulse redirect there until unlocked. Per-platform activation later (`NCM_SHARED_ACTIVATION=0`).

## 2026-09-16 (Separate platform processes)

- Done: Three entry apps — `nexuscore_app.py` (lobby), `primenet_app.py` (engineering), `nexpulse_app.py` (marketing).
- Done: Per-platform users DB + cookies (`nxc_session`, `primenet_session`, `nexpulse_session`); no SSO handoff.
- Done: `core/platform/` base factory + parameterized identity; marketing `access.py` no longer imports `database_enhanced`.
- Done: Docker Compose services `nexuscore` / `primenet` / `nexpulse`; `app.py` shim → PrimeNet.
- Tests: `core/platform/test_platform.py`; marketing architecture test updated.

## 2026-09-16 (NexPulse — Marketing Portal)

- Done: `portals/` — NexusCore portals live outside `modules/`, as separate applications. `portals/marketing/` (NexPulse) owns its own SQLite store (`NEXUS_MARKETING_DB`, default `data/portals/marketing/marketing.db`), templates, static, and access rules; mounted with `create_marketing_portal(app)` in `app.py`. Splitting it into its own service = calling the same factory against a standalone Flask app
- Done: Phase 1 spine — Offer catalog (draft→in_review→approved→live→retired), Campaigns (8-state lifecycle + readiness gate), Segment builder (15 attributes, 11 operators, validated rule expressions), Consent / suppression / contact policy, plus calendar, audit trail, contactability lookup. 31 routes
- Done: Portal-local RBAC (5 roles, 13 permissions). Identity still comes from PrimeNet's login, isolated to `portals/marketing/access.py` — the only file that imports `database_enhanced`, per vision rule 2
- Done: Provider seam (`providers.py`) — `SegmentSizeProvider`, `CampaignMetricsProvider`, `NetworkFootprintProvider`. All null-backed; screens render explicit "not connected" states. No fixtures, no invented numbers. Real ingestion is a `providers.register()` swap
- Done: MSISDN canonicalisation via `NEXUS_MARKETING_MSISDN_CC` — without it `0791234567` and `962791234567` are two subscribers and a DNC entry on one will not stop a send to the other. Unset is allowed but flagged in the UI
- Done: Campaign readiness gate blocks approval without audience, channels, offers, schedule, and an active contact policy; holdout/templates/budget are advisory
- Done: `portals/marketing/test_marketing.py` — 25 tests (lifecycles, rule validation, consent precedence, MSISDN matching, RBAC layering, audit, architecture isolation). `python -m pytest portals/marketing/test_marketing.py` — 25/25. Full suite 172 passed (2 pre-existing collection errors in `scripts/test_personal_vendor_credentials.py`, a manual CLI script)
- Done: Portal tower — Marketing now Active and routed to the portal; product names NexPulse / NexArpu / NexResolve on the cards
- Modified: `app.py`, `routes/auth_routes.py`, `templates/portal_select.html`, `templates/portal_coming_soon.html`, `docs/NEXUSCORE_VISION.md`, new `portals/`
- **NEXT:** Phase 2 for NexPulse — campaign performance + holdout/uplift reporting, creative asset library, promo/quota engine, and the network-aware targeting bridge (coverage, serviceability, capacity gating) over a PrimeNet API

## 2026-09-14 (Optimization Cases A–C)

- Done: `core/cases/` — schema/store/state machine, deterministic correlator, scorecard v1, per-user selection context.
- Done: Module `/optimization-cases` workspace + APIs; dashboard tile; admin nav.
- Done: Radio modules **Open Optimization Case**; SON detail **Open Optimization Case**; Network Map polygon **Use as selection**.
- Done: Unit tests `core.cases.test_cases` (4/4); smoke script `scripts/_smoke_optimization_cases.py`.

## 2026-09-11 (ETL gate + local cleanup)

- Done: `core/etl_gate.py` — `NCM_ENABLE_ETL=0/1` master switch (loads `.env`); wired into bootstrap, scheduler, sync triggers, pipeline orchestrators/pull/load, PM Plus workers.
- Done: Local `.env` + `.env.example` set `NCM_ENABLE_ETL=0`; server scheduler entrypoint defaults to `1`.
- Done: `scripts/clear_local_etl_data.py` — wipes PM/raw/sync_downloads, keeps admin+metadata+geo.

## 2026-09-11 (Performance Explorer Plus)

- Done: `core/pm_plus/` — streaming TS 32.435 parser, ledger, ingest cycle, hour→day rollup, KPI compiler, query/export, VendorAdapter (Huawei stub).
- Done: Scripts `scripts/pm_plus/run_pilot.py`, `run_ingest_worker.py`, `run_rollup.py`.
- Done: Module `/performance-explorer-plus` (Explorer / KPI Builder / Ingest Health) + dashboard tile; old `/performance` unchanged.
- Done: Unit tests 7/7 (`core.pm_plus.test_pm_plus`); pilot sample ingest ~0.02s.
- Store: SQLite fallback `databases/pm_plus/pm_plus.db`; Postgres via `PM_PLUS_DATABASE_URL`.

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
