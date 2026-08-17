# Lesson 07 — Module reference (all 41)

**Goal:** a code-level catalog of every module in `modules/`, grouped by family,
so you can jump straight to the right file. For each: its route prefix, its extra
files, and what makes it special. The heavy four (`cm_extractor`, `performance`,
`network_map`, `sync`) get their own deep dive in Lesson 08.

**How to read this:** modules in the "Radio optimization (engine wrappers)" group
are the Lesson-06 shape — don't re-read them individually, they're variations.
Everything else is a standalone tool; the notes tell you what's non-obvious.

Access rules (`all` / `admin` / `admin_or_noc`) come from
`core/module_access.py` `NAV_SECTIONS`.

---

## Group A — Radio optimization (engine wrappers)

All follow Lesson 06: a page route rendering `radio_module.html` + an
`/api/.../issues` route returning `{success, issues, summary}`. They differ only
in the detector they call and their titles. All are `admin`-visibility.

| Module | Route | Detector source | Notes |
|---|---|---|---|
| `sleeping_cells` | `/sleeping-cells` | local `logic.py` | Active-in-CM but traffic collapsed. The worked example in Lesson 06. |
| `overshooting_detector` | `/overshooting-detector` | `core/radio/insights.overshooting_candidates` | Long-neighbor + distance + handover evidence. 36 lines. |
| `capacity_hotspots` | `/capacity-hotspots` | `core/radio/insights` | High-utilization cells. 36 lines. |
| `neighbor_quality` | `/neighbor-quality` | `core/radio/insights` + `neighbor.py` | Bad/missing neighbor relations. 36 lines. |
| `layer_coverage` | `/layer-coverage` | `core/radio/insights` | Coverage-layer gaps. 36 lines. |
| `rf_optimization` | `/rf-optimization` | `core/radio/insights` | RF tuning workbench feed. 36 lines. |
| `change_impact` | `/change-impact` | `core/radio/insights` | Correlates config changes with KPI shifts. 36 lines. |
| `radio_morning_report` | `/radio-morning-report` | `core/radio/insights` | Daily digest of the above. 36 lines. |

> If you understand `sleeping_cells` (has logic) and `overshooting_detector` (no
> logic), you understand this entire group.

---

## Group B — Health & monitoring (heavier analytics)

| Module | Route | Extra files | Notes |
|---|---|---|---|
| `network_health` | `/network-health` | `config.py`, `logic.py`, `kpi_filter.py`, `precalc_job.py`, `precalc_store.py` | **Precompute pattern** (Lesson 05.5): a cron builds a KPI scorecard store; the page reads it. `admin`. Its `config.py`/`CATEGORY_PRESETS` are the alias source reused by the radio engine. |
| `sector_health` | `/sector-health`, `/sector-health-all` | — | Per-sector rollups. Two views: monitored sectors vs all cells. `all`. |
| `son_analytics` | `/son-analytics` | `logic.py`, `pm_helpers.py`, `area_helpers.py`, `config.py` | **Owns `pm_helpers.py`** — the PM benchmarking engine from Lessons 04–05 that half the app imports. SON = Self-Organizing Network insights. `admin`. |
| `fault_management` | `/fault-management` | — | Alarm/fault list (395 lines, 3 endpoints). `all`. |
| `femto_pm` | `/femto-pm` | `kpi_store.py` | Femtocell performance (small home cells). Own cached KPI store (880 lines). `all`. |
| `performance_analytics` | `/performance-analytics` | — | "Huawei PM Query Studio" — ad-hoc Huawei PM querying. `admin`. |

---

## Group C — Configuration management (CM)

The tools that read/compare/push device configuration rather than performance.

| Module | Route | Extra files | Notes |
|---|---|---|---|
| `cm_extractor` | `/cm-extractor` | `scripts/` | **Heavy — Lesson 08.** Live config extraction from Nokia NetAct / Huawei U2020. 32 endpoints, backed by `core/cm_extractor/`. `all`. |
| `cm_parameter_audit` | `/cm-parameter-audit` | `cache.py`, `export.py` | Audits config parameters against expected values; cached + exportable. `all`. |
| `config_history` | `/config-history` | — | Timeline of config changes (7 endpoints). `all`. |
| `xml_parser` | `/xml-parser` | — | Parse vendor XML config dumps. Uses `utils/xml_safety.py` (safe XML parsing — defends against XXE/entity attacks). `all`. |
| `excel_generator` | `/excel-generator` | — | "XML Generator" — builds config XML/Excel from templates. `all`. |
| `ne_comparison` | `/ne-comparison` | — | Compare two network elements' configs (949 lines, diff engine). `all`. |
| `ret_management` | `/ret-management` | `logic.py`, `test_logic.py` | Remote Electrical Tilt: read/adjust antenna tilt. Has unit tests — read `test_logic.py` to learn the module. `all`. |
| `network_management` | `/network-management` | — | General NE management actions. `all`. |
| `ran_features` | `/ran-features` | `hdx.py`, `navi.py` | RAN Feature Library — which features are licensed/active per NE. `all`. |
| `nokia_load_balancing` | `/nokia-load-balancing` | `logic.py`, `rules.py`, `ingest_job.py`, `balance_store.py`, `balance_data.py`, `export.py`, `push.py`, `file_discovery.py`, `smb_config.py` | **AMLE optimizer.** Ingests Network Balance CSVs → SQLite, live CM extract (`NOKLTE:AMLEPR`), proposes RAML XML/Excel, optional NetAct OSS `actualImport`. Admin. Legacy `/amle-optimizer` redirects here. |
| `huawei_load_balancing` | `/huawei-load-balancing` | — | **Stub.** Placeholder page only; no ingest/rules/push yet. Admin. |

