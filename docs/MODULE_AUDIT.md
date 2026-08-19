# PrimeNet — Module Audit

Every module in the Engineering Portal: does it run, what is it for, and what it is
missing — judged twice, once as **code** (developer) and once as **a tool an RF
engineer has to trust** (radio). Written from a live smoke test plus a code read.

**Audit date:** 2026-08-19 · **Scope:** 45 modules, 54 pages, 138 GET APIs, ~40.5k LOC

---

## 1. How this was tested, and what that does *not* prove

The app was booted locally (`NCM_SKIP_ACTIVATION=1`, scheduler off), logged in as
an admin, and every parameterless page and GET API in the Flask URL map was crawled
with that session.

| Result | Count |
|---|---|
| Pages returning 200 | **54 / 54** |
| APIs returning 200 with `success != false` | **110 / 138** |
| APIs returning a by-design 400 (missing required query param) | 17 |
| APIs blocked by unconfigured external systems (NetAct, U2020, SMB share) | 10 |
| Genuine server errors (500) | **1 — found and fixed, see §2** |
| Unit tests passing | **74 / 75** |

**Important limitation:** every PM/CM/neighbor database in the test environment is
*schema-only* (bootstrap-created, zero rows), and the daily PM, neighbor, and
KPI-header databases do not exist at all. This audit therefore proves **wiring** —
routes register, queries execute, templates render, JSON contracts hold, empty
states don't crash. It does **not** validate detector accuracy, KPI maths, or
threshold tuning against real traffic. §4 lists what to check on a populated
deployment.

---

## 2. Defects found

### Fixed in this pass

**Group / Cluster Health returned 500 on every request.** The shared radio blueprint
factory (`core/radio/blueprint.py`) passed `area=` to every detector, but
`group_health()` has no `area` parameter — group PM rows are BSC/RNC aggregates that
span areas. Every call raised `TypeError: group_health() got an unexpected keyword
argument 'area'`. Fixed by making the factory signature-aware: it passes `area` only
to builders that model it, and skips area filtering for those that don't, so
controller-level issues are no longer silently emptied when an area is selected.

### Open — reported, not fixed

**XML Parser "Save Profile" / "Load Profile" are dead buttons.** Rendered at
`modules/xml_parser/templates/xml_parser.html:54-55`, calling `/api/profiles/save`
and `/api/profiles/list`, which **do not exist** — verified live, both 404.

**`static/js/app.js` is dead code.** 1,145 lines / 40 KB, referenced by no template,
calling nine endpoints that no longer exist. Legacy from the pre-modular app.

**One test is data-dependent.** `modules/performance_dictionary/test_nokia_loader.py::test_load_nokia_data_has_entries`
asserts a non-empty Nokia measurement index, so it fails in any environment without
the (unversioned) dictionary source. It should skip, not fail.

---

## 3. Module by module

Each entry: what it does, what a **developer** would fix, what an **RF engineer**
would ask for. Gaps that belong to no single module are in §5.

---

### Overview & Performance

#### Dashboard — OK
- **Scope:** Landing page — site map, PM health, neighbor health, network activity, operational sites.
- **Dev:** Tile queries are unpaginated and uncached; layout is fixed beyond profile preferences; each tile is its own round trip with no shared payload.
- **RF:** No default scoping to *my* area/cluster — every engineer opens the whole network. No KPI status against operator targets (green/amber/red vs. a CSSR or drop-rate objective), so the tiles report activity rather than health. No "today's worst N" jump-off into actual work.

#### Performance Explorer (3.8k LOC) — OK
- **Scope:** The workhorse KPI browser — cell and group trends, PM tables, time-frame and area filters, multi-cell selection with compare tabs, Excel export, saved views.
- **Dev:** Largest single module. KPI alias resolution is spread across recipes and the headers DB and is hard to trace; the widest PM tables are unpaginated; one blueprint mixes query building, export, and view state. Needs a documented KPI-mapping contract.
- **RF:** **Daily scope only — no busy-hour or peak-hour selection**, which is the scope RF actually works in. Charts carry **no target/threshold reference lines** (verified: no annotation logic), so an engineer cannot see at a glance whether a cell is inside objective. No CM-change annotations on the trend, so before/after validation is done by eye against a separate screen.

