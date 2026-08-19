# PrimeNet — Module Audit

A pass over every module in the Engineering Portal: does it run, what is it for,
and where does it fall short. Written from a live smoke test plus a code read.

**Audit date:** 2026-08-19 · **Scope:** 45 modules, 54 pages, 138 GET APIs, ~40.5k LOC

---

## 1. How this was tested, and what that does *not* prove

The app was booted locally (`NCM_SKIP_ACTIVATION=1`, scheduler off), logged in as
an admin, and every parameterless page and GET API in the Flask URL map was
crawled with that session.

| Result | Count |
|---|---|
| Pages returning 200 | **54 / 54** |
| APIs returning 200 with `success != false` | **110 / 138** |
| APIs returning a by-design 400 (missing required query param) | 17 |
| APIs blocked by unconfigured external systems (NetAct, U2020, SMB share) | 10 |
| Genuine server errors (500) | **1 — found and fixed, see §2** |
| Unit tests passing | **74 / 75** |

**Important limitation:** every PM/CM/neighbor database in the test environment
is *schema-only* (bootstrap-created, zero rows), and the daily PM, neighbor, and
KPI-header databases do not exist at all. So this audit proves **wiring** — routes
register, queries execute, templates render, JSON contracts hold, empty states
don't crash — but it does **not** validate detector accuracy, KPI maths, or
threshold tuning against real network data. Those need a run against a populated
deployment; §5 lists what to check there.

---

## 2. Defects found

### Fixed in this pass

**Group / Cluster Health returned 500 on every request.** The shared radio
blueprint factory (`core/radio/blueprint.py`) passed `area=` to every detector,
but `group_health()` has no `area` parameter — group PM rows are BSC/RNC
aggregates that span areas. Every call raised
`TypeError: group_health() got an unexpected keyword argument 'area'`.
Fixed by making the factory signature-aware: it passes `area` only to builders
that model it, and skips area filtering for those that don't (so controller-level
issues are no longer silently emptied when an area is selected).

### Open — reported, not fixed

**XML Parser "Save Profile" / "Load Profile" are dead buttons.** Both buttons are
rendered in `modules/xml_parser/templates/xml_parser.html:54-55` and call
`/api/profiles/save` and `/api/profiles/list`, which **do not exist** — verified
live, both return 404. Either implement filter-profile persistence (the saved-views
infrastructure in `static/js/saved_views.js` is a natural host) or remove the
buttons. Today they fail silently for the user.

**`static/js/app.js` is dead code.** 1,145 lines / 40 KB, referenced by no
template, calling nine endpoints that no longer exist (`/api/compare-xml`,
`/api/excel-to-xml`, `/api/mo/*`, `/api/tasks`, `/api/users`, …). Legacy from the
pre-modular app. Safe to delete; it currently misleads anyone grepping the codebase.

**One test is data-dependent.** `modules/performance_dictionary/test_nokia_loader.py::test_load_nokia_data_has_entries`
asserts the Nokia measurement index is non-empty, so it fails in any environment
without the (unversioned) Nokia dictionary source. It should skip when the source
is absent rather than fail.

---

## 3. Module inventory

Grouped as the navigation groups them. "Status" reflects the wiring test above.

### Overview & Performance

