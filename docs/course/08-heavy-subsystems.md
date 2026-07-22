# Lesson 08 — The heavy subsystems

**Goal:** the four modules that don't fit the thin-wrapper pattern, because they
either talk to live network equipment, render huge interactive UIs, or drive the
data pipeline. You won't read every line — you'll learn the *shape* so you can
navigate them.

The four: `cm_extractor` (live config extraction), `performance` (KPI explorer),
`network_map` (the map), `sync` (ETL control plane).

---

## 8.1 `cm_extractor` — live configuration extraction

**Route:** `/cm-extractor`. **Size:** `routes.py` 1352 lines, 32 endpoints,
backed by the substantial `core/cm_extractor/` package. **This is the module that
actually talks to the customer's live network management systems.**

### The two vendor systems

- **Nokia NetAct** — accessed via an HTTP "Open API" and a bulk export
  interface.
- **Huawei U2020** — accessed via MML (Man-Machine Language) commands and its own
  discovery API.

`core/cm_extractor/` has a client + a semantics layer for each vendor:

| File | Role |
|---|---|
| `nokia_client.py`, `nokia_operations_client.py` | HTTP clients for NetAct. |
| `nokia_bulk_export.py`, `nokia_bulk_routing.py` | The bulk-export path (large config dumps). |
| `nokia_discovery.py`, `site_catalog.py` | Discover the MRBTS/RNC/BSC inventory. |
| `nokia_semantics.py`, `nokia_mass_modify.py` | Interpret MO trees; mass-modify parameters. |
| `nokia_excel_reimport.py` | Round-trip: export → edit in Excel → re-import. |
| `huawei_client.py`, `huawei_discovery.py`, `huawei_mml_discovery.py` | U2020 clients + discovery. |
| `mml_parser.py`, `huawei_semantics.py`, `huawei_param_dict.py` | Parse/understand Huawei MML + parameters. |
| `extraction.py` | The vendor-neutral extraction orchestration. |
| `export_store.py` | Persist finished exports + notifications. |
| `job_scheduler.py` | Scheduled recurring extractions. |
| `excel_writer.py` | Write results to `.xlsx`. |
| `http_util.py`, `config.py` | Shared HTTP + config. |
| `test_*.py` | **Read these to learn the module** — they show real inputs/outputs. |

### The endpoint flow (read `routes.py` in this order)

The 32 endpoints group into a clear workflow. Trace it top-down:

1. **Setup** — `GET /api/cm-extractor/defaults`,
   `POST /api/cm-extractor/test-connection`. Get saved connection settings and
   verify credentials reach NetAct/U2020.
2. **Discover inventory** — `.../nokia/sites`, `/nokia/areas`, `/nokia/discover`
   (and Huawei equivalents). "What sites/NEs exist, what MO classes do they have?"
   Results cache so you don't re-hit the live system every time.
3. **Pick what to extract** — `.../nokia/mo-classes`, `/nokia/parameters`,
   `/nokia/preview` (Huawei: `/huawei/mo-objects`, `/huawei/parameters`,
   `/huawei/preview`). Choose MO classes + parameters; preview before running.
4. **Extract** — `POST /api/cm-extractor/extract` kicks off the job;
   `GET /api/cm-extractor/extract-status/<file_id>` polls progress (extractions
   run in the background — this is why the input-size budget is bumped to 8 MB in
   `app.py`, Lesson 02). Finished files: `/exports`, `/download/<file_id>`.
5. **Scheduled jobs** — `GET|POST /api/cm-extractor/jobs`, plus
   `/jobs/<id>/toggle`, `/run-now`, `/runs`, `/runs/<id>/download`. Recurring
   extractions run by `core/cm_extractor/job_scheduler.py`.
6. **Round-trip edit** — `/nokia/reimport/preview` + `/nokia/reimport/execute`:
   export config, edit the Excel, push changes back. This is a *write* path to
   the live network — handled carefully, admin-guarded, previewed first.
7. **Notifications** — `/notifications`, `/notifications/seen`: surface completed
   background jobs to the UI.

The CLI entry points documented in `modules/cm_extractor/__init__.py`
(`run_nokia_netact_discovery`, `run_huawei_u2020_discovery`,
`run_due_jobs`, `run_extraction`) let you exercise all of this **without the web
UI** — the best way to learn it. Reference docs:
`docs/CM_OPEN_API_RNC_BSC_REFERENCE.md`, `docs/HUAWEI_CM_OPEN_API_REFERENCE.md`.

> **Mental model:** `cm_extractor` is a mini application. Routes = HTTP surface;
> `core/cm_extractor/` = the vendor SDKs, parsers, and job engine. When debugging,
> figure out which of the 7 phases above you're in, then go to the matching
> `core/cm_extractor/` file.

---

## 8.2 `performance` — the KPI Explorer

**Route:** `/performance`. **Size:** 2981 lines — the single biggest module.
**Extra files:** `kpi_catalog.py`, `kpi_mapping.py`. It's the deep-dive tool for
looking at cell/site KPIs over time.

It's big not because it's complex logic but because it handles **many
combinations**: 2 vendors × 5 RATs × hourly/daily × cells/groups × many KPIs ×
trend/table/CSV output — each with correct column discovery, timestamp parsing,
and caching. Reading the function names (`grep -nE "^def " modules/performance/routes.py`)
shows the structure:

- **Vendor/scope routing** — `_pm_db_for_vendor`, `_groups_db_for_vendor`,
  `_normalize_granularity`, `_normalize_data_scope`, `_resolve_pm_table_bundle`.
  Pick the right DB + table for the current selection.