#### Huawei PM Query Studio — OK (needs API)
- **Scope:** Live counter and NE browsing against the Huawei MAE PM Open API.
- **Dev:** Entirely dependent on a configured API; degrades to clear 404/503 but has no cached or offline mode, so the page is inert without connectivity.
- **RF:** Raw counter access with no KPI formula layer — the engineer must know the counter maths themselves. No saved counter sets per investigation type, and no bridge into Performance Explorer for the same cell.

#### Network Coverage Heatmap — OK
- **Scope:** KPI-driven intensity overlay on the map, backend-driven band and KPI lists.
- **Dev:** No export of the rendered layer; no legend calibration controls; point queries unbounded.
- **RF:** Intensity is KPI-relative, not calibrated to RF thresholds (e.g. RSRP bands), so colours can't be read as coverage quality. No time comparison (this week vs. last), which is how coverage change is actually judged.

#### Network Map (4.6k LOC) — OK
- **Scope:** Site/cell map, sector wedges, repeaters, cell-code search, KML/site export, neighbor lines.
- **Dev:** Second-largest module; mixes map rendering, neighbor linking, and export in one blueprint. Neighbor endpoints require explicit `technology`/`cell_name` (by design) but the UI offers no guidance when they're absent.
- **RF:** Wedges show inventory, not performance — no colouring by KPI or alarm state, so the map can't be used as a network-health picture. No terrain/clutter layer and no coverage prediction overlay, so it cannot answer why a cell behaves as it does.

#### Neighbor Analysis — OK
- **Scope:** Neighbor relations view built on raw neighbor export linking.
- **Dev:** Depends on neighbor DBs absent in fresh installs, with no "not synced yet" empty state distinct from "no relations".
- **RF:** Shows relations that exist; **cannot show relations that should exist** — no missing-neighbor/ANR analysis. No one-way vs. two-way summary per cell, and no ranking by HO traffic carried.

#### Performance Reports — OK
- **Scope:** On-demand and scheduled Excel generation with an archive. Five report types: Site Inventory, Conflict Report, Configuration Log, Sector Health, Sector Health (All Cells).
- **Dev:** Report types are code-defined (`REPORT_TYPES` dict) — adding one is a code change; no user-authored templates; archive has no retention policy.
- **RF:** **No KPI/performance report** in the set — all five are inventory or config reports. The weekly/monthly KPI pack an RF team actually circulates (trends vs. targets, top degradations, cluster summaries) has to be built by hand in Excel.

#### Power BI Reports — OK
- **Scope:** Link-out gallery to Power BI Service.
- **Dev:** Pure link list — no embedding, no per-user visibility rules.
- **RF:** Not integrated with PrimeNet context — no deep link that carries the current cell/area into the report.

#### Sector Health / Sector Health (All Cells) — OK
- **Scope:** Interactive sector tech-layer coverage view, same payload as the Sector Health report.
- **Dev:** Thin wrapper (109 LOC) over the report payload; conceptually overlaps Layer Coverage Gaps.
- **RF:** Build completeness only — a sector with all layers present but one layer carrying no traffic still reads as healthy. No link to the Sleeping Cell detector that would catch exactly that.

#### Conflict Map — OK
- **Scope:** Co-band PCI/PSC reuse conflicts by distance and azimuth-vs-bearing, KML export.
- **Dev:** Overlaps Network Management's PCI conflict API; distance/bearing thresholds hardcoded.
- **RF:** **One of four standard PCI checks.** Missing **PCI confusion** (two neighbors of the same cell sharing a PCI — a hard HO fault, not a risk score), **mod3 collision** (PSS/SSS and DMRS interference), and **mod30** (PUCCH/SRS). Also no RSI/PRACH root-sequence conflict check.