| Module | Status | What it does | Gaps / improvement |
|---|---|---|---|
| **Dashboard** | OK | Landing page: site map, PM health, neighbor health, network activity tiles | Tile queries are unpaginated; no user-configurable layout beyond profile prefs |
| **Performance Explorer** (3.8k LOC) | OK | The workhorse KPI browser — cell/group trends, PM tables, time-frame and area filters, Excel export, saved views | Largest single module; KPI alias resolution is spread across recipes and headers DB, hard to trace. Needs a documented KPI-mapping contract and pagination on the widest tables |
| **Huawei PM Query Studio** | OK (needs API) | Live counter/NE browsing against the Huawei MAE PM Open API | Entirely dependent on a configured Huawei API; degrades to 404/503 with a clear message but no cached/offline mode |
| **Network Coverage Heatmap** | OK | KPI-driven intensity overlay on the map | Band list and KPI set are backend-driven but there's no legend calibration or export of the rendered layer |
| **Network Map** (4.6k LOC) | OK | Site/cell map, sector wedges, repeaters, cell-code search, KML/site export, neighbor lines | Second-largest module and mixes map rendering, neighbor linking, and export concerns in one blueprint. Neighbor endpoints require explicit `technology`/`cell_name` (by design) but the UI gives no guidance when they're missing |
| **Neighbor Analysis** | OK | Neighbor relations view built on the raw neighbor export linking | Depends on neighbor DBs absent in fresh installs; no clear "data not synced yet" empty state |
| **Performance Reports** | OK | On-demand and scheduled Excel report generation with an archive | Report types are code-defined; no user-authored report templates |
| **Power BI Reports** | OK | Link-out gallery to Power BI Service | Pure link list — no embedding, no per-user report visibility |
| **Sector Health** / **(All Cells)** | OK | Sector tech-layer coverage view, same data as the Sector Health report | Thin wrapper (109 LOC) over the report payload; overlaps conceptually with Layer Coverage Gaps (see §4) |
| **Conflict Map** | OK | PCI reuse conflicts by distance + azimuth/bearing, KML export | Overlaps with Network Management's PCI conflict API (see §4); thresholds hardcoded |
| **Femto PM** | OK | Femtocell PM: device catalog, KPI columns, trends, user-defined KPIs | Separate DB and data path from macro PM; not represented in any fused/optimization view |
| **Fault Management** | OK | Live OSS alarm views | Read-only; no alarm acknowledgement, no ticket hand-off (this is the natural bridge to the future Support Portal) |

### Radio Optimization

All detectors share one engine (`core/radio/`) and emit a normalized issue record
(score 0–100 → severity, evidence, recommendation, source link).

| Module | Status | What it does | Gaps / improvement |
|---|---|---|---|
| **RF Optimization Workbench** | OK | Fuses 5 detectors into one prioritized action queue | Fuses only 5 of 11 detectors (omits sleeping cells, layer, mobility, alarm, IRAT); issues on the same cell are listed, not grouped — the cross-signal convergence value is left to the eye. **Highest-value next step: per-cell/site grouping** |
| **Radio Morning Report** | OK | Daily NOC/RF digest across all 11 detectors | Web-only — no scheduled email/export, which is what a "morning report" implies operationally |
| **Neighbor Quality** | OK | HO success rate, failed HOs, distance, missing reciprocal relations | No TA/MR data source, so distance is metadata-derived only (documented in the payload note) |
| **Capacity Hotspots** | OK | Congested cells via PRB/utilization recipes vs. daily baseline | Baseline is a fixed prior-week average; no seasonality or busy-hour awareness |
| **Overshooting Detector** | OK | Far-neighbor (>8 km) + HO evidence heuristic | Self-declared heuristic; 8 km threshold is hardcoded and not band- or morphology-aware (urban vs. rural) |
| **Sleeping Cell Detector** | OK | Recent traffic vs. own baseline, for cells Active in CM | Thresholds (recent/baseline days, min baseline) are function defaults, not operator-configurable in the UI |
| **Layer Coverage Gaps** | OK | Inventory-based missing RAT/LTE-layer checks per sector | Inventory-only — a layer present in CM but non-functional reads as fine |
| **CM Parameter Audit** | OK | Golden-parameter rules (equals/range/not-empty) vs. latest snapshot | Rule-set management is minimal; no rule versioning or approval trail |
| **Change Impact Tracker** | OK | Correlates CM changes with PM degradation on the same cell | Correlation is same-cell, same-window only — no control group, no overlapping-change disambiguation; scores are the fixed pair 65/35 |
| **Mobility / HO Explorer** | OK | Handover behaviour explorer | Thin wrapper over the shared engine |
| **Alarm–PM Correlator** | OK | Joins alarm windows to PM degradation | 5-minute cache; correlation window not tunable from the UI |
| **Group / Cluster Health** | **Fixed** (was 500) | Controller/BSC/RNC congestion from group PM DBs | No area dimension by nature; needs drill-down from controller → member cells |
| **IRAT / Vendor Border** | OK | Inter-RAT and vendor-border handover issues | Thin wrapper over the shared engine |
| **SON Optimization Insights** | OK | SON recommendations and summaries | Marked "development stage" in its own docstring |
| **Network Health Overview** | OK | KPI scorecard: clusters, groups, worst cells, trends | Marked "development stage"; the richest filter surface in the app but several endpoints require params the UI must supply correctly |
| **Nokia Load Balancing** (3.6k LOC) | OK (needs share) | AMLE parameter proposals from Network Balance CSVs → rules → Excel/MML export → verify → push | Best-tested module (4 test files) but depends on an SMB share that is a hard blocker when unmounted; returns a clear 503 diagnostic |
| **Huawei Load Balancing** | OK (needs share) | CellMLB proposals, same shape as Nokia | Much thinner than the Nokia twin (610 vs 3,556 LOC) — no push, no verify, no ingest diagnostics (see §4) |

