# NexusCore — Feature catalog (AI context)

Master map of every blueprint/portal under **NexusCore**. Root `progress.md` is a
**brief daily journal** (topics only). Dated detail lives in
`docs/features/<slug>.progress.md`; implementation context in `docs/features/<slug>.md`.
Platform vision: `docs/NEXUSCORE_VISION.md`.

**Agents:** Before changing a feature, read this entry, the linked brief, and the
`.progress.md` file, then `python -m graphify query "<feature>"`. After code changes:
append to `<slug>.progress.md`, update brief **Plans** if needed, add one topic bullet
to root `progress.md`.

## How NexusCore is structured

| Layer | What it is | Code home |
|---|---|---|
| **NexusCore** | Umbrella: login, portal tower, shared brand | `routes/auth_routes.py`, portal templates |
| **PrimeNet** | Engineering portal — RAN OSS (~40 blueprints) | `modules/<name>/` + `app.register_blueprint` |
| **NexPulse** | Marketing portal (reference second portal) | `portals/marketing/` via `create_marketing_portal(app)` |
| **NexArpu / NexResolve** | Sales / Support — Coming soon on the tower | Placeholders only |

Rule: new business domains are **portals**, not new PrimeNet dashboard tiles
(see vision §4). PrimeNet blueprints stay under `modules/`.

## Blueprint registration (PrimeNet)

Registered in `app.py` (plus `create_marketing_portal(app)`). Dashboard cards use
`data-module-id` = feature brief slug. Versions: `core/module_versions.py`. Nav/access:
`core/module_access.py` `NAV_SECTIONS` + `core/feature_access.py`.

---

## NexusCore portals

### NexPulse (Marketing) — Active

| | |
|---|---|
| Product | NexPulse |
| Route prefix | `/portals/marketing` |
| Code | `portals/marketing/` (not under `modules/`) |
| Store | `data/portals/marketing/marketing.db` (`NEXUS_MARKETING_DB`) |
| Brief | [`docs/features/nexpulse.md`](features/nexpulse.md) |

**User sees:** Portal tower → Marketing level → NexPulse home with Offer catalog, Campaigns,
Segments, Consent/suppression/contact policy, calendar, audit, contactability lookup. Screens show explicit "not connected" when providers have no data (no fake numbers).

**What it does:** Phase 1 marketing spine — lifecycled offers/campaigns, segment rule builder,
consent/DNC with MSISDN canonicalisation (`NEXUS_MARKETING_MSISDN_CC`), portal-local RBAC
(5 roles / 13 permissions), provider seam for future CRM/network feeds.

**Progress:** [`features/nexpulse.progress.md`](features/nexpulse.progress.md)


**Plan (NEXT):** Phase 2 remaining — campaign performance + holdout/uplift reporting,
creative asset library, promo/quota engine. (Network-aware targeting bridge: done.)

### NexArpu (Sales) / NexResolve (Support) — Coming soon

**User sees:** Tower cards with product names; enter shows Coming soon.

**Plan:** Support next (tickets from PrimeNet fault/health APIs), then Sales (reads NexPulse
offer catalog). See `docs/NEXUSCORE_VISION.md` §5.

---

## Platform shell

### Auth, sessions, activation

| | |
|---|---|
| Slug | `auth-activation` |
| Route | _(see brief)_ |
| Access | `core/module_access.py`, `core/feature_access.py` |
| Version | — |
| Brief | [`features/auth-activation.md`](features/auth-activation.md) |
| Progress | [`features/auth-activation.progress.md`](features/auth-activation.progress.md) |

**User sees:** NexusCore login, activation gate if unlicensed, portal tower, then Engineering dashboard or other portal.

**What it does:** Monthly operator activation lock, login/session, password rotation, CSRF origin check, per-role feature grants.

**Progress:** [`features/auth-activation.progress.md`](features/auth-activation.progress.md)


**Plan:** None. Do not weaken activation for convenience on a laptop that will be copied to the server.

### Dashboard

| | |
|---|---|
| Slug | `dashboard` |
| Route | `/dashboard` — `templates/dashboard.html` |
| Access | all authenticated |
| Version | — |
| Brief | [`features/dashboard.md`](features/dashboard.md) |
| Progress | [`features/dashboard.progress.md`](features/dashboard.progress.md) |

**User sees:** After login and Engineering portal entry, the constellation tile deck is home. User picks a module card (version chip shown); cards respect role/feature_access.

**What it does:** Tile deck for every tool. Cards use `data-module-id` (that id is the feature-brief slug). Version labels come from `MODULE_VERSIONS`.

**Progress:** [`features/dashboard.progress.md`](features/dashboard.progress.md)


**Plan:** UI unification in `checklist.md` mostly checked (2026-09-06). Remaining: browser verify light/dark on dashboard + one radio + one standalone + login.

### Postgres runtime (opt-in)

| | |
|---|---|
| Slug | `postgres-runtime` |
| Route | _(see brief)_ |
| Access | — |
| Version | — |
| Brief | [`features/postgres-runtime.md`](features/postgres-runtime.md) |
| Progress | [`features/postgres-runtime.progress.md`](features/postgres-runtime.progress.md) |

**User sees:** Invisible to end users — DB routing SQLite vs Postgres for domains; agents must use db/runtime helpers.