#### Femto PM — OK
- **Scope:** Femtocell PM — device catalog, KPI columns, trends, user-defined KPIs.
- **Dev:** Separate DB and data path from macro PM with no shared abstraction; absent from every fused/optimization view.
- **RF:** No macro–femto interaction analysis (interference or offload effectiveness), which is the main reason to look at femto at all.

#### Fault Management — OK (needs OSS)
- **Scope:** Live OSS alarm views, Nokia and Huawei, with time and NE filters.
- **Dev:** Read-only — no acknowledgement, no state persistence, no ticket hand-off (the natural bridge to a future Support Portal).
- **RF:** Alarms are listed, not **ranked by traffic impact** — no answer to "which of these 400 alarms is actually costing me traffic". No correlation to the Sleeping Cell or degradation detectors, and no VSWR/PIM-specific view despite those being prime RF fault classes.

---

### Radio Optimization

All detectors share one engine (`core/radio/`) and emit a normalized issue record
(score 0–100 → severity, evidence, recommendation, source link).

#### RF Optimization Workbench — OK
- **Scope:** Fuses five detectors (neighbor quality, capacity, overshooting, CM audit, change impact) into one prioritized queue; per-module chip filters.
- **Dev:** Fuses 5 of 11 available detectors; per-section caps (80) applied before the global merge, so a section with hundreds of Criticals is truncated before prioritization.
- **RF:** Ranking is **severity-only, not impact-weighted** — a symptom on a 2 GB/day cell outranks a milder one on a 400 GB/day cell. Issues on the same cell are listed separately rather than grouped, so the strongest real signal (one cell appearing in three detectors) is left for the eye to spot.

#### Radio Morning Report — OK
- **Scope:** Daily RF/NOC digest across all eleven detectors.
- **Dev:** Same section-cap behaviour as the Workbench; no export endpoint.
- **RF:** **Web-only** — a morning report should arrive by email at 07:00 with the overnight delta, not wait to be opened. No day-over-day comparison ("new since yesterday" vs. "still open"), which is the entire value of a daily report.

#### Neighbor Quality — OK
- **Scope:** Scores defined relations on HO success rate, failures, distance, reciprocity, cross-vendor.
- **Dev:** Rebuilds neighbor lines per call (now cached by the section runner); penalty weights hardcoded.
- **RF:** **Blind to missing neighbors** — an undefined neighbor generates no HO attempts, so a cell can score perfectly while dropping calls at a border. No TA/MR source, so distance is metadata-derived. No correlation to HO parameters (hysteresis, TTT, A3 offset), which is where the fix usually lives.

#### Capacity Hotspots — OK
- **Scope:** Ranks congested cells from PRB/utilization recipes against a prior-week daily baseline.
- **Dev:** Baseline is a fixed prior-week average with no seasonality handling.
- **RF:** **Daily averages, not busy hour** — the single most consequential gap in the suite. A cell at 45% daily PRB can sit at 95% in the evening peak; as built this will under-flag genuinely congested cells and over-flag flat-profile ones. No coverage-limited vs. capacity-limited classification, and no expansion recommendation (carrier add vs. sector split) with expected relief.

#### Overshooting Detector — OK
- **Scope:** Flags cells with neighbor relations beyond 8 km plus handover evidence.
- **Dev:** 8 km threshold and score cutoffs hardcoded.
- **RF:** **Distance is a proxy, not a diagnosis** — real overshooting is read from the timing-advance distribution tail. Produces false positives on legitimately planned long-range rural cells, and misses overshooters with no far neighbor defined. Threshold is not morphology- or band-aware (dense urban vs. desert highway).

