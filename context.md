# PrimeNet — session context

**Read this first in any new session.** It is the bootstrap file: what this
project is, the domain it lives in, the handful of mechanisms that will
surprise you, and where to go for depth.

| Doc | What it is | Read when |
|---|---|---|
| **`context.md`** (this file) | Session bootstrap: domain, spine, landmines, task recipes | Always, first |
| `AGENTS.md` | Terse conventions + do-not-edit list | Always, second (it's short) |
| `docs/ARCHITECTURE.md` | One-page architecture map with a `where to look first` table | Before touching an unfamiliar layer |
| `docs/course/` (12 lessons) | Full code-level walkthrough with `file:line` refs | When you need real depth on a layer |
| `docs/FRONTEND_THEME.md` | Theme tokens + **mandatory dark-mode checklist** | Any UI change, no exceptions |
| `progress.md` | Dated log of verified work + the `NEXT` pointer | Start of session, to know what's in flight |
| `checklist.md` | Definition-of-done for the *current* effort | Before deciding if something is in scope |
| `.cursor/rules/*.mdc` | Per-glob conventions (flask-modules, pipeline, templates-ui) | Editor-driven; same rules as AGENTS.md |
| `docs/*_CM_OPEN_API_*.md` | Nokia/Huawei vendor API references | Working in `core/cm_extractor/` |

There is **no `README.md`** at the root — `AGENTS.md` + `docs/ARCHITECTURE.md`
serve that purpose.

---

## 1. What PrimeNet is

A **Flask web platform for radio-access-network (RAN) engineers** at a mobile
operator in **Jordan**. It ingests **performance (PM)** and **configuration
(CM)** data from a live cellular network — vendors **Nokia** and **Huawei**,
radio technologies **2G through 5G** — stores it in **SQLite**, and exposes
**39 feature modules** (dashboards, optimization detectors, config extractors,
reference dictionaries) behind a login.

It is an **internal operations tool**, not a public product: it talks to real
network element management systems (Nokia NetAct/MantaRay, Huawei U2020) over
SFTP and vendor REST/MML APIs, and it ships with a license/activation lock.

Entry point: `app.py`.

### Scale (measured, not estimated)

| | |
|---|---|
| Python files | 264 (~67.5k LOC) |
| Feature modules | 39 (`modules/*/`) |
| Registered blueprints | 41 (39 modules + `auth_bp` + `activation_bp`) |
| Nav links / features | 41 (`core/module_access.py`) |
| HTML templates | 37 (excluding reference corpora) |
| Frontend | ~13k lines CSS/JS in `static/` |
| `huawei_params/` reference HTML | **19,337 files** — do not edit, do not grep casually |
| Working tree | ~582 MB (`.git` is 163 MB of it) |

---

## 2. Domain glossary

You cannot read this codebase without these. They appear unexplained everywhere.

| Term | Meaning |
|---|---|
| **RAN** | Radio Access Network — the cell towers and their radios |
| **PM** | Performance Management — counters/KPIs per cell per time bucket (hourly/daily) |
| **CM** | Configuration Management — the parameter settings on network elements |
| **FM** | Fault Management — active alarms |
| **KPI** | Key Performance Indicator — a derived metric (drop rate, throughput, PRB utilization) |
| **RAT** | Radio Access Technology — 2G / 3G / 4G-FDD / 4G-TDD / 5G |
| **Cell** | One sector-carrier: the atomic unit of everything here |
| **Site / eNodeB / gNodeB / BTS / NodeB** | The physical tower; carries several cells (2G=BTS, 3G=NodeB, 4G=eNodeB, 5G=gNodeB) |
| **NE** | Network Element — a managed node (site, controller) |
| **MO / MO class** | Managed Object — a CM config entity (e.g. `LNCEL`, `LNREL`); its class is the type |
| **DN** | Distinguished Name — hierarchical MO path identifying an object |
| **MML** | Man-Machine Language — Huawei's command interface for CM |
| **NetAct / MantaRay** | Nokia's OSS; exposes the **CM Open API** used by `cm_extractor` |
| **U2020** | Huawei's OSS; exposes MML + Open API |
| **PCI / PSC / BCCH** | Physical Cell ID (4G/5G) / Scrambling Code (3G) / control channel (2G) — collision-sensitive identifiers |
| **PRB** | Physical Resource Block — the LTE/NR capacity unit; "PRB utilization" = load |
| **RET** | Remote Electrical Tilt — motorized antenna tilt, adjustable over the air |
| **Neighbor / neighbor relation** | Configured handover target between two cells |
| **SON** | Self-Organizing Network — automated optimization recommendations |
| **Overshooting** | A cell serving users far beyond its intended footprint |
| **Sleeping cell** | A cell that is configured Active but has stopped carrying traffic — a silent outage |
| **Femto** | Small indoor cells (own PM feed, own module) |
| **Area** | This network's geographic partition: *East Amman, West Amman, South Amman, East Jordan, North Jordan, South Jordan* (+ `Unknown`) |

---

## 3. The spine

Every request in this app has the same shape. Learn it once.

```
Browser  GET /sleeping-cells   (cookie: session_token)
   │
   ▼  app.py  @before_request stack, in order:
   │    1. enforce_monthly_operator_activation   → redirect /activation, or 403 for /api/*
   │    2. validate_and_sanitize_request_input   → g.sanitized_{json,form,args}
   │    3. enforce_csrf_origin_for_cookie_auth   → same-origin on POST/PUT/PATCH/DELETE
   │    4. enforce_password_rotation             → force /profile when rotation is due
   ▼
modules/<name>/routes.py     @login_required / @admin_required  (core/radio/web.py)
   │  page route → render_template("radio_module.html", api_url=..., module_title=...)
   ▼  (browser JS then calls api_url with the standard filter query string)
API route → logic.py
   │    ├─ core/radio/metadata.py   cell inventory
   │    ├─ core/radio/pm.py         KPI_RECIPES → vendor column resolution
   │    └─ db/runtime.performance_meta_pm_conn()   ATTACH + JOIN
   ▼
core/radio/scoring.py   filter_rows() + summarize()
   ▼
JSON {success, issues, summary} → @after_request set_security_headers → Browser
```

**The layering rule:** `modules/` is HTTP + presentation, `core/` is logic.
A `routes.py` parses the request, calls `core/` (or a local `logic.py`), and
JSON-ifies. Anything more than one module needs lives in `core/`.

Reference implementation of the whole pattern, small enough to read in one go:
`modules/sleeping_cells/` (`routes.py` is 70 lines).

---

## 4. The five mechanisms that will surprise you

### 4.1 The activation gate monkeypatches `sqlite3.connect`

`core/activation_gate.py:328` — `install_sqlite_gate()` replaces
`sqlite3.connect` globally. After that, **every** SQLite connection anywhere in
the process calls `is_activated()` first and raises `ActivationRequired` if not.

- `app.py:25` installs it **before any DB-touching import**. Import order there
  is load-bearing; `pyproject.toml` even whitelists `E402` for `app.py`.
- `db/runtime.py:17` installs it again defensively (idempotent).
- Two modes: **local** (PBKDF2 hash + HMAC-signed expiry file
  `.ncm_activation_state`, default 180 days) or **remote** (a separate license
  service holds the signing key — `core/license_client.py`,
  `core/license_tokens.py`).
- **For any local work set `NCM_SKIP_ACTIVATION=1`.** Without it, everything
  including `/health` returns 503 and every page redirects to `/activation`.

### 4.2 PM tables are partitioned by geographic area

The single most under-documented piece of domain logic. `core/site_area.py`
carries the full spec in its module docstring (lines 1–52) — read it before
touching PM queries.

- Base table name: `sync_config.pm_table_name(tech, scope)` →
  `4G_CELLS_HOURLY`, `2G_CELLS_DAILY`, etc.
- Area partition: `4G_CELLS_HOURLY__WEST_AMMAN` (slug =
  `area.upper().replace(" ", "_")`).
- Routing a site to an area: normalize the site id (NetAct long ids subtract
  60000 or 50000) → manual override table → `cluster = site_id // 100` →
  `CLUSTER_AREA` map → else dominant `area` from metadata cell tables.
- **New loads write only to area partitions; APIs dual-read partition + legacy
  monotable.** So a query that reads only the monotable silently misses recent
  data, and one that reads only partitions silently misses history. Use
  `core/site_area.list_pm_partition_tables()` / `preferred_pm_table()`.

### 4.3 One KPI concept, many vendor column names

Nokia and Huawei name the same counter differently, and names drift between
releases. `core/radio/pm.py:13` `KPI_RECIPES` maps a concept
(`"traffic"`, `"users"`, `"utilization"`, `"throughput"`, plus the
Mobility/Accessibility/Retainability/Interference presets from
`modules/network_health/config.py`) to a list of **aliases**, and
`resolve_kpi(vendor, rat, recipe)` matches them against the live column list —
exact, then normalized (alnum-lowercase), then substring.

Never hardcode a PM column name in a detector. Add an alias to the recipe.

### 4.4 The ATTACH + JOIN pattern

`db/runtime.performance_meta_pm_conn(vendor)` (`db/runtime.py:147`) opens
`metadata.db` and `ATTACH`es the PM database(s), so one query can JOIN cell
inventory against performance counters:

- single vendor → PM attached as alias **`pm`**
- both vendors → attached as **`nokia_pm`** + **`huawei_pm`** (and the returned
  alias is `None` — callers must branch)

Every connection from `db/runtime.py` sets `row_factory = Row`, `journal_mode =
WAL`, `busy_timeout = 120000`, and `execute_query()` retries 3× on
"database is locked". This matters because the background scheduler writes
while users read.

### 4.5 Cell "activity status" is vendor- and RAT-specific

`modules/sync/metadata_active_sql.py` — whether a cell is on-air depends on
which column and which magic string, per vendor **and** per RAT:

- 2G: Huawei `active_state = Activated`, Nokia `admin_state = Unlocked`
- 3G/5G: `active_state` — Huawei `Activated`, Nokia `Unlocked`
- 4G FDD: `active_state` — Huawei `Activated` *or* `CELL_ACTIVE`, Nokia `Unlocked` *or* `CELL_ACTIVE`
- 4G TDD: Huawei `active_state` `CELL_ACTIVE`, **Nokia `admin_state` `Unlocked`**

Use `PER_TABLE_ACTIVE_WHERE` / the exported CASE builders. Do not write your own
`WHERE status = 'Active'`.

---

## 5. Data model

Everything is **SQLite files** under `databases/` in a strict
`domain/vendor/technology/timeframe` taxonomy. **`sync_config.py` is the map —
never hardcode a path, import the constant.**

| Constant | Holds |
|---|---|
| `NCMUSERS_DB` | users, sessions, roles, tasks, saved views, feature access — the "app DB" |
| `METADATA_DB` | **cell inventory**: `cells_2g`, `cells_3g`, `cells_4g_fdd`, `cells_4g_tdd`, `cells_5g`, plus sites/sectors/groups |
| `NOKIA_PM_DB` / `HUAWEI_PM_DB` | hourly PM counters per cell (+ area partitions) |
| `NOKIA_PM_DAILY_DB` / `HUAWEI_PM_DAILY_DB` | daily-rollup PM |
| `NEIGHBOR_KPI_DB` / `HUAWEI_NEIGHBOR_RAW_DB` | neighbor relations + handover KPIs |
| `*_GROUPS_DB` (hourly/daily, per vendor) | cell-group aggregates |
| `KPI_HEADERS_DB` | KPI header catalog |

`DATA_ROOT` defaults to the repo root and is overridden by **`NCM_DATA_ROOT`**
(set to `/data` in Docker, with a volume mounted there).

Metadata cell tables are **schema-flexible**: `core/radio/metadata.py` probes
actual columns and picks the first match from an alias list
(`site_id` / `bcf id` / `enb_id_actual` / …). Assume nothing about column
presence; use `_pick_col`-style resolution.

Timestamps: `core/pm_timestamp.py` normalizes everything to naive wall-clock
`YYYY-MM-DD HH:MM:SS`. Huawei raw is **day-first** (`DD/MM/YYYY`), Nokia is not.
Recent commits added `report_date` / `report_time` columns; legacy rows may lack
them — handle both.

---

## 6. Auth, roles and access control

- **`database_enhanced.py`** (1,048 lines, root-level legacy) — the user/session
  layer over `NCMUSERS_DB`: `create_user`, `authenticate_user`, `create_session`,
  `get_user_by_session`, `log_activity`, tasks, filter profiles.
- **`routes/auth_routes.py`** — `/login`, `/register`, `/logout`, `/dashboard`,
  `/portals`, plus the dashboard data APIs (`/api/dashboard/pm-health`,
  `/site-map`, `/network-activity`, `/neighbor-health`, `/api/global-search`).
  Session is a `session_token` cookie; lifetime from `SESSION_LIFETIME_HOURS`
  (default 2).
- **`core/radio/web.py`** — the decorators modules actually use:
  `@login_required`, `@admin_required`, `get_current_user`, `format_user`,
  and `query_filters()` (parses the shared
  `area / vendor / technology / severity / q / limit` filter set).
- **`core/module_access.py`** — `NAV_SECTIONS`: the declarative list of all 41
  nav links with a `visibility` of `all` / `admin` / `admin_or_noc`. It both
  renders the nav *and* enforces access.
- **`core/feature_access.py`** — admin-configurable overrides on top of those
  defaults, stored in a `feature_access` table. `admin` always has everything;
  `/dashboard`, `/profile`, `/admin-panel` are **locked** so nobody can be
  locked out.

**Roles (4, not 3):** `admin` (Owner), `noc_sys` (NOC SYS),
`ran_config_user` (RNC User), `user` (User).
`docs/ARCHITECTURE.md` §5 predates `ran_config_user` and lists only three —
`core/feature_access.py:ROLE_ORDER` is the source of truth.

**User-shape gotcha:** a user is sometimes a `dict` and sometimes a positional
tuple where **`user[6]` is the role** (`core/radio/web.py:17`, `:84`). Legacy DB
rows are tuples. Mirror the tolerant helpers when you touch user objects.

---

## 7. Module index

Grouped as the dashboard groups them. Page route → module dir.

**Overview & Performance**
| Route | Module | Notes |
|---|---|---|
| `/dashboard` | `routes/auth_routes.py` | constellation deck landing page |
| `/performance` | `performance` | KPI explorer. **3,669-line `routes.py`** — the biggest file in the repo |
| `/performance-analytics` | `performance_analytics` | Huawei PM Query Studio (live U2020 queries) |
| `/cell-heatmap` | `cell_heatmap` | coverage heatmap |
| `/network-map`, `/neighbor-analysis` | `network_map` | Leaflet map, 2,500-line routes + `neighbor_raw_linking.py`, `repeater_loader.py` |
| `/reports` | `reports` | generated report archive |
| `/power-bi` | `power_bi` | catalog-driven link-out gallery (`catalog.json`) |
| `/sector-health`, `/sector-health-all` | `sector_health` | |
| `/conflict-map` | `conflict_map` | PCI/PSC/BCCH collisions, KML export |
| `/femto-pm` | `femto_pm` | femtocell PM + user-defined KPIs |
| `/fault-management` | `fault_management` | live alarms via Nokia FM API / Huawei |

**Radio Optimization** — all admin-only, all thin routes over `core/radio/` +
`modules/son_analytics/pm_helpers.py`, all rendering `templates/radio_module.html`
| Route | Module |
|---|---|
| `/son-analytics` | `son_analytics` (has real `logic.py`, `pm_helpers.py`) |
| `/network-health` | `network_health` (has precalc job + store) |
| `/rf-optimization` | `rf_optimization` |
| `/neighbor-quality` | `neighbor_quality` |
| `/capacity-hotspots` | `capacity_hotspots` |
| `/sleeping-cells` | `sleeping_cells` ← **read this one first** |
| `/layer-coverage` | `layer_coverage` |
| `/overshooting-detector` | `overshooting_detector` |
| `/change-impact` | `change_impact` |
| `/radio-morning-report` | `radio_morning_report` |

**Configuration**
| Route | Module | Notes |
|---|---|---|
| `/cm-extractor` | `cm_extractor` | the big one: live Nokia/Huawei extraction, 30+ endpoints, backed by `core/cm_extractor/` (~10.2k lines) |
| `/cm-parameter-audit` | `cm_parameter_audit` | |
| `/parameter-dictionary` | `parameter_dictionary` | serves the 19k-file `huawei_params/` corpus + an AI ask endpoint |
| `/performance-dictionary` | `performance_dictionary` | Nokia counter/KPI reference |
| `/xml-parser`, `/excel-generator` | `xml_parser`, `excel_generator` | vendor XML ↔ Excel (uses root `ncm_core.py`) |
| `/ne-comparison` | `ne_comparison` | |
| `/ret-management` | `ret_management` | remote electrical tilt; per-user vendor credentials |
| `/config-task-scheduler` | `task_scheduler` | |
| `/config-history` | `config_history` | config version diffs |
| `/network-management` | `network_management` | |
| `/ran-features` | `ran_features` | HDX feature docs |
| `/drive-test-viewer` | `drive_test_viewer` | |

**Administration**
| Route | Module |
|---|---|
| `/admin-panel` | `admin_panel` (users, roles, feature access, API connection tests) |
| `/documentation` | `documentation` — renders `docs/ARCHITECTURE.md` + `docs/course/*.md` in-app, **admin-only, fixed catalog** |
| `/profile` | `user_profile` (prefs, saved views, vendor credentials, photo requests) |
| `/sync` APIs | `sync` — drives the pipeline from the UI; owns the APScheduler |
| `/api/radio/areas`, `/api/elevation` | `radio_api`, `elevation` — API-only helpers |

---

## 8. ETL pipeline

Three SFTP sources (Nokia PM, Huawei PM, metadata — hosts and export paths in
`sync_config.py`, credentials in `.env`).

```
pipeline/orchestrators/orchestrate_{daily,hourly,watcher_cycle}_full.py   ← use these
pipeline/pull/<vendor>/all/<daily|hourly>/pull_all.py
pipeline/load/<vendor>/all/<daily|hourly>/load_all.py
pipeline/paths.py        raw/{vendor}/{domain}/{rat}/{timeframe}/
scripts/pipeline/*       legacy equivalents — kept for compatibility, don't extend
```

- Huawei daily exports stage in `raw/huawei/{cells,groups}/all/daily` **before**
  the RAT split.
- A pull returning **exit code 2** means *partial* (one vendor failed); the
  orchestrator still runs the load so a single-vendor miss doesn't stall
  ingestion.
- Scheduling lives in `modules/sync/scheduler.py` (APScheduler, 1,282 lines):
  interval raw pull, daily cron pull, a separate **neighbor sync cadence** (full
  SQLite replace), an SFTP **watcher** poll, Nokia CM inventory refresh, and a
  1-minute CM-extractor job tick. Each is individually disable-able via
  `NCM_DISABLE_*` env vars.
- **Adaptive RAM:** `core/load_monitor.py` + `core/resource_limits.py` — with
  `RESOURCE_ADAPTIVE=1` (default) ingest workers and heavy-query slots scale
  from live free RAM, with env vars as ceilings. `_defer_pipeline_if_low_memory()`
  will skip a job outright under pressure.
- After every load, `core/pm_indexes.py` rebuilds composite indexes;
  `core/pm_retention.py` prunes old rows; `core/pipeline_ingest_verify.py` checks
  whether row counts actually advanced (and the watcher re-runs if not).

---

## 9. Running it

```bash
pip install -r requirements.txt
cp .env.example .env
#  minimum for local dev, in .env:
#    NCM_SKIP_ACTIVATION=1              # else everything 503s / redirects
#    FLASK_DEBUG=1
#    NCM_DISABLE_AUTO_BROWSER=1         # app.py shells out to PowerShell otherwise
#    NCM_DISABLE_LIVE_LOGGER_TERMINAL=1 # same
#    NCM_DISABLE_SCHEDULER=1            # don't hit real SFTP servers from a dev box
python app.py            # → http://localhost:5000/dashboard
```

**On a fresh clone the `databases/` files are empty or absent.** Pages render;
tables are blank. That is expected and is not a bug to chase.

**Container:** `docker compose up -d --build` → `:8000`. Two services from one
image — `web` (gunicorn, scheduler disabled) and `scheduler` (the APScheduler
process). `deploy/entrypoint.sh` takes `web|dev|scheduler|bootstrap`.
`deploy/bootstrap.py` runs migrations + admin bootstrap before gunicorn.

**Lint:** `ruff check .` — config in `pyproject.toml`, line length 120, rule set
deliberately conservative (`E4,E7,E9,F`).

**Tests:** there is no test runner config and no CI. Nine scattered
`test_*.py` files exist (`core/test_site_area.py`, `core/test_pm_timestamp.py`,
`core/cm_extractor/test_*.py`, `modules/ret_management/test_logic.py`,
`modules/performance_dictionary/test_nokia_loader.py`). Run them with
`python -m pytest <path>`. **Assume no safety net** — verify changes by
exercising the actual page or endpoint.

**Env vars:** 114 of them, all documented (commented out) in `.env.example`.
Families: `NCM_*` (activation, license, data root, container, scheduler
toggles, bootstrap admin), `NOKIA_*` / `HUAWEI_*` / `METADATA_*` (SFTP + CM/FM
API), `FLASK_*`, `GUNICORN_*`, `OPENAI_*` (parameter-dictionary AI ask),
`RESOURCE_*`.

---

## 10. Landmines

1. **New blueprint not registered in `app.py`** → the route 404s. Import **and**
   `app.register_blueprint(...)`. This is the #1 self-inflicted bug here.
2. **Adding a page without a `NAV_SECTIONS` entry** → invisible and/or
   unenforced. Access rules go in `core/module_access.py`, nowhere else.
3. **Never `sqlite3.connect()` a literal path.** Use `db/runtime.py` helpers +
   `sync_config.py` constants, or you bypass WAL, timeouts, retries, and the
   activation gate.
4. **Do not edit** `modules/parameter_dictionary/huawei_params/` (19,337 scraped
   HTML files), `raw/`, `*.db`, `sync_downloads/`. They are runtime data.
   Unfiltered `grep -r` from the repo root will drown in them — always scope
   your search or use `--glob`.
5. **UI changes must satisfy `docs/FRONTEND_THEME.md`'s dark-mode checklist.**
   Light-only CSS is the most common regression in this repo's history.
6. **Bump `?v=X.X` cache-bust strings only on files you actually changed.**
7. **`templates/dashboard.html` is 1,903 lines.** Edit targeted sections; never
   rewrite the file wholesale.
8. **Any new PM query must handle both area partitions and the legacy
   monotable** (§4.2), and both new and legacy timestamp columns.
9. **`app.py` shells out to PowerShell** on startup (`_start_live_logger_terminal`,
   `_open_dashboard_browser`) — Windows-dev leftovers. Disable via env on Linux.
10. **CSP is set in `app.py:437`.** New external assets (CDNs, tile servers) must
    be added there or they are silently blocked in the browser.
11. **CM extractor payloads are huge** and get a deliberately larger input budget
    (8 MB / 100k items vs 1 MB / 5k) in `validate_and_sanitize_request_input`.
    Keep that carve-out if you touch the sanitizer.

---

## 11. Known debt

Honest list — useful for judging whether something is "existing style" or "a
thing to fix".

- **Fat route files.** `performance/routes.py` (3,669), `network_map/routes.py`
  (2,500), `cm_extractor/routes.py` (1,352) break the thin-routes rule the rest
  of the repo follows. Logic belongs in `logic.py` / `core/`.
- **Root-level legacy.** `ncm_core.py` (1,144 lines, "extracted from NCM_V3.py
  without GUI") and `database_enhanced.py` (1,048) predate the `core/` + `db/`
  layering and sit outside it.
- **Vestigial Postgres shims** in `db/runtime.py`: `is_postgresql()` returns
  `False`, `adapt_placeholders()` and `adapt_app_sql()` are identity functions.
  Ignore them; don't build on them.
- **Committed non-source at the root**: `PM202604260945+030072LNBTS.xml` (1.8 MB),
  `PrimeNet_Tool_Overview_With_Screenshots.pptx` (8.3 MB), plus sample data in
  `femto/`, `network-map/repeater/`, `data/`. `.gitignore` covers `raw/`/`*.db`
  but not these.
- **No CI, no test config, sparse tests** (§9).
- **Duplicated legacy pipeline**: `scripts/pipeline/` mirrors `pipeline/`.
  New work goes in `pipeline/`.
- **Role docs drift**: `docs/ARCHITECTURE.md` lists 3 roles, the code has 4.
- **`static/css/style.css` (51 KB) and `static/js/app.js` (39 KB)** are older
  monoliths alongside the newer `common.css`/`common.js` system.

---

## 12. Task recipes

| Goal | Do this |
|---|---|
| Add an analysis module | Copy `modules/sleeping_cells/` → rename blueprint → add `logic.py` → import + `register_blueprint` in `app.py` → add a `NAV_SECTIONS` entry → add a `MODULE_VERSIONS` entry in `core/module_versions.py` |
| Add a KPI to a detector | Add aliases to `core/radio/pm.py:KPI_RECIPES` — never a hardcoded column |
| Change who sees a page | `core/module_access.py` (default) and/or the admin panel's feature-access UI (`core/feature_access.py`) |
| Query PM data | `db/runtime.performance_meta_pm_conn(vendor)` + `core/site_area` partition helpers + `core/radio/pm.resolve_kpi` |
| Add a DB or path | A constant in `sync_config.py`, then a connector in `db/runtime.py` |
| Touch login/sessions | `routes/auth_routes.py` + `database_enhanced.py` |
| Change ingestion | `pipeline/orchestrators/` (+ `modules/sync/scheduler.py` for cadence) |
| Talk to a live NE | `core/cm_extractor/{nokia,huawei}_client.py`; see `docs/*_CM_OPEN_API_*.md` |
| Restyle | `static/css/common.css` + `radio_modules.css`; follow `docs/FRONTEND_THEME.md` |
| Publish a doc in-app | Add it to the catalog in `modules/documentation/routes.py` (fixed allowlist — arbitrary paths are refused by design) |

---

## 13. Session hygiene

1. Read `progress.md` — the newest dated entry and its **`NEXT`** pointer are the
   live task.
2. Read `checklist.md` — it defines what is in and out of scope right now.
3. Do the work; verify by exercising the real page/endpoint (there is no CI).
4. Append a dated entry to `progress.md` using its template, and mark items done
   **only after end-to-end verification**.
5. Development branch and push/PR rules are set per-session by the harness — do
   not push to `main`.

---

*Maintenance: this file describes structure and invariants, which change slowly.
Update it when a layer is added or removed, a landmine is fixed, or the debt
list changes — not for routine feature work (that goes in `progress.md`).*