### Configuration

| Module | Status | What it does | Gaps / improvement |
|---|---|---|---|
| **Configuration Data Extractor** (32 routes) | OK (needs CM) | Live CM pulls from Nokia NetAct CM Open API and Huawei U2020 MML, job queue, exports, re-import | Most route-dense module in the app; job state and notifications would benefit from a documented lifecycle |
| **CM Parameter Audit** | OK | (see Radio Optimization) | — |
| **Parameter Dictionary** | OK | MO parameter browsing, Nokia MRBTS tree, Huawei TOC | 678 ms list call — the slowest non-network read; worth an index or cache |
| **Performance Dictionary** | OK | Nokia PM measurements, counters, KPIs | Slowest endpoint measured (1.76 s); its one unit test is data-dependent (§2) |
| **XML Parser** | **Partly broken** | XML → Excel conversion with filters | **Save/Load Profile buttons 404 (§2)** |
| **XML Generator** | OK | Excel → XML conversion | Minimal (188 LOC); no schema validation of generated XML |
| **NE Comparison** | OK | XML/CM configuration diffing between NEs | Has write paths — deserves the same test depth as Nokia Load Balancing |
| **RET Management** | OK (needs CM) | View and edit antenna tilts via live CM APIs | Writes to live network; credential fallbacks exist but there's no dry-run/preview mode in the UI |
| **Config Task Scheduler** | OK | Scheduled CM task management | Scheduling is app-local; no visibility of scheduler health from this page |
| **Config History** | OK | Upload, version, diff, download XML configs | Storage is filesystem-based under the project root; no retention policy |
| **Network Management** | OK | PCI/PSC/BCCH conflict detection, site cell browser | Overlaps Conflict Map (§4) |
| **RAN Feature Library** | OK | Serves compiled Huawei HDX feature documentation | Vendor-specific (Huawei only); no Nokia equivalent |
| **Drive Test Viewer** | OK | Upload GPX + NMFS, visualise the drive route | Visualisation only — no KPI overlay from the drive log, no correlation to cell PM |

### Administration & shared

| Module | Status | What it does | Gaps / improvement |
|---|---|---|---|
| **Admin Panel** | OK | User admin, feature-access matrix, activity log, PM timestamps, RET credential fallbacks | Feature-access model is solid; activity log has no retention/rotation |
| **User Profile** | OK | Profile, password, preferences, vendor credentials, saved views, photo requests | Vendor credential storage is per-user — worth a security review pass of its own |
| **Documentation** | OK | In-app developer docs and code maps | — |
| **Sync** (6.4k LOC) | OK | Largest module: SFTP/SMB pulls of PM, metadata, neighbor and group data; status, history, progress, diagnostics | Requires `paramiko` (in `requirements.txt`, absent from my sandbox until installed — a fresh deployment that skips requirements gets 500s here). `/api/sync/test` takes 30 s against unreachable hosts with no per-host timeout surfaced to the UI |
| **Elevation** | OK | Authenticated elevation lookup | Tiny helper; 400 without coordinates is by design |
| **Radio API** | OK | Single shared endpoint: `/api/radio/areas` | Fine as-is |