#### Sleeping Cell Detector — OK
- **Scope:** Cells Active in CM whose recent traffic collapsed against their own baseline.
- **Dev:** Window and minimum-baseline thresholds are function defaults, not operator-configurable.
- **RF:** Genuinely valuable — catches the fault class that silently bleeds traffic. Missing the second half: **no correlation to VSWR / RET / hardware alarms**, so it cannot separate "sleeping" (needs a reset) from "faulty" (needs a site visit), which is the dispatch decision.

#### Layer Coverage Gaps — OK
- **Scope:** Inventory-based missing RAT/LTE-layer checks per sector.
- **Dev:** Overlaps Sector Health; inventory-only.
- **RF:** A layer present in CM but non-functional reads as fine. No traffic-based validation that a declared layer is actually serving, and no link to layer/traffic-steering strategy (idle-mode priorities).

#### CM Parameter Audit — OK
- **Scope:** Golden-parameter rules (equals / range / not-empty) against the latest CM snapshot.
- **Dev:** Rule management is minimal — no versioning, no approval trail, no rule test harness.
- **RF:** Exactly what a golden-config audit should be. Wants per-market/per-band rule sets (one golden value rarely fits a whole network) and MOP-grade change discipline: who approved this rule, when, and against which baseline.

#### Change Impact Tracker — OK
- **Scope:** Correlates detected CM changes with PM degradation on the same cell (65 when both appear, 35 for a change alone).
- **Dev:** Fixed score pair; no confidence measure; no handling of multiple changes landing on one cell.
- **RF:** **Correlation, not validation.** No control group (did untouched sibling cells degrade too?), no explicit before/after window per KPI, no statistical confidence. RNO practice needs "I applied X on day D — here is the KPI delta over D+7 against a comparable control set". Highest false-positive risk in the suite.

#### Mobility / HO Explorer, IRAT / Vendor Border, Alarm–PM Correlator — OK
- **Scope:** Thin blueprints over the shared engine — handover behaviour, inter-RAT and vendor-border issues, alarm-to-PM correlation.
- **Dev:** ~19 LOC each over `core/radio/`; the alarm correlator's 5-minute cache and correlation window are not tunable.
- **RF:** Mobility lacks a HO-parameter view alongside the failure counts. IRAT lacks a coverage-driven vs. parameter-driven distinction. The alarm correlator does not rank by traffic lost, so it tells you an alarm coincided with degradation but not whether it mattered.

#### Group / Cluster Health — Fixed (was 500)
- **Scope:** Controller/BSC/RNC congestion from group PM databases.
- **Dev:** Was crashing on every request (§2). No area dimension by nature.
- **RF:** No drill-down from a congested controller to its member cells — the natural next click is missing. No controller resource dimension (CPU / licence / Iub or S1 transport), which is usually the real constraint at that layer.

#### SON Optimization Insights — OK
- **Scope:** SON recommendations including geo-cluster grouping of degraded cells.
- **Dev:** Self-described "development stage"; recommendation builders are not unit-tested.
- **RF:** Recommendations are analytical groupings, not SON actions — no closed-loop SON (ANR, MRO, MLB) parameter proposals or write-back, which is what "SON" implies to an RF engineer.

#### Network Health Overview — OK
- **Scope:** KPI scorecard — clusters, groups, worst cells, per-category trends (Retainability, Accessibility, Mobility, Interference, Utilization) with `threshold_bad` values per category.
- **Dev:** Self-described "development stage"; the richest filter surface in the app, and several endpoints 400 unless the UI supplies params correctly.
- **RF:** **The only place operator thresholds exist** (`threshold_bad`) — and the radio detectors ignore them, scoring on separate hardcoded heuristics instead. Unifying the two would make every detector speak in operator KPI targets rather than an abstract 0–100.