---

## Group D — Dictionaries & reference data

| Module | Route | Extra files | Notes |
|---|---|---|---|
| `parameter_dictionary` | `/parameter-dictionary` | `nokia_loader.py`, `mrbts_tree_loader.py`, `knowledge.py`, `ai_service.py`, `huawei_params/`, `data/` | Searchable vendor parameter reference. **`huawei_params/` is ~19k scraped HTML files — do NOT edit**, served read-only. `ai_service.py` adds AI-assisted lookups. Includes an MRBTS graphical tree. `all`. |
| `performance_dictionary` | `/performance-dictionary` | `nokia_loader.py`, `test_nokia_loader.py`, `Nokia Performance/`, `data/` | Searchable KPI/counter reference. `all`. |

---

## Group E — Maps & geospatial

| Module | Route | Extra files | Notes |
|---|---|---|---|
| `network_map` | `/network-map` | `huawei_prs_tabular.py`, `neighbor_raw_linking.py`, `repeater_loader.py` | **Heavy — Lesson 08.** The big Leaflet map (2104 lines, 18 endpoints): sites, sectors, neighbors, repeaters. `all`. |
| `cell_heatmap` | `/cell-heatmap` | — | Coverage/KPI heatmap over the map (831 lines). `all`. |
| `conflict_map` | `/conflict-map` | `logic.py` | PCI/PSC/frequency conflict detection on the map. `all`. |
| `drive_test_viewer` | `/drive-test-viewer` | — | Renders drive-test measurement logs (451 lines). `all`. |
| `elevation` | `/elevation` | — | Terrain elevation lookups; backed by `core/elevation.py`. Feeds line-of-sight/overshooting. `all`. |

---

## Group F — Reporting

| Module | Route | Extra files | Notes |
|---|---|---|---|
| `reports` | `/reports` | `metadata_helpers.py`, `sector_coverage_data.py` | Performance report builder (649 lines). `all`. |
| `performance` | `/performance` | `kpi_catalog.py`, `kpi_mapping.py` | **Heavy — Lesson 08.** The main KPI Explorer (the biggest module): cell/trend charts, CSV export, caching. `all`. |
| `power_bi` | `/power-bi` | `logic.py` | Catalog-driven **link-out** gallery to Power BI Service. No embed tokens until the workspace has Premium/Fabric. `all`. |

---

## Group G — Admin & user

| Module | Route | Endpoints | Notes |
|---|---|---|---|
| `admin_panel` | `/admin-panel` | 9 | User administration (create/disable/role/reset) **and feature-access grants** (`core/feature_access.py`). `admin_or_noc`. |
| `user_profile` | `/profile` | 14 | Self-service profile + **change password** + **per-user vendor credentials**. `all`. |
| `sync` | `/sync` (+ APIs) | 18 | **Heavy — Lesson 08.** Drives the ETL pipeline from the UI: SFTP pulls, processors, scheduler. Own `sftp_client.py`, `pm_processor.py`, `metadata_processor.py`, `group_processor.py`, `scheduler.py`, `db_migration.py`. |
| `task_scheduler` | `/config-task-scheduler` | 8 | Schedule config tasks; ties into the task tables in `database_enhanced.py`. `all`. |
| `documentation` | `/documentation` | 3 | Admin-only course + architecture + **embedded graphify maps** (`graph.html`, `GRAPH_TREE.html`, `Project-callflow.html`). Catalog is `_catalog()` in `routes.py` — no arbitrary file reads. |

---

## Group H — Thin API helpers

| Module | Route | Notes |
|---|---|---|
| `radio_api` | `/api/radio/areas` | 15 lines. Just exposes `core/radio/metadata.list_areas()` for the shared filter-bar area dropdown. The minimal possible module — a good "hello world" to read. |

---

## How to explore any module yourself

For a module you haven't seen:

1. **`grep` its routes** to see the surface:
   ```bash
   grep -nE "\.route\(" modules/<name>/routes.py
   ```
2. **Read the page route** — what template does it render, what `api_url` does it
   pass? That tells you if it's the shared-shell pattern or a bespoke UI.
3. **Read the API route(s)** — what function do they call? That's the real logic;
   follow it into `logic.py` or `core/`.
4. **Check `__init__.py`** for the exported blueprint name, then confirm it's
   registered in `app.py`.

Nine times out of ten you'll recognize the Lesson-06 shape and be done in
minutes. The exceptions are the four heavy modules — next lesson.

---

## Recap

- ~41 modules fall into these families; the biggest family (radio optimization) is
  all the same Lesson-06 shape.
- The non-obvious ones: `network_health` (precompute store), `son_analytics`
  (owns `pm_helpers.py`), `parameter_dictionary` (huge do-not-edit reference),
  `sync` (drives the pipeline), `nokia_load_balancing` (AMLE + OSS push), and the
  four heavy modules.
- To learn any module fast: grep routes → read page route → follow the API route
  into logic.

**Next:** [Lesson 08 — The heavy subsystems](08-heavy-subsystems.md).
