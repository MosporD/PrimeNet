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
deployment; §6 lists what to check there.

Two lenses are used throughout: **§3–§4 and §7 are the engineering view** (does the
code work, is it maintainable) and **§5 is the RF/operational view** (would a radio
engineer trust and use it).

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
The "Gaps" column here is the **engineering view** (structure, coupling, coverage);
for the **RF/operational view** of the same modules see §5.

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

## 5. The RF engineer's view

§3 and §4 judge the code. This section judges the **tool**: would an RF/RNO
engineer trust it, and what would they immediately ask for. Every claim below was
checked against the source.

### 5.1 Workflow coverage

How an RF engineer's actual working week maps onto PrimeNet:

| RF workflow | Covered by | Verdict |
|---|---|---|
| Morning KPI check / worst cells | Radio Morning Report, Network Health, Performance Explorer | **Strong** |
| Trouble-ticket investigation (one cell/site) | Performance Explorer, Network Map, Fault Management | **Strong** |
| Neighbor / mobility optimization | Neighbor Quality, Mobility Explorer, IRAT Border | **Partial** — existing relations only (see 5.2 #2) |
| Capacity management | Capacity Hotspots, Load Balancing | **Partial** — no busy hour (see 5.2 #1) |
| Coverage optimization (tilt / azimuth / power) | Overshooting Detector, Layer Coverage, RET Management | **Partial** — detects, but does not propose values or close the loop |
| PCI / PSC planning and audit | Conflict Map, Network Management | **Partial** — reuse only, no confusion/mod3 (see 5.2 #3) |
| Interference / UL noise analysis | Network Health (RTWP KPI only) | **Missing as a detector** (see 5.2 #5) |
| Parameter audit / golden config | CM Parameter Audit, NE Comparison, Config History | **Strong** |
| Change validation (before/after) | Change Impact Tracker | **Partial** — correlation, not a validation cycle (see 5.2 #9) |
| Site acceptance / new-site validation | — | **Missing** |
| Drive test analysis | Drive Test Viewer | **Weak** — route display only, no KPI overlay or PM correlation |
| Capacity planning / expansion business case | — | **Missing** |
| VoLTE / voice quality | — | **Missing** |

### 5.2 Gaps that matter to an RF engineer, ranked by operational impact

**1. Everything runs on daily averages — there is no busy hour.**
`modules/son_analytics/pm_helpers.py:19` sets `PM_DATA_SCOPE = "daily"`, and every
detector inherits it. Capacity Hotspots compares a daily figure against a prior-week
daily average. RF capacity work is busy-hour work: a cell at 45% daily PRB can sit
at 95% in the evening peak, and a cell with flat all-day load can look worse than
it is. As built, the capacity ranking will **systematically under-flag genuinely
congested cells and over-flag flat-profile cells**. This is the single biggest
credibility gap for an RF audience — hourly stores already exist for group PM, so
the ingestion pattern is proven; the detectors need to consume a BH scope.

**2. Missing neighbors are invisible by construction.**
Neighbor Quality (`core/radio/neighbor.py`) scores relations that already exist —
low HO success, failures, distance, missing reciprocity. But the most common real
mobility fault is a neighbor that was **never defined**, causing drops at a border
with no HO attempts to score. Nothing in the codebase detects missing/undefined
neighbors (no ANR or X2 candidate handling anywhere). A cell can have a perfect
Neighbor Quality score and still be dropping calls into an undefined neighbor.

**3. PCI analysis covers reuse but not confusion or modulo collisions.**
Conflict Map does co-band PCI/PSC reuse by distance and azimuth-vs-bearing — good,
but it is one of three standard checks. Missing:
- **PCI confusion** — two neighbors *of the same cell* sharing a PCI, which breaks
  handover target resolution outright;
- **mod3 collision** — PSS/SSS and DMRS interference between strong neighbors;
- **mod30 collision** — PUCCH/SRS interference.
Any operator PCI audit expects all four. Confusion in particular is a hard fault,
not a risk score.

**4. Nothing is weighted by traffic or customer impact.**
`core/radio/scoring.py` scores pure symptom severity. An RF engineer prioritizes by
impact: 92% HO success on a cell carrying 400 GB/day outranks 85% on a cell carrying
2 GB. Without a traffic/Erlang/user weighting term, the "prioritized action queue"
is not prioritized the way an RF team prioritizes, and the Workbench's top rows may
be statistically noisy low-traffic cells. **Adding a traffic-weight multiplier to
`bounded_score()` is probably the highest value-per-line change in the suite.**

**5. There is no UL interference detector.**
RTWP / UL interference exists as a Network Health KPI category
(`modules/network_health/config.py:112`, threshold −95 dBm) but no detector in the
optimization suite hunts rising RTWP, external interference, or PIM signatures.
UL interference is a top-three real-world RF fault class and is well suited to the
existing detector pattern (baseline vs. recent, per cell).

**6. Recommendations name a topic, not an action.**
Every detector's recommendation is generic — *"Review antenna tilt/azimuth, power,
neighbor design"*, *"Check neighbor definition, reciprocity, distance"*. An RF tool
earns trust when it proposes a **value and an expected gain**: "E-tilt 3° → 5°,
expected overshoot reduction ~2 km, 6 affected relations". Notably, Nokia Load
Balancing already works this way (concrete AMLE parameter proposals, export, verify)
— that bar exists in the codebase and the optimization suite doesn't meet it.

**7. Overshooting without TA/MR is a weak proxy.**
The detector flags neighbor relations beyond 8 km with HO evidence, and is honest
about being a heuristic. But real overshooting is diagnosed from the **timing-advance
distribution tail** (or MR path-loss). Distance-based inference produces false
positives on legitimately planned long-range rural cells and **misses overshooters
that have no far neighbor defined at all** — which is the same blind spot as #2.
The 8 km threshold is also fixed, so it cannot distinguish dense urban from desert
highway morphology.

**8. Detect → act → verify is four disconnected modules.**
The natural RF loop — detect overshoot, propose a tilt, push it via RET, verify the
KPI moved — exists as Overshooting Detector, RET Management, and Change Impact
Tracker with **no links between them** (no reference to RET anywhere in
`core/radio/`). Today the engineer copies a cell name between three screens.

**9. Change Impact correlates, it does not validate.**
It flags a CM change on a cell that also degraded, scoring 65 when both appear and
35 for a change alone. That is a candidate list, not validation: no control group
(did untouched sibling cells degrade too?), no confidence measure, no explicit
before/after window comparison per KPI, and no disambiguation when several changes
land on one cell. RNO practice needs "I applied X on day D, here is the KPI delta
over D+7 against a comparable control set".

**10. The tool is issue-centric; RF work is campaign-centric.**
There is no cluster or campaign object — no way to say "I own Cluster 7 this
sprint, show me everything, track my progress, report what improved". Issues cannot
be assigned, acknowledged, snoozed, or closed; the same issue reappears every run
with no memory that an engineer already dispositioned it. **No issue lifecycle is
the biggest workflow gap after busy hour.**

**11. No coverage-limited vs capacity-limited classification.**
The standard first triage question — is this cell short of coverage or short of
capacity? — is unanswered, yet it decides whether the action is tilt/power or
carrier/sector split.

**12. 5G support is thin.** Only two NSA aliases appear in the KPI recipes
(`NSA Avg nr user`, `IntergNB HO SR NSA`). There is no SA handling, no beam/SSB
analysis, no NSA leg-retention or EN-DC setup-failure view. For a network deploying
5G, this is a growing blind spot.

**13. No VoLTE or voice-quality dimension** — no VoLTE accessibility/retainability
category, no MOS or codec view. For most operators voice KPIs are contractual.

**14. No planned-vs-actual comparison.** Nothing imports planning-tool output
(Atoll / Asset / Planet), so the tool cannot flag where the live network diverges
from the design — a routine optimization input.

### 5.3 What an RF engineer would say about specific modules

| Module | RF verdict |
|---|---|
| **Performance Explorer** | The module they'd live in. Wants busy-hour scope and per-KPI target lines on trends. |
| **RF Optimization Workbench** | Right idea; ranking is not impact-weighted (5.2 #4) and it covers 5 of 11 detectors. Add traffic weighting and per-cell grouping and it becomes the daily worklist. |
| **Radio Morning Report** | Content is right, delivery is wrong — a morning report should arrive by email at 07:00, not wait to be opened. |
| **Neighbor Quality** | Solid on defined relations; blind to missing ones (5.2 #2). |
| **Capacity Hotspots** | Cannot be trusted for capacity decisions until it's busy-hour based (5.2 #1). |
| **Overshooting Detector** | Useful screening list, not a diagnosis (5.2 #7). |
| **Sleeping Cell Detector** | Genuinely valuable — catches the fault type that silently costs traffic. Should correlate to VSWR/RET/hardware alarms to separate "sleeping" from "faulty". |
| **CM Parameter Audit** | Exactly what a golden-config audit should be. Wants rule versioning and an approval trail for MOP discipline. |
| **Nokia Load Balancing** | The most RF-credible module in the app: concrete proposals, export, verify, push. This is the template the rest should follow. |
| **Huawei Load Balancing** | Same promise, far less delivered — no verify, no push. |
| **Conflict Map / Network Management** | Two half-PCI-audits; merge them and add confusion + mod3/mod30 (5.2 #3). |
| **Drive Test Viewer** | Shows the route but not the radio — no RSRP/SINR overlay, no correlation to serving-cell PM. Currently a map, not an analysis tool. |
| **Fault Management** | Read-only alarm list. RF wants alarm-to-KPI-impact ranking (which alarms are actually costing traffic). |
| **RET Management** | Trusted for what it does; needs a dry-run/preview and a link from the detectors that recommend tilt changes (5.2 #8). |

### 5.4 RF priority list

If the next quarter of PrimeNet work were scoped by an RF manager rather than a
developer, this is the order:

1. **Busy-hour scope for all PM detectors** — without it, capacity output isn't decision-grade.
2. **Traffic/impact weighting in issue scoring** — makes the priority queue genuinely prioritized.
3. **Issue lifecycle** (assign / acknowledge / snooze / close, with history) — turns detectors into a workflow.
4. **Missing-neighbor detection** — closes the biggest mobility blind spot.
5. **PCI confusion + mod3/mod30 checks** — completes the PCI audit.
6. **UL interference / RTWP detector** — adds a missing top-three fault class.
7. **Quantified recommendations** with proposed values, following the Nokia LB pattern.
8. **Detect → RET → verify loop** — connect the three modules that already exist.

---

## 6. What to verify on a populated deployment

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

## 7. Priority recommendations (engineering / codebase)

The RF-facing priority list is §5.4. This one is about the code itself; the two
are complementary, and items 2–4 here are what make §5.4 affordable to build.

1. **Fix or remove the XML Parser profile buttons** — a visible feature that 404s.
2. **Unit-test `core/radio/`** — highest coverage value per line in the codebase.
3. **Group Workbench issues per cell/site** — turns the merged list into real triage.
4. **Externalise detector thresholds** — per-market tuning without redeploys.
5. **Delete `static/js/app.js`** — 1,145 lines of misleading dead code.
6. **Add an integrations-health panel** — one view of NetAct / U2020 / MAE / SMB reachability.
7. **Close the Huawei Load Balancing gap** — or document it as intentionally export-only.