---

## 4. Cross-cutting observations

**Duplicated concepts across modules.** Three pairs cover overlapping ground:
Conflict Map vs. Network Management's PCI conflict API; Sector Health vs. Layer
Coverage Gaps; and the two Load Balancing modules. The load-balancing asymmetry is
the sharpest — Nokia has ingest diagnostics, verify, push, and four test files,
while Huawei has none of those in 17% of the code. Either lift the shared pipeline
into `core/` with vendor rule packs, or document deliberately that Huawei LB is
export-only.

**Detector thresholds are hardcoded.** Overshooting distance (8 km), score cutoffs
(20/25/30), severity bands (85/70/45), neighbor SR target (95%), sleeping-cell
windows — all live in code. RF engineers will want these per-market and per-band.
A small `core/radio/thresholds.py` with admin-panel overrides would make the whole
optimization suite tunable without redeploys.

**Test coverage is concentrated.** 75 tests, but they cluster in four modules
(Nokia Load Balancing, RET, CM extractor, dictionaries). The entire `core/radio/`
insight engine — the scoring, filtering, and fusion logic that every optimization
module depends on — has **no unit tests**. That engine is pure functions over
dicts, so it is the cheapest high-value coverage available.

**Empty-state honesty.** Because every store was empty in the test environment,
the crawl doubled as an empty-data test: no module crashed, which is genuinely good.
But most modules render an empty table rather than saying "no data synced yet /
this needs the neighbor DB". Distinguishing *no issues* from *no data* would
prevent a class of false confidence in the field.

**External dependency surface.** Ten endpoints are hard-blocked without Nokia
NetAct, Huawei U2020/MAE, or the Network Balance SMB share. All fail with clear,
actionable messages — that's well handled. Worth surfacing one consolidated
"integrations health" panel so an operator sees at a glance which of the four
external systems are reachable.

**Route hygiene.** Every navigation entry resolves to a real route (no dead links),
and the only non-nav pages are intentional (`/login`, `/portals`, `/activation`,
`/health`, and a 301 redirect from the legacy `/amle-optimizer`). Clean.

---

## 5. What to verify on a populated deployment

This audit could not test data correctness. On a real dataset, check in this order:

1. **Detector precision** — sample 20 issues per detector and confirm with an RF
   engineer that they are real. Score calibration is untested against ground truth.
2. **Fused-view completeness** — after the recent time-budget change, confirm the
   Workbench and Morning Report reach full (non-partial) results on the second load,
   and note which sections routinely miss the budget.
3. **KPI alias resolution** — verify each recipe in `core/radio/pm.py` binds to the
   intended vendor column for every RAT; silent mis-binding is the most likely
   source of wrong numbers.
4. **Change Impact attribution** — the highest false-positive risk in the suite.
5. **Write paths** (RET, CM extractor, Nokia LB push) — dry-run before any live push.

---

## 6. Priority recommendations

1. **Fix or remove the XML Parser profile buttons** — a visible feature that 404s.
2. **Unit-test `core/radio/`** — highest coverage value per line in the codebase.
3. **Group Workbench issues per cell/site** — turns the merged list into real triage.
4. **Externalise detector thresholds** — per-market tuning without redeploys.
5. **Delete `static/js/app.js`** — 1,145 lines of misleading dead code.
6. **Add an integrations-health panel** — one view of NetAct / U2020 / MAE / SMB reachability.
7. **Close the Huawei Load Balancing gap** — or document it as intentionally export-only.