**What it does:** Optional cutover of canonical SQLite files to one Postgres server, per domain, for backup/HA. Nokia and Huawei hourly tables share names (`"4G_Hourly"`) so each file is its own schema (`pm_nokia_hourly`, `pm_huawei_hour…

**Progress:** [`features/postgres-runtime.progress.md`](features/postgres-runtime.progress.md)


**Plan:** Cut over on the **server** after migrate. PM ingest on PG is not load-tested (~14 GB). Dashboard constellation pulse still uses SQLite `rowid` — will go quiet on PG until rewritten (visual only).

### Sync / pipeline (ETL)

| | |
|---|---|
| Slug | `sync` |
| Route | _(see brief)_ |
| Access | authenticated (ops); scheduler is a separate process |
| Version | — |
| Brief | [`features/sync.md`](features/sync.md) |
| Progress | [`features/sync.progress.md`](features/sync.progress.md) |

**User sees:** Admin triggers/monitors Data Sync and ETL pipelines (gated by NCM_ENABLE_ETL); not a casual dashboard tile for all roles.

**What it does:** SFTP pull of Nokia/Huawei PM, metadata, groups, neighbors; load into canonical DBs; retention; Network Health / SON jobs after load.

**Progress:** [`features/sync.progress.md`](features/sync.progress.md)


**Plan:** Do not run a 14 GB Postgres migrate from this laptop. SON ML job is after NH precalc (`scripts/pipeline/run_son_ml_job.py`); `SON_DISABLE_ML=1` kill switch.

### Radio API

| | |
|---|---|
| Slug | `radio-api` |
| Route | `/api/radio/areas` |
| Access | authenticated (same as radio modules) |
| Version | — |
| Brief | [`features/radio-api.md`](features/radio-api.md) |
| Progress | [`features/radio-api.progress.md`](features/radio-api.progress.md) |

**User sees:** Thin HTTP wrappers over core/radio for shared radio APIs consumed by modules.

**What it does:** Populate area dropdowns. Not a dashboard card.

**Progress:** [`features/radio-api.progress.md`](features/radio-api.progress.md)


**Plan:** None. Do not grow this into a second radio engine.

### Elevation

| | |
|---|---|
| Slug | `elevation` |
| Route | `/elevation` (API-style module) |
| Access | all |
| Version | — |
| Brief | [`features/elevation.md`](features/elevation.md) |
| Progress | [`features/elevation.progress.md`](features/elevation.progress.md) |

**User sees:** Helper used by map/coverage views for terrain elevation lookups (not a primary dashboard narrative).

**What it does:** Height samples for radio geometry. Not a dashboard constellation tile.

**Progress:** [`features/elevation.progress.md`](features/elevation.progress.md)


**Plan:** None parked. Do not pull a new global DEM without asking.

## Overview & Performance

### Performance Explorer

| | |
|---|---|
| Slug | `performance` |
| Route | `/performance` |
| Access | all |
| Version | V1.0 |
| Brief | [`features/performance.md`](features/performance.md) |
| Progress | [`features/performance.progress.md`](features/performance.progress.md) |

**User sees:** Engineer opens Performance Explorer from the dashboard, picks vendor/RAT/time and KPI columns from pre-baked Excel PM tables, charts/exports cell KPIs.

**What it does:** Cell/site/group KPI trends and tables, Nokia + Huawei, 2G–5G, hourly/daily, CSV export. Column lists are discovered from live tables, not a fixed schema.

**Progress:** [`features/performance.progress.md`](features/performance.progress.md)


**Plan:** None specific. KPI “ref” links into Performance Dictionary already exist.

### Performance Explorer Plus

| | |
|---|---|
| Slug | `performance-explorer-plus` |
| Route | `/performance-explorer-plus` |
| Access | all (authenticated) |
| Version | V1.0 |
| Brief | [`features/performance-explorer-plus.md`](features/performance-explorer-plus.md) |
| Progress | [`features/performance-explorer-plus.progress.md`](features/performance-explorer-plus.progress.md) |

**User sees:** Engineer uses Explorer / KPI Builder / Ingest Health tabs to query Nokia raw-counter warehouse KPIs (ratio-of-sums), separate from classic Performance Explorer. Agg rules live under Admin → PM Plus Rules.

**What it does:** Ingest Nokia NBI 15‑minute `.gz` (TS 32.435) into a warehouse, roll up to hour/day, and let engineers build ratio-of-sums KPIs with completeness — separate from Excel-KPI `/performance`.

**Progress:** [`features/performance-explorer-plus.progress.md`](features/performance-explorer-plus.progress.md)


**Plan:** Tune live SFTP workers against &lt;15 min lag SLO on production hosts. Enable Huawei adapter when SFTP paths exist.

### Huawei PM Query Studio

| | |
|---|---|
| Slug | `performance-analytics` |
| Route | `/performance-analytics` |
| Access | admin |
| Version | V1.0 |
| Brief | [`features/performance-analytics.md`](features/performance-analytics.md) |
| Progress | [`features/performance-analytics.progress.md`](features/performance-analytics.progress.md) |

**User sees:** Admin queries live Huawei MAE/U2020 PM via Query Studio (not the SQLite Excel warehouse).

**What it does:** Studio UI for Huawei PM tables beyond the main Explorer presets.

**Progress:** [`features/performance-analytics.progress.md`](features/performance-analytics.progress.md)


**Plan:** None parked.

### Network Coverage Heatmap

| | |
|---|---|
| Slug | `cell-heatmap` |
| Route | `/cell-heatmap` |
| Access | all |
| Version | V1.0 |
| Brief | [`features/cell-heatmap.md`](features/cell-heatmap.md) |
| Progress | [`features/cell-heatmap.progress.md`](features/cell-heatmap.progress.md) |

**User sees:** User picks vendor/RAT/KPI/time and sees a geographic heatmap of cell points colored by that KPI.

**What it does:** Map points colored by a selected KPI for the current vendor/RAT/time.

**Progress:** [`features/cell-heatmap.progress.md`](features/cell-heatmap.progress.md)


**Plan:** None parked.

### Network Map

| | |
|---|---|
| Slug | `network-map` |
| Route | `/network-map` |
| Access | all |
| Version | V1.0 |
| Brief | [`features/network-map.md`](features/network-map.md) |
| Progress | [`features/network-map.progress.md`](features/network-map.progress.md) |

**User sees:** User browses sites/cells on an interactive map, draws polygons, can push selection into Optimization Cases.

**What it does:** Geographic network picture from `metadata.db` (sites/cells) plus optional PM overlays and repeaters.

**Progress:** [`features/network-map.progress.md`](features/network-map.progress.md)


**Plan:** None parked for the map itself.

### Neighbor Analysis

| | |
|---|---|
| Slug | `neighbor-analysis` |
| Route | `/neighbor-analysis` |
| Access | all |
| Version | V1.0 |
| Brief | [`features/neighbor-analysis.md`](features/neighbor-analysis.md) |
| Progress | [`features/neighbor-analysis.progress.md`](features/neighbor-analysis.progress.md) |

**User sees:** User inspects neighbor relations / analysis views for selected cells (dashboard neighbor tool).

**What it does:** Draw neighbor lines for a drawn cell/site scope. Export the same filtered rows to Excel.

**Progress:** [`features/neighbor-analysis.progress.md`](features/neighbor-analysis.progress.md)


**Plan:** Live DB often returns 0 lines until a cell is drawn — that is expected. SON Topology needs a **ML rebuild** after `NEIGHBOR_MAX_LINES=100000` (that cap is in the quality/SON path, not this Excel button).

### Performance Reports

| | |
|---|---|
| Slug | `reports` |
| Route | `/reports` |
| Access | all |
| Version | V1.1 |
| Brief | [`features/reports.md`](features/reports.md) |
| Progress | [`features/reports.progress.md`](features/reports.progress.md) |

**User sees:** User generates or downloads packaged performance reports from the reports UI.

**What it does:** Build downloadable performance reports from metadata + PM; archive rows live in the app DB (`performance_reports`).

**Progress:** [`features/reports.progress.md`](features/reports.progress.md)


**Plan:** None parked.

### Power BI Reports

| | |
|---|---|
| Slug | `power-bi` |
| Route | `/power-bi` |
| Access | all |
| Version | V1.0 |
| Brief | [`features/power-bi.md`](features/power-bi.md) |
| Progress | [`features/power-bi.progress.md`](features/power-bi.progress.md) |

**User sees:** User opens embedded/gallery Power BI reports configured for the operator.

**What it does:** Catalog of report URLs. Does not proxy Power BI tokens today.

**Progress:** [`features/power-bi.progress.md`](features/power-bi.progress.md)


**Plan:** None. Do not fake an embed.

### Sector Health

| | |
|---|---|
| Slug | `sector-health` |
| Route | _(see brief)_ |
| Access | all |
| Version | V1.3 |
| Brief | [`features/sector-health.md`](features/sector-health.md) |
| Progress | [`features/sector-health.progress.md`](features/sector-health.progress.md) |

**User sees:** User monitors sector-level health scores and drill-downs for watched sectors.

**What it does:** Monitored sectors vs all configured cells. Coverage = metadata (active vs all), not Sleeping Cells PM.

**Progress:** [`features/sector-health.progress.md`](features/sector-health.progress.md)


**Plan:** None parked.

### Conflict Map

| | |
|---|---|
| Slug | `conflict-map` |
| Route | `/conflict-map` |
| Access | all |
| Version | V1.0 |
| Brief | [`features/conflict-map.md`](features/conflict-map.md) |
| Progress | [`features/conflict-map.progress.md`](features/conflict-map.progress.md) |

**User sees:** User sees map/list of identifier collisions (duplicate/conflicting cell or site IDs) from metadata.

**What it does:** Detect identifier collisions from metadata (and related CM fields).

**Progress:** [`features/conflict-map.progress.md`](features/conflict-map.progress.md)


**Plan:** None parked.

### Adjacency GIS

| | |
|---|---|
| Slug | `adjacency-gis` |
| Route | `/adjacency-gis` |
| Access | all |
| Version | V1.1 |
| Brief | [`features/adjacency-gis.md`](features/adjacency-gis.md) |
| Progress | [`features/adjacency-gis.progress.md`](features/adjacency-gis.progress.md) |

**User sees:** 2G sector wedges and configured adjacency lines (Nokia ADCE / Huawei G2GNCELL) with uni/bi, overshoot, NCL>32, co-channel coloring.

**What it does:** Scheduled per-vendor CM snapshots joined to `cells_2g` geometry for NCL GIS audit (separate from Neighbor Analysis HO lines).

**Progress:** [`features/adjacency-gis.progress.md`](features/adjacency-gis.progress.md)


**Plan:** None parked.

### Femto PM

| | |
|---|---|
| Slug | `femto-pm` |
| Route | `/femto-pm` |
| Access | all |
| Version | V1.0 |
| Brief | [`features/femto-pm.md`](features/femto-pm.md) |
| Progress | [`features/femto-pm.progress.md`](features/femto-pm.progress.md) |

**User sees:** User explores femtocell PM KPIs and custom KPI definitions in the Femto PM mini-app.

**What it does:** KPIs for femto/home cells. Separate DBs under `databases/cells/` (`femto_pm_cells.db`, `femto_user_kpis.db`).

**Progress:** [`features/femto-pm.progress.md`](features/femto-pm.progress.md)


**Plan:** Stay SQLite.

### Fault Management

| | |
|---|---|
| Slug | `fault-management` |
| Route | `/fault-management` |
| Access | all |
| Version | V1.0 |
| Brief | [`features/fault-management.md`](features/fault-management.md) |
| Progress | [`features/fault-management.progress.md`](features/fault-management.progress.md) |

**User sees:** User browses raw alarm/fault lists by vendor; pair with Alarm–PM Correlator for KPI join.

**What it does:** Show recent OSS/FM alarms. Alarm–PM correlation is a different tile (`/alarm-impact`).

**Progress:** [`features/fault-management.progress.md`](features/fault-management.progress.md)


**Plan:** None parked.

## Radio Optimization

### SON Optimization Insights

| | |
|---|---|
| Slug | `son-analytics` |
| Route | `/son-analytics` |
| Access | admin |
| Version | V1.1 |
| Brief | [`features/son-analytics.md`](features/son-analytics.md) |
| Progress | [`features/son-analytics.progress.md`](features/son-analytics.progress.md) |

**User sees:** Admin opens SON Insights for WoW clusters, ML anomaly/topology scores, and recommendations; can open an Optimization Case from a detail. Read-only — no OSS write.

**What it does:** WoW clusters + optional ML scores (PCA/IF, neighbor-graph topology, spatial DBSCAN). Flask never imports torch.

**Progress:** [`features/son-analytics.progress.md`](features/son-analytics.progress.md)


**Plan:** **NEXT:** browser-click `/son-analytics`. No 2G/3G/5G ML. No closed-loop.

### Optimization Cases

| | |
|---|---|
| Slug | `optimization-cases` |
| Route | `/optimization-cases` |
| Access | admin |
| Version | V1.1 |
| Brief | [`features/optimization-cases.md`](features/optimization-cases.md) |
| Progress | [`features/optimization-cases.progress.md`](features/optimization-cases.progress.md) |

**User sees:** Admin works a case queue: evidence → proposed change → approval gates → execution_ref → before/after scorecard. Bulk intake from Morning Report; map/radio modules can open cases.

**What it does:** Turn detector/SON issues into owned cases with correlated PM/CM/FM evidence, narrative, proposed change, execution ref, and before/after scorecard. Shared selection context syncs map polygons / pasted cell lists into ca…

**Progress:** [`features/optimization-cases.progress.md`](features/optimization-cases.progress.md)


**Plan:** - Harden golden-rule parse against structured proposed_change JSON. - Expand neighbor/overshoot packs when live HO distance fields are richer. - Optional AI narrative over verified facts only.

### Network Health Overview

| | |
|---|---|
| Slug | `network-health` |
| Route | `/network-health` |
| Access | admin |
| Version | V1.1 |
| Brief | [`features/network-health.md`](features/network-health.md) |
| Progress | [`features/network-health.progress.md`](features/network-health.progress.md) |

**User sees:** Admin views the precomputed category scorecard (retainability, accessibility, mobility, interference, utilization) vs operator thresholds.

**What it does:** Category scorecard (retainability, accessibility, mobility, interference, utilization) vs operator `threshold_bad`. Nightly precalc store; page reads it.

**Progress:** [`features/network-health.progress.md`](features/network-health.progress.md)


**Plan:** Scheduler already runs precalc before SON ML. Do not compute the full scorecard synchronously in the request.

### RF Optimization Workbench

| | |
|---|---|
| Slug | `rf-optimization` |
| Route | `/rf-optimization` |
| Access | admin |
| Version | V1.0 |
| Brief | [`features/rf-optimization.md`](features/rf-optimization.md) |
| Progress | [`features/rf-optimization.progress.md`](features/rf-optimization.progress.md) |

**User sees:** Admin uses the RF workbench (radio_module shell) to triage RF optimization issues from shared detectors.

**What it does:** Workbench feed: several detectors composed, not a new data source.

**Progress:** [`features/rf-optimization.progress.md`](features/rf-optimization.progress.md)


**Plan:** None parked.

### Neighbor Quality Analyzer

| | |
|---|---|
| Slug | `neighbor-quality` |
| Route | `/neighbor-quality` |
| Access | admin |
| Version | V1.0 |
| Brief | [`features/neighbor-quality.md`](features/neighbor-quality.md) |
| Progress | [`features/neighbor-quality.progress.md`](features/neighbor-quality.progress.md) |

**User sees:** Admin reviews neighbor quality issue list (HO/distance/reciprocity style signals) and can open cases.

**What it does:** Score neighbor relations (HO, distance, azimuth, freshness) against operator targets.

**Progress:** [`features/neighbor-quality.progress.md`](features/neighbor-quality.progress.md)


**Plan:** Do not merge with `/neighbor-analysis`.

### Capacity Hotspots

| | |
|---|---|
| Slug | `capacity-hotspots` |
| Route | `/capacity-hotspots` |
| Access | admin |
| Version | V1.0 |
| Brief | [`features/capacity-hotspots.md`](features/capacity-hotspots.md) |
| Progress | [`features/capacity-hotspots.progress.md`](features/capacity-hotspots.progress.md) |

**User sees:** Admin sees ranked cells breaching utilization threshold_bad and can open cases.

**What it does:** Rank cells that breach utilization `threshold_bad` (default 80%).

**Progress:** [`features/capacity-hotspots.progress.md`](features/capacity-hotspots.progress.md)


**Plan:** None parked.

### Sleeping Cell Detector

| | |
|---|---|
| Slug | `sleeping-cells` |
| Route | `/sleeping-cells` |
| Access | admin |
| Version | V1.1 |
| Brief | [`features/sleeping-cells.md`](features/sleeping-cells.md) |
| Progress | [`features/sleeping-cells.progress.md`](features/sleeping-cells.progress.md) |

**User sees:** Admin sees cells that look asleep (traffic/zero activity patterns) on the shared radio issue list.

**What it does:** Silent outages: cell still configured Active, payload gone vs baseline. Optional live FM cross-check.

**Progress:** [`features/sleeping-cells.progress.md`](features/sleeping-cells.progress.md)


**Plan:** None parked.

### Layer Coverage Gaps

| | |
|---|---|
| Slug | `layer-coverage` |
| Route | `/layer-coverage` |
| Access | admin |
| Version | V1.0 |
| Brief | [`features/layer-coverage.md`](features/layer-coverage.md) |
| Progress | [`features/layer-coverage.progress.md`](features/layer-coverage.progress.md) |

**User sees:** Admin sees layer coverage gap issues on the shared radio issue list.

**What it does:** Sites missing an expected layer (e.g. no 4G where 3G exists). Metadata-driven.

**Progress:** [`features/layer-coverage.progress.md`](features/layer-coverage.progress.md)


**Plan:** None parked.

### Overshooting Detector

| | |
|---|---|
| Slug | `overshooting-detector` |
| Route | `/overshooting-detector` |
| Access | admin |
| Version | V1.0 |
| Brief | [`features/overshooting-detector.md`](features/overshooting-detector.md) |
| Progress | [`features/overshooting-detector.progress.md`](features/overshooting-detector.progress.md) |

**User sees:** Admin sees overshooting cell issues and can open cases with overshoot evidence packs.

**What it does:** Cells serving too far (HO SR / distance / elevation helpers).

**Progress:** [`features/overshooting-detector.progress.md`](features/overshooting-detector.progress.md)


**Plan:** None parked.

### Change Impact Tracker

| | |
|---|---|
| Slug | `change-impact` |
| Route | `/change-impact` |
| Access | admin |
| Version | V1.0 |
| Brief | [`features/change-impact.md`](features/change-impact.md) |
| Progress | [`features/change-impact.progress.md`](features/change-impact.progress.md) |

**User sees:** Admin correlates recent CM snapshot changes with PM degradation across RATs.

**What it does:** Correlate configuration snapshots with PM across RATs.

**Progress:** [`features/change-impact.progress.md`](features/change-impact.progress.md)


**Plan:** None parked.

### Radio Morning Report

| | |
|---|---|
| Slug | `radio-morning-report` |
| Route | `/radio-morning-report` |
| Access | admin |
| Version | V1.0 |
| Brief | [`features/radio-morning-report.md`](features/radio-morning-report.md) |
| Progress | [`features/radio-morning-report.progress.md`](features/radio-morning-report.progress.md) |

**User sees:** Admin runs/views the morning issue digest and can bulk-create Optimization Cases.

**What it does:** Compose capacity / neighbor / overshooting / sleeping / … into one briefing list.

**Progress:** [`features/radio-morning-report.progress.md`](features/radio-morning-report.progress.md)


**Plan:** None parked.

### Nokia Load Balancing

| | |
|---|---|
| Slug | `nokia-load-balancing` |
| Route | `/nokia-load-balancing` (legacy `/amle-optimizer` redirects) |
| Access | admin |
| Version | V1.2 |
| Brief | [`features/nokia-load-balancing.md`](features/nokia-load-balancing.md) |
| Progress | [`features/nokia-load-balancing.progress.md`](features/nokia-load-balancing.progress.md) |

**User sees:** Admin reviews Nokia AMLEPR / load-balancing recommendations built on CM extractor data.

**What it does:** Admin AMLE workflow on Network Balance sector snapshots. Live CM extract `NOKLTE:AMLEPR` via CM Extractor client. Verify API: `/api/nokia-load-balancing/verify`.

**Progress:** [`features/nokia-load-balancing.progress.md`](features/nokia-load-balancing.progress.md)


**Plan:** Browser-verify with NetAct CM credentials was an older NEXT — only when Malek is on a host that can reach OSS.

### Huawei Load Balancing

| | |
|---|---|
| Slug | `huawei-load-balancing` |
| Route | `/huawei-load-balancing` |
| Access | admin |
| Version | V1.2 |
| Brief | [`features/huawei-load-balancing.md`](features/huawei-load-balancing.md) |
| Progress | [`features/huawei-load-balancing.progress.md`](features/huawei-load-balancing.progress.md) |

**User sees:** Admin reviews Huawei load-balancing recommendations (parallel to Nokia LB).

**What it does:** NOK Huawei sectors → CellMLB propose → Excel/MML. No U2020 push.

**Progress:** [`features/huawei-load-balancing.progress.md`](features/huawei-load-balancing.progress.md)


**Plan:** No OSS push. Course still says “stub” — ignore that.

### Mobility / HO Explorer

| | |
|---|---|
| Slug | `mobility-explorer` |
| Route | `/mobility-explorer` |
| Access | admin |
| Version | V1.0 |
| Brief | [`features/mobility-explorer.md`](features/mobility-explorer.md) |
| Progress | [`features/mobility-explorer.progress.md`](features/mobility-explorer.progress.md) |

**User sees:** Admin explores HO/mobility issues on the shared radio issue list.

**What it does:** Rank mobility problems from PM HO recipes.

**Progress:** [`features/mobility-explorer.progress.md`](features/mobility-explorer.progress.md)


**Plan:** None parked.

### Alarm–PM Correlator

| | |
|---|---|
| Slug | `alarm-impact` |
| Route | `/alarm-impact` |
| Access | admin |
| Version | V1.0 |
| Brief | [`features/alarm-impact.md`](features/alarm-impact.md) |
| Progress | [`features/alarm-impact.progress.md`](features/alarm-impact.progress.md) |

**User sees:** Admin sees poor-KPI cells that also have recent alarms (join of PM + FM).

**What it does:** Show which poor-KPI cells also have live/recent alarms.

**Progress:** [`features/alarm-impact.progress.md`](features/alarm-impact.progress.md)


**Plan:** None parked.

### Group / Cluster Health

| | |
|---|---|
| Slug | `group-health` |
| Route | `/group-health` |
| Access | admin |
| Version | V1.0 |
| Brief | [`features/group-health.md`](features/group-health.md) |
| Progress | [`features/group-health.progress.md`](features/group-health.progress.md) |

**User sees:** Admin reviews cluster/group health scores using groups DBs.

**What it does:** Scan vendor group DBs for degraded controller/group KPIs.

**Progress:** [`features/group-health.progress.md`](features/group-health.progress.md)


**Plan:** None parked.

### IRAT / Vendor Border

| | |
|---|---|
| Slug | `irat-border` |
| Route | `/irat-border` |
| Access | admin |
| Version | V1.0 |
| Brief | [`features/irat-border.md`](features/irat-border.md) |
| Progress | [`features/irat-border.progress.md`](features/irat-border.progress.md) |

**User sees:** Admin reviews IRAT / vendor-border mobility issue list.

**What it does:** Flag IRAT / inter-vendor mobility problems.

**Progress:** [`features/irat-border.progress.md`](features/irat-border.progress.md)


**Plan:** None parked.

## Configuration

### Parameter Dictionary

| | |
|---|---|
| Slug | `parameter-dictionary` |
| Route | `/parameter-dictionary` |
| Access | all |
| Version | V1.1 |
| Brief | [`features/parameter-dictionary.md`](features/parameter-dictionary.md) |
| Progress | [`features/parameter-dictionary.progress.md`](features/parameter-dictionary.progress.md) |

**User sees:** User searches Nokia/Huawei parameter definitions and knowledge notes.

**What it does:** Searchable MO/parameter docs. Huawei pages are runtime-served scrapes.

**Progress:** [`features/parameter-dictionary.progress.md`](features/parameter-dictionary.progress.md)


**Plan:** **Parked:** browser-verify XML parser / generator / perf dictionary / CM audit. Parameter Dictionary layout widened 2026-09-02 — still worth a click-through.

### Performance Dictionary

| | |
|---|---|
| Slug | `performance-dictionary` |
| Route | `/performance-dictionary` |
| Access | all |
| Version | V1.1 |
| Brief | [`features/performance-dictionary.md`](features/performance-dictionary.md) |
| Progress | [`features/performance-dictionary.progress.md`](features/performance-dictionary.progress.md) |

**User sees:** User searches PM counter/KPI dictionary definitions (Nokia catalog etc.).

**What it does:** Look up counter meanings. Explorer “ref” links land here.

**Progress:** [`features/performance-dictionary.progress.md`](features/performance-dictionary.progress.md)


**Plan:** **Parked:** browser-verify.

### Configuration Data Extractor

| | |
|---|---|
| Slug | `cm-extractor` |
| Route | `/cm-extractor` |
| Access | all (write/reimport still gated in-module) |
| Version | V1.1 |
| Brief | [`features/cm-extractor.md`](features/cm-extractor.md) |
| Progress | [`features/cm-extractor.progress.md`](features/cm-extractor.progress.md) |

**User sees:** User discovers NEs, extracts MOs, schedules jobs, exports Excel, optionally previews Nokia reimport — never auto-push from laptop.

**What it does:** Discover NEs, extract MO parameters, schedule jobs, Excel export, Nokia reimport (`actualImport`).

**Progress:** [`features/cm-extractor.progress.md`](features/cm-extractor.progress.md)


**Plan:** No drive-by MO list expansion. Vendor API refs: `docs/HUAWEI_CM_OPEN_API_REFERENCE.md`, `docs/CM_OPEN_API_RNC_BSC_REFERENCE.md`.

### CM Parameter Audit

| | |
|---|---|
| Slug | `cm-parameter-audit` |
| Route | `/cm-parameter-audit` |
| Access | all |
| Version | from `modules/cm_parameter_audit/version.py` |
| Brief | [`features/cm-parameter-audit.md`](features/cm-parameter-audit.md) |
| Progress | [`features/cm-parameter-audit.progress.md`](features/cm-parameter-audit.progress.md) |

**User sees:** User defines golden/consistency rules, runs scans, reviews Excel/table findings; golden panel is admin-gated.

**What it does:** Rules with band/area scope, version, approval/baseline. Detector honors the same scope.

**Progress:** [`features/cm-parameter-audit.progress.md`](features/cm-parameter-audit.progress.md)


**Plan:** **Parked:** browser-verify `/cm-parameter-audit`.

### XML Parser

| | |
|---|---|
| Slug | `xml-parser` |
| Route | `/xml-parser` |
| Access | all |
| Version | V1.1 |
| Brief | [`features/xml-parser.md`](features/xml-parser.md) |
| Progress | [`features/xml-parser.progress.md`](features/xml-parser.progress.md) |

**User sees:** User uploads/parses vendor XML/RAML plans with validation before apply workflows.

**What it does:** Upload/parse XML, save/load profiles, validate MO vs dictionary / golden rules.

**Progress:** [`features/xml-parser.progress.md`](features/xml-parser.progress.md)


**Plan:** **Parked:** browser-verify `/xml-parser`.

### XML Generator

| | |
|---|---|
| Slug | `excel-generator` |
| Route | `/excel-generator` |
| Access | all |
| Version | V1.2 |
| Brief | [`features/excel-generator.md`](features/excel-generator.md) |
| Progress | [`features/excel-generator.progress.md`](features/excel-generator.progress.md) |

**User sees:** User builds XML/plan output from Excel-style inputs (XML Generator).

**What it does:** Generate vendor XML/Excel. Pre-flight against dictionary, golden rules, and CM snapshot diff.

**Progress:** [`features/excel-generator.progress.md`](features/excel-generator.progress.md)


**Plan:** **Parked:** browser-verify `/excel-generator`.

### NE Comparison

| | |
|---|---|
| Slug | `ne-comparison` |
| Route | `/ne-comparison` |
| Access | all |
| Version | V1.0 |
| Brief | [`features/ne-comparison.md`](features/ne-comparison.md) |
| Progress | [`features/ne-comparison.progress.md`](features/ne-comparison.progress.md) |

**User sees:** User compares NE/MO parameter sets across snapshots or sources.

**What it does:** Side-by-side / delta of MO parameters between two NEs.

**Progress:** [`features/ne-comparison.progress.md`](features/ne-comparison.progress.md)


**Plan:** None parked.

### RET Management

| | |
|---|---|
| Slug | `ret-management` |
| Route | `/ret-management` |
| Access | all |
| Version | V1.2 |
| Brief | [`features/ret-management.md`](features/ret-management.md) |
| Progress | [`features/ret-management.progress.md`](features/ret-management.progress.md) |

**User sees:** User manages RET (remote electrical tilt) related config/ops for selected NEs.

**What it does:** Antenna RET values. Unit tests in `test_logic.py` — read those first. Sector+tech from Huawei Subunit Name / Nokia sectorID; azimuth from metadata; three.js mesh hologram with per-tech toggles.

**Progress:** [`features/ret-management.progress.md`](features/ret-management.progress.md)


**Plan:** None parked.

### Configuration Dashboard

| | |
|---|---|
| Slug | `configuration-dashboard` |
| Route | `/configuration-dashboard` |
| Access | all |
| Version | V1.1 |
| Brief | [`features/configuration-dashboard.md`](features/configuration-dashboard.md) |
| Progress | [`features/configuration-dashboard.progress.md`](features/configuration-dashboard.progress.md) |

**User sees:** Tabs for Nokia radio hardware Sankey and WNCELG Area → Split/No-split → group-count Sankey.

**What it does:** Shared daily 04:00 (and admin manual) `RMOD_R` + `WNCELG` snapshots; UI + Excel from DB only. Hardware engine stays in `modules/rru_inventory/`. Legacy `/rru-inventory` redirects to Hardware tab.

**Progress:** [`features/configuration-dashboard.progress.md`](features/configuration-dashboard.progress.md)


**Plan:** None parked.

### Radio Hardware Inventory Report

| | |
|---|---|
| Slug | `rru-inventory` |
| Route | `/configuration-dashboard?tab=hardware` (legacy `/rru-inventory`) |
| Access | all |
| Version | V1.2 |
| Brief | [`features/rru-inventory.md`](features/rru-inventory.md) |
| Progress | [`features/rru-inventory.progress.md`](features/rru-inventory.progress.md) |

**User sees:** Sankey of Nokia radio modules by area and tech/band vs RRU hardware type (snapshot-only). Now the Hardware tab of Configuration Dashboard.

**What it does:** Part of shared Configuration Dashboard ingest (`RMOD_R` + `WNCELG`). Engine in `modules/rru_inventory/`.

**Progress:** [`features/rru-inventory.progress.md`](features/rru-inventory.progress.md)


**Plan:** None parked — surface moved under Configuration Dashboard.

### Config Task Scheduler

| | |
|---|---|
| Slug | `config-task-scheduler` |
| Route | `/config-task-scheduler` |
| Access | all |
| Version | V1.0 |
| Brief | [`features/config-task-scheduler.md`](features/config-task-scheduler.md) |
| Progress | [`features/config-task-scheduler.progress.md`](features/config-task-scheduler.progress.md) |

**User sees:** User schedules configuration tasks via the config scheduler UI.

**What it does:** User-facing scheduler for config tasks (`config_scheduler_*` tables in ncm_users / app schema).

**Progress:** [`features/config-task-scheduler.progress.md`](features/config-task-scheduler.progress.md)


**Plan:** None parked.

### Config History

| | |
|---|---|
| Slug | `config-history` |
| Route | `/config-history` |
| Access | all |
| Version | V1.0 |
| Brief | [`features/config-history.md`](features/config-history.md) |
| Progress | [`features/config-history.progress.md`](features/config-history.progress.md) |

**User sees:** User browses historical CM change records / audit trail.

**What it does:** Browse recorded CM changes (snapshot/audit trail).

**Progress:** [`features/config-history.progress.md`](features/config-history.progress.md)


**Plan:** None parked.

### Network Management

| | |
|---|---|
| Slug | `network-management` |
| Route | `/network-management` |
| Access | all |
| Version | V1.0 |
| Brief | [`features/network-management.md`](features/network-management.md) |
| Progress | [`features/network-management.progress.md`](features/network-management.progress.md) |

**User sees:** User performs network-management inventory/ops views in the module UI.

**What it does:** NE/site management views on PrimeNet metadata.

**Progress:** [`features/network-management.progress.md`](features/network-management.progress.md)


**Plan:** None parked.

### RAN Feature Library

| | |
|---|---|
| Slug | `ran-features` |
| Route | `/ran-features` |
| Access | all |
| Version | V1.0 |
| Brief | [`features/ran-features.md`](features/ran-features.md) |
| Progress | [`features/ran-features.progress.md`](features/ran-features.progress.md) |

**User sees:** User browses the RAN Feature Library (vendor feature references).

**What it does:** Browse vendor feature documentation / activation state.

**Progress:** [`features/ran-features.progress.md`](features/ran-features.progress.md)


**Plan:** None parked.

### Drive Test Viewer

| | |
|---|---|
| Slug | `drive-test-viewer` |
| Route | `/drive-test-viewer` |
| Access | all |
| Version | V1.0 |
| Brief | [`features/drive-test-viewer.md`](features/drive-test-viewer.md) |
| Progress | [`features/drive-test-viewer.progress.md`](features/drive-test-viewer.progress.md) |

**User sees:** User uploads/views drive-test logs on a map/timeline.

**What it does:** Plot DT samples (log files), not OSS PM.

**Progress:** [`features/drive-test-viewer.progress.md`](features/drive-test-viewer.progress.md)


**Plan:** None parked.

## Administration

### Platform Admin (NexusCore)

| | |
|---|---|
| Slug | `platform-admin` |
| Route | `/admin` (NexusCore) |
| Access | admin_or_noc |
| Version | V1.0 |
| Brief | [`features/platform-admin.md`](features/platform-admin.md) |
| Progress | [`features/platform-admin.progress.md`](features/platform-admin.progress.md) |

**User sees:** Owner/NOC opens Platform Admin from the portal tower for users, portal allow-list, and PrimeNet module access.

**What it does:** Create/disable users, reset password, portal grants, feature_access matrix (`core/feature_access.py`).

**Progress:** [`features/platform-admin.progress.md`](features/platform-admin.progress.md)

**Plan:** None parked.

### Admin Panel (Engineering)

| | |
|---|---|
| Slug | `admin-panel` |
| Route | `/admin-panel` (default `?section=data-sync`) |
| Access | admin (Owner) |
| Version | V1.0 |
| Brief | [`features/admin-panel.md`](features/admin-panel.md) |
| Progress | [`features/admin-panel.progress.md`](features/admin-panel.progress.md) |

**User sees:** Owner opens Engineering Admin for sync, API connections, PM Plus Rules, Ops Alerts, activity.

**What it does:** Data Sync, vendor API tests, PM Plus catalog/rollup, RET/CM accountability, activity log. Identity/module ACL moved to Platform Admin.

**Progress:** [`features/admin-panel.progress.md`](features/admin-panel.progress.md)

**Plan:** None parked.

### Developer Documentation

| | |
|---|---|
| Slug | `documentation` |
| Route | `/documentation` |
| Access | admin |
| Version | — |
| Brief | [`features/documentation.md`](features/documentation.md) |
| Progress | [`features/documentation.progress.md`](features/documentation.progress.md) |

**User sees:** Admin opens Developer Documentation catalog (course, architecture, graphify maps).

**What it does:** Serve `docs/course/`, `docs/ARCHITECTURE.md`, and graphify HTML (`graph.html`, call flow) via a catalog (`_catalog()` in `routes.py`) — no arbitrary filesystem reads.

**Progress:** [`features/documentation.progress.md`](features/documentation.progress.md)


**Plan:** Course Lesson 07 still calls Huawei LB a stub — briefs here are the correction. Optional later course patch; not required for agents.

### User Profile

| | |
|---|---|
| Slug | `user-profile` |
| Route | `/profile` |
| Access | all |
| Version | V1.0 (`profile` in `module_versions`) |
| Brief | [`features/user-profile.md`](features/user-profile.md) |
| Progress | [`features/user-profile.progress.md`](features/user-profile.progress.md) |

**User sees:** Any user opens Profile to manage account settings / personal vendor credentials where exposed.

**What it does:** User row + `user_vendor_credentials` + preferences. Password change satisfies `force_password_change`.

**Progress:** [`features/user-profile.progress.md`](features/user-profile.progress.md)


**Plan:** None parked.

---

## Shared engine notes

- Radio issue-list modules share `templates/radio_module.html` + `core/radio/` — read
  [`features/_radio-engine.md`](features/_radio-engine.md) before changing detectors.
- ETL master switch: `NCM_ENABLE_ETL` (`core/etl_gate.py`). Local laptop usually `0`.
- Do not invent roadmap: only record Plans that already exist in briefs / `progress.md`.

_Catalog of briefs + progress files. Keep Plans aligned with `<slug>.progress.md` NEXT._