#### Nokia Load Balancing (3.6k LOC) — OK (needs SMB share)
- **Scope:** AMLE parameter proposals from Network Balance CSVs → rules → Excel/MML export → verify → push. Four test files, ingest diagnostics.
- **Dev:** Depends on an SMB share that hard-blocks the module when unmounted (clear 503 diagnostic). The vendor pipeline lives in the module rather than `core/`.
- **RF:** **The most RF-credible module in the app** — concrete proposed values, verification, and a push path. This is the bar the rest of the optimization suite should meet. Wants post-push KPI verification (did the proposal actually move traffic?) to close its own loop.

#### Huawei Load Balancing — OK (needs SMB share)
- **Scope:** CellMLB proposals, same shape as the Nokia module.
- **Dev:** 610 LOC vs. Nokia's 3,556 — no push, no verify, no ingest diagnostics, one test file.
- **RF:** Same promise, far less delivered: the engineer gets proposals but no verification path and no way to apply them from the tool, so Huawei markets fall back to manual work.

---

### Configuration

#### Configuration Data Extractor (32 routes) — OK (needs CM)
- **Scope:** Live CM pulls from Nokia NetAct CM Open API and Huawei U2020 MML, job queue, exports, Excel re-import.
- **Dev:** Most route-dense module in the app; the job lifecycle and notification states would benefit from being documented and state-machined.
- **RF:** Extraction is on demand — no scheduled config baselining, so "what changed since last week" depends on someone having pulled a snapshot. No diff-on-extract summary.

#### CM Parameter Audit — see Radio Optimization.

#### Parameter Dictionary — OK
- **Scope:** MO parameter browsing, Nokia MRBTS tree, Huawei TOC, AI-assisted search.
- **Dev:** 678 ms list call — worth an index or cache.
- **RF:** Reference only — not linked to live values, so an engineer cannot see the definition and the network's current setting side by side, nor which cells deviate from a default.

#### Performance Dictionary — OK
- **Scope:** Nokia PM measurements, counters, and KPIs.
- **Dev:** Slowest endpoint measured (1.76 s); its one unit test is data-dependent (§2).
- **RF:** Nokia only — no Huawei counter dictionary, so half the network has no reference. Not linked from Performance Explorer, so looking up what a KPI means is a separate journey.

#### XML Parser — Partly broken
- **Scope:** XML → Excel conversion with filters.
- **Dev:** **Save/Load Profile buttons 404 (§2)** — implement or remove.
- **RF:** Conversion utility with no CM semantics — no MO-aware validation, so a malformed plan is only discovered when the network rejects it.

#### XML Generator — OK
- **Scope:** Excel → XML conversion.
- **Dev:** Minimal (188 LOC); no schema validation of generated XML.
- **RF:** Produces the file that gets pushed to the network with **no pre-flight validation** against MO rules or golden config — the riskiest gap in the config chain. No dry-run or diff against current network state before generation.

#### NE Comparison — OK
- **Scope:** XML/CM configuration diffing between NEs.
- **Dev:** Has write paths but far less test depth than Nokia Load Balancing.
- **RF:** Diffs NE to NE; no diff against a **golden template** for a cell class (band + morphology), which is the comparison RF actually wants when auditing a new site.

#### RET Management — OK (needs CM)
- **Scope:** View and edit antenna electrical tilts via live CM APIs, with credential fallbacks.
- **Dev:** Writes to the live network with no dry-run/preview mode in the UI and no per-change audit trail surfaced.
- **RF:** Trusted for what it does, but **disconnected from the detectors that recommend tilt changes** — Overshooting says "review tilt", RET can set it, nothing links them. No expected-gain estimate before applying, and no automatic post-change KPI verification.

#### Config Task Scheduler — OK
- **Scope:** Scheduled CM task management.
- **Dev:** Scheduling is app-local; scheduler health is not visible from this page.
- **RF:** No maintenance-window awareness or approval gate — an RF team needs changes to land in an agreed window with a rollback plan attached.