- **Trend building** — `_pick_trend_time_value`, `_aggregate_trend_rows`,
  `_filter_trend_rows_by_hours`, `_parse_trend_ts`. Turn raw PM rows into a clean
  time series for charts (handling the messy timestamps from Lesson 04).
- **KPI catalog** — `_kpi_scope_from_catalog`, `_kpi_mapping_from_catalog`,
  `_drop_duplicate_kpis`. Which KPIs to offer for a vendor/tech, from
  `kpi_catalog.py`/`kpi_mapping.py` and the `KPI_HEADERS_DB`.
- **Caching everywhere** — `_cell_cache_*`, `_trend_cache_*`, `_pm_table_cache_*`,
  keyed partly by `_pm_data_version_token` (a DB-mtime token, so the cache
  invalidates when the pipeline writes). Same mtime-aware idea as Lesson 04, at
  larger scale.
- **CSV export** — `_pm_table_csv_response` streams a table download.

Notice it defines its **own** `login_required`/`get_current_user` (line 736)
rather than importing from `core/radio/web.py` — a small inconsistency from before
the shared helper existed. Functionally identical.

> **How to work in it:** don't read top-to-bottom. Find the endpoint for the
> behavior you care about (`grep "@performance_bp.route"`), read just that view
> and the handful of helpers it calls. The caching helpers are noise until you
> specifically need them.

---

## 8.3 `network_map` — the interactive map

**Route:** `/network-map`. **Size:** 2104 lines, 18 endpoints. **Extra files:**
`huawei_prs_tabular.py`, `neighbor_raw_linking.py`, `repeater_loader.py`.

It's a **Leaflet** map (that's why `app.py`'s CSP whitelists OpenStreetMap and
ArcGIS tile servers — Lesson 02). The backend's job is to feed the map GeoJSON-ish
payloads:

- **Sites & sectors** — cell inventory from `metadata.db` with lat/lng, drawn as
  markers and sector wedges (bearing + beamwidth).
- **Neighbors** — relations from the neighbor DBs; `neighbor_raw_linking.py`
  links raw neighbor exports to known cells so lines can be drawn between them.
- **Repeaters** — `repeater_loader.py` loads repeater equipment onto the map.
- **Huawei PRS** — `huawei_prs_tabular.py` handles a Huawei-specific tabular data
  source.

The 18 endpoints are mostly "give me layer X for the current viewport/filters."
The frontend (a large template + JS) does the rendering. Because the map can
request a lot of points, look for **thinning** logic (like `_thin_site_points` in
`auth_routes.py`) that caps how many markers get sent.

> **How to work in it:** decide whether your change is *data* (a backend endpoint
> producing the wrong points) or *display* (the Leaflet JS in the template). They
> meet at the JSON payload — inspect it in the browser Network tab first to know
> which side to open.

---

## 8.4 `sync` — the ETL control plane

**Route:** `/sync` + APIs. **Size:** `routes.py` 1003 lines, 18 endpoints.
**Extra files:** `sftp_client.py`, `pm_processor.py`, `metadata_processor.py`,
`group_processor.py`, `metadata_active_sql.py`, `scheduler.py`, `db_migration.py`.

This is the **UI + orchestration for getting data into the app**. It's the web-
facing sibling of the `pipeline/` package (Lesson 09). Its parts:

- `sftp_client.py` — connects to the three source servers (Nokia PM, Huawei PM,
  metadata — IPs at the top of `sync_config.py`) and pulls raw files.
- `pm_processor.py` / `group_processor.py` / `metadata_processor.py` — parse the
  pulled files and load rows into the right SQLite tables (the PM/groups/metadata
  DBs from Lesson 04).
- `metadata_active_sql.py` — SQL for computing which cells are "active."
- `scheduler.py` — runs pulls/loads on a schedule.
- `db_migration.py` — schema migrations for the data DBs.

The 18 endpoints let an admin trigger pulls, watch progress (this is what the
Windows-only "live sync logger terminal" in `app.py` tails), and configure
schedules. The `sync_config.py` file you met in Lesson 04 is the shared
configuration both `sync/` and `pipeline/` read.

> **`sync/` vs `pipeline/`:** `sync/` is the interactive, UI-driven path;
> `pipeline/` is the canonical scripted path (orchestrators run by cron/Docker).
> They overlap by design. `AGENTS.md` says prefer `pipeline/orchestrators/` for
> new automation. More in Lesson 09.

---

## 8.5 What these four have in common

Even the heavy modules keep the layering:

- **Routes stay HTTP-shaped** — parse, delegate, jsonify. The real work is in a
  `core/` package (`cm_extractor`) or sibling processor files (`sync`) or is just
  the sheer number of combinations (`performance`, `network_map`).
- **Background + caching** — anything slow (extraction, PM trends, map layers,
  pulls) is cached or pushed to a background job with a status-poll endpoint.
- **They read the same DBs** through the same `sync_config.py` constants. No
  module invents its own storage location.

So the skills from Lessons 01–06 still apply; these modules are just *more* of the
same, with a vendor-SDK or a big UI attached.

---

## Recap

- `cm_extractor`: a mini-app that talks to Nokia NetAct / Huawei U2020; routes are
  a 7-phase workflow, real logic in `core/cm_extractor/`, learnable via its CLI +
  tests.
- `performance`: biggest module, big because of vendor×RAT×scope×output
  combinations + heavy caching, not deep logic.
- `network_map`: Leaflet map fed by 18 data endpoints; split changes into
  data-side vs display-side.
- `sync`: the UI/orchestration for ETL; sibling to `pipeline/`.

**Next:** [Lesson 09 — The ETL pipeline](09-pipeline.md).