#### Config History — OK
- **Scope:** Upload, version, diff, and download XML configs.
- **Dev:** Filesystem-backed under the project root; no retention policy.
- **RF:** Versions what was *uploaded*, not what the network *actually holds* — no automatic snapshot from live CM, so history has gaps whenever someone forgets to upload. No rollback-to-version action.

#### Network Management — OK
- **Scope:** PCI/PSC/BCCH conflict detection (grouped by PCI and area) and a site cell browser.
- **Dev:** Overlaps Conflict Map — two half-implementations of the same audit.
- **RF:** Same PCI gaps as Conflict Map (no confusion, mod3, mod30, RSI). Conflicts are grouped by area rather than by actual neighbor relations or measured co-coverage, so distant same-PCI cells that never interfere are flagged alongside real collisions.

#### RAN Feature Library — OK
- **Scope:** Serves compiled Huawei HDX feature documentation.
- **Dev:** Vendor-specific with no Nokia equivalent.
- **RF:** Documentation only — no view of which features are actually **licensed and activated** in the network, which is the question an engineer opens a feature library to answer.

#### Drive Test Viewer — OK
- **Scope:** GPX + Nemo NMFS upload; route rendered on a map and **coloured by RSRP / RSCP / RSRQ / EcNo**.
- **Dev:** NMFS KPI extraction is **heuristic** — it scans int16 streams for smooth runs inside plausible dBm ranges (`routes.py:195-225`) rather than decoding the format. Values are inferred, not parsed, so accuracy is unproven.
- **RF:** No serving-cell decode, so a sample cannot be attributed to a cell — which rules out the main use (comparing measured coverage against the serving cell's PM and configuration). No scanner/Top-N neighbor view, no SINR or throughput, no benchmark comparison between drives, and no export of processed samples.

---

### Administration & shared

#### Admin Panel — OK
- **Scope:** User admin, feature-access matrix, activity log, PM latest timestamps, RET credential fallbacks.
- **Dev:** Solid feature-access model; activity log has no retention or rotation.
- **RF:** Access is per feature, not per **area/cluster** — an RF team cannot scope engineers to their own region's data.

#### User Profile — OK
- **Scope:** Profile, password, preferences, vendor credentials, saved views, photo requests.
- **Dev:** Per-user vendor credential storage deserves a dedicated security review.
- **RF:** Saved views exist per module, but there is no personal "my cells / my cluster" scope reused across modules.

#### Sync (6.4k LOC) — OK
- **Scope:** Largest module — SFTP/SMB pulls of PM, metadata, neighbor and group data; status, history, progress, diagnostics.
- **Dev:** Requires `paramiko` (in `requirements.txt`; a deployment that skips install gets 500s here). `/api/sync/test` takes 30 s against unreachable hosts with no per-host timeout surfaced.
- **RF:** **No hourly/busy-hour PM ingestion for cell-level data** — the daily-only pipeline is what forces every detector into daily scope. No data-completeness indicator per day/cell, so an engineer cannot tell whether a KPI dip is real or a missing file.

#### Documentation — OK
- **Scope:** In-app developer docs and code maps.
- **Dev / RF:** Developer-facing; there is no RF user guide or KPI/methodology reference for the engineers actually using the tools.

#### Elevation, Radio API — OK
- **Scope:** Authenticated elevation lookup; shared `/api/radio/areas` endpoint.
- **Dev / RF:** Small helpers, appropriately scoped. Elevation is not used for line-of-sight or overshooting analysis, where terrain would materially improve results.

---

## 4. What to verify on a populated deployment

1. **Detector precision** — sample 20 issues per detector and confirm with an RF engineer that they are real. Score calibration is untested against ground truth.
2. **KPI alias resolution** — verify each recipe in `core/radio/pm.py` binds to the intended vendor column for every RAT; silent mis-binding is the likeliest source of wrong numbers.
3. **Fused-view completeness** — confirm the Workbench and Morning Report reach full (non-partial) results on the second load, and note which sections routinely miss the time budget.
4. **Change Impact attribution** — highest false-positive risk in the suite.
5. **Drive Test NMFS extraction** — compare the heuristically-scanned values against Nemo's own export for the same log before trusting any of it.
6. **Write paths** (RET, CM extractor, Nokia LB push) — dry-run before any live push.

---

## 5. Gaps that belong to no single module

**Busy hour does not exist anywhere.** `modules/son_analytics/pm_helpers.py:19` sets
`PM_DATA_SCOPE = "daily"` and every detector inherits it. This is a data-pipeline
gap (Sync ingests daily cell PM) surfacing as an analysis gap in every RF module.
Fixing it once at ingestion upgrades Capacity, Sleeping Cells, Change Impact,
Network Health, and the Workbench together.

**Nothing is weighted by traffic or customer impact.** `core/radio/scoring.py` scores
symptom severity only, so every ranked list in the app orders by how bad a symptom
looks rather than how much traffic it costs. A single weighting term in
`bounded_score()` would re-rank the entire optimization suite.

**There is no issue lifecycle.** No detector issue can be assigned, acknowledged,
snoozed, or closed; the same rows reappear on every run with no memory that an
engineer already dispositioned them. This is what separates a set of detectors from
a workflow, and it is the largest RF-workflow gap after busy hour.

**Two threshold systems that don't talk.** Network Health has operator KPI thresholds
(`threshold_bad` per category); the radio detectors use separate hardcoded heuristics
(8 km, score cutoffs 20/25/30, severity bands 85/70/45, 95% HO target). Unifying them
behind one operator-editable store would make every detector speak in the operator's
own targets.

**The `core/radio/` engine has no unit tests.** 75 tests exist but cluster in four
modules; the scoring, filtering, and fusion logic that all 16 optimization modules
depend on has none. It is pure functions over dicts — the cheapest high-value
coverage available.

**Duplicated concepts.** Conflict Map vs. Network Management PCI; Sector Health vs.
Layer Coverage; Nokia LB (3,556 LOC, full pipeline) vs. Huawei LB (610 LOC,
export-only). Each pair should be merged or the asymmetry documented as deliberate.

**Empty states don't distinguish "no issues" from "no data".** No module crashed on
empty stores — genuinely good — but most render an empty table, which in the field
reads as "all clear" when it may mean "the neighbor DB never synced".

---

## 6. Priority lists

The two lenses produce different orders. Items 1–3 on the RF list depend on items
2–3 of the developer list being affordable, so in practice they interleave.

**Developer / codebase**
1. Fix or remove the XML Parser profile buttons — a visible feature that 404s.
2. Unit-test `core/radio/` — highest coverage value per line in the codebase.
3. Externalise detector thresholds into one operator-editable store.
4. Delete `static/js/app.js` — 1,145 lines of misleading dead code.
5. Group Workbench issues per cell/site; raise or remove the pre-merge section caps.
6. Add an integrations-health panel (NetAct / U2020 / MAE / SMB reachability).
7. Close the Huawei Load Balancing gap, or document it as intentionally export-only.

**RF / operational**
1. **Busy-hour scope** for PM ingestion and all detectors — without it, capacity output is not decision-grade.
2. **Traffic/impact weighting** in issue scoring — makes the priority queue genuinely prioritized.
3. **Issue lifecycle** (assign / acknowledge / snooze / close, with history) — turns detectors into a workflow.
4. **Missing-neighbor detection** — closes the biggest mobility blind spot.
5. **PCI confusion + mod3/mod30 + RSI checks** — completes the PCI audit.
6. **UL interference / RTWP detector** — adds a missing top-three fault class.
7. **Quantified recommendations** with proposed values and expected gain, following the Nokia LB pattern.
8. **Detect → RET → verify loop** — connect three modules that already exist.
9. **KPI report pack** in Performance Reports — the weekly deliverable is currently manual.
