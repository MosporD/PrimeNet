# PrimeNet — Architecture & Onboarding Guide

A developer's map of the codebase: what each layer does, how a request flows
through it, how the data model works, and the conventions to follow when adding
code. Read this once and every module reads the same way.

> Companion docs: `AGENTS.md` (short conventions), `progress.md` (current work +
> `NEXT` pointer), `checklist.md` (active scope). Vendor references live under
> `docs/*_CM_OPEN_API_*.md` and `docs/FRONTEND_THEME.md`.

---

## 1. What PrimeNet is

A **Flask** web platform for radio-access-network (RAN) engineers. It ingests
**performance (PM)** and **configuration (CM)** data from live telecom networks
— vendors **Nokia** and **Huawei**, radio technologies **2G through 5G** —
stores it in **SQLite**, and exposes ~40 analysis tools (dashboards,
optimization detectors, config extractors) behind a login.

Entry point: `app.py`.

---

## 2. The four layers

```
app.py                    ← app shell: registers blueprints, request hooks, security
├─ routes/                ← shared infra: auth, activation (NOT feature modules)
├─ core/                  ← business logic, reused by many modules (no HTTP here)
│   ├─ radio/             ← shared engine for the optimization modules
│   ├─ cm_extractor/      ← Nokia/Huawei live config extraction clients
│   └─ huawei_pm/, ...    ← activation gate, licensing, elevation, pm health
├─ modules/<name>/        ← ~40 feature modules, one Flask blueprint each
├─ pipeline/              ← ETL: pull raw PM files → load into SQLite
├─ db/ + sync_config.py   ← DB connections + all filesystem paths
└─ templates/ + static/   ← shared UI shell (dashboard, radio_module, CSS/JS)
```

**The golden rule of the layout:** `modules/` is HTTP + presentation, `core/` is
logic. A module's `routes.py` parses the request, calls into `core/` (or a local
`logic.py`), and JSON-ifies the result. Anything more than one module needs
lives in `core/` so it isn't duplicated.

---

## 3. `app.py` — the shell (read this file first, top to bottom)

| Lines | What it does |
|---|---|
| 14–24 | Load `.env`, then `install_sqlite_gate()` **before any DB import** (see §5). |
| 36–115 | Import + register every module blueprint. This is the master index of the app. |
| 128–136 | Error handlers (413 too-large, 500). |
| 211–236 | `/health` + `/api/health` — 503 while locked, else pings the DB. |
| 242–400 | The `@app.before_request` hook stack (runs on **every** request). |
| 403–422 | `set_security_headers` — CSP, `X-Frame-Options`, etc. |
| 424–455 | Dev server entry (`ConciseRequestHandler` strips query strings from logs). |

**The `before_request` stack, in order:**

1. `enforce_monthly_operator_activation` — if not activated, redirect to
   `/activation` (or 403 for `/api/*`). Allowlist: `/health`, `/activation`,
   activation APIs.
2. `validate_and_sanitize_request_input` — rejects malformed/oversized
   JSON/form/query input; stashes sanitized copies on `flask.g`
   (`g.sanitized_json`, `g.sanitized_form`, `g.sanitized_args`). CM-extractor
   APIs get a larger 8 MB / 100k-item budget because config payloads are huge.
3. `enforce_csrf_origin_for_cookie_auth` — same-origin check on
   POST/PUT/PATCH/DELETE when a `session_token` cookie is present.
4. `enforce_password_rotation` — forces a password change when the user record
   demands it.

> **#1 "why is my route 404ing" bug:** you added a blueprint but forgot to
> `import` **and** `app.register_blueprint(...)` it in `app.py`.

---

## 4. The activation gate — the most unusual piece

`core/activation_gate.py` is a license/activation system that works by
**monkeypatching `sqlite3.connect`** (`install_sqlite_gate`, ~line 328). Once
installed, **every** SQLite connection anywhere in the app first checks
`is_activated()` and raises `ActivationRequired` if not. That is why:

- `app.py` installs it on line 24, before importing anything DB-related.
- `db/runtime.py` installs it again defensively (idempotent via
  `_SQLITE_GATE_INSTALLED`).

**Two modes** (set in `.env`):

- **Local** — a PBKDF2 password hash + an HMAC-signed expiry file
  `.ncm_activation_state` (default 180-day period). Configure with
  `python scripts/set_activation_password.py`.
- **Remote** — a separate license service holds the signing key
  (`core/license_client.py`), via `NCM_LICENSE_SERVER_URL`.

**For local dev, set `NCM_SKIP_ACTIVATION=1`** and the whole gate becomes a
no-op. That's the first env var you'll want.

---

## 5. Auth & access control

- **`routes/auth_routes.py`** (~621 lines) — login/logout/register, session
  cookies (`session_token`), login rate-limiting
  (`_login_rate_limit_remaining`), plus the dashboard's data APIs
  (`/api/dashboard/pm-health`, `/site-map`, `/global-search`, …). Users and
  sessions live in `database_enhanced.py` → `ncm_users.db`.
- **`core/module_access.py`** — the single source of truth for **who can see
  what**. `NAV_SECTIONS` is a declarative list of every dashboard link with a
  `visibility` of `all` / `admin` / `admin_or_noc`. It both renders the nav menu
  (filtered by role) *and* enforces access (`enforce_module_access`,
  `href_allowed_for_role`). Roles: `admin` (owner), `noc_sys`, regular users.
- **`core/radio/web.py`** — the decorators feature modules actually use:
  `@login_required`, `@admin_required`, plus `get_current_user`, `format_user`,
  and `query_filters()` (parses the standard
  `area/vendor/technology/severity/q/limit` filter set every radio module
  shares).

> **User shape gotcha:** a user is sometimes a `dict` and sometimes a positional
> tuple where `user[6]` is the role. Legacy DB rows are tuples. Helpers in
> `web.py` tolerate both — mirror that when you touch user objects.

---

## 6. The data model & database topology (core domain knowledge)

Everything is **SQLite files** in a strict taxonomy under `databases/`, and
**`sync_config.py` is the map of every path.** Never hardcode a DB path — import
the constant.

| Constant | File | Holds |
|---|---|---|
| `NCMUSERS_DB` | `admin/.../ncm_users.db` | users, sessions, roles |
| `METADATA_DB` | `metadata/.../metadata.db` | the **cell inventory** — every cell/site, vendor, RAT, location, activity status |
| `NOKIA_PM_DB` / `HUAWEI_PM_DB` | `cells/<vendor>/all/hourly/…` | hourly **performance counters/KPIs** per cell |
| `NOKIA_PM_DAILY_DB` / `HUAWEI_PM_DAILY_DB` | `.../daily/…` | daily-rollup PM |
| `NEIGHBOR_KPI_DB` | `neighbors/nokia/all/hourly/…` | neighbor relations + KPIs |
| `*_GROUPS_DB` | `groups/<vendor>/…` | cell groups |
| `KPI_HEADERS_DB` | `.../kpi_headers.db` | KPI header catalog |

**`db/runtime.py` is the only way to open these.** `connect_app()`,
`connect_metadata()`, `connect_nokia_pm()`, etc. all: require activation, open
with a 120s timeout, set `row_factory = Row`, enable **WAL journal mode** + a
**120s busy_timeout**. WAL matters because background sync writes while users
read; `execute_query()` retries 3× on "database is locked."

**The key JOIN pattern — `performance_meta_pm_conn(vendor)`:** opens
`metadata.db` and `ATTACH`es the PM database(s) so a single query can `JOIN`
cell inventory (metadata) against performance counters (PM).

- Single vendor → PM attached as alias `pm`.
- Both vendors → attached as `nokia_pm` + `huawei_pm`.

Nearly every analytics query uses this attach-and-join. (`db/runtime.py` also
has vestigial Postgres-shaped helpers like `adapt_placeholders()` hardcoded to
SQLite — leftovers; ignore them.)

---

## 7. The shared radio engine — `core/radio/`

The dozen "Radio Optimization" modules are **thin routes over `core/radio/`**:

| File | Responsibility |
|---|---|
| `metadata.py` | Cell-inventory queries (`list_areas`, cell lookups). |
| `pm.py` | `KPI_RECIPES`: named KPI concepts (`"traffic"`, `"users"`) → lists of **vendor-specific column aliases**. This is how one detector works across Nokia + Huawei, which name the same counter differently. |
| `scoring.py` | `filter_rows`, `summarize`, `bounded_score`, `issue()` — the common `{success, issues, summary}` response shape. |
| `web.py` | The decorators + `query_filters()` (see §5). |
| `neighbor.py` | Neighbor relations. |
| `insights.py` | Cross-KPI insights. |
| `cm_live.py`, `cm_store.py` | Live-CM read + caching. |

### Anatomy of a radio module (30 of ~40 modules follow this)

```
modules/<name>/
  routes.py     # blueprint: a page route (renders radio_module.html)
                #            + an /api/<name>/... route
  logic.py      # detection logic → calls core/radio + son_analytics.pm_helpers
  __init__.py   # exports the blueprint
```

The page route renders the **shared `templates/radio_module.html` shell**,
passing `module_title`, `api_url`, `default_technology`, etc. The template's JS
then calls the API URL with the standard filter query string, and
`core/radio/scoring` shapes the response. That's why these modules have almost
no template of their own — the shell + shared `radio_modules.css` do the work.

**Example** (`modules/sleeping_cells/routes.py`): the page route is a
`render_template("radio_module.html", ...)` call; the API route calls
`detect_sleeping_cells(...)` from `logic.py`, runs the result through
`filter_rows` + `summarize`, and returns `{success, issues, summary}`.

---

## 8. The other module families

- **CM (configuration) tooling** — `cm_extractor` (the big one; backed by
  `core/cm_extractor/` with real Nokia & Huawei network clients, bulk export,
  MML parsers, an export store, a job scheduler), `cm_parameter_audit`,
  `config_history`, `xml_parser`, `excel_generator`, `ne_comparison`,
  `ret_management` (remote electrical tilt), `network_management`. These talk to
  live network elements or parse vendor XML/MML.
- **Dictionaries / reference** — `parameter_dictionary` (its
  `huawei_params/` is ~19k scraped HTML files, **do-not-edit**, served
  read-only), `performance_dictionary`, `ran_features`.
- **Maps & visualization** — `network_map`, `cell_heatmap`, `conflict_map`,
  `drive_test_viewer`, `elevation` (uses `core/elevation.py`).
- **Reporting / monitoring** — `reports`, `radio_morning_report`,
  `fault_management`, `femto_pm` (femtocells), `performance` /
  `performance_analytics` (KPI explorer; own `kpi_catalog.py` + `kpi_mapping.py`).
- **Admin / ops** — `admin_panel`, `user_profile`, `sync` (drives the pipeline
  from the UI), `task_scheduler`.

---

## 9. The ETL pipeline

`pipeline/` pulls raw PM files off SFTP servers (Nokia PM, Huawei PM, metadata —
IPs documented at the top of `sync_config.py`) and loads them into the SQLite
files above. Structure mirrors the data taxonomy:

```
pipeline/pull/<vendor>/all/<daily|hourly>/pull_all.py
pipeline/load/<vendor>/all/<daily|hourly>/load_all.py
pipeline/orchestrators/orchestrate_{daily,hourly,watcher_cycle}.py
pipeline/paths.py     ← raw-file path taxonomy
```

Prefer the **orchestrators** over the loose legacy scripts. `scripts/` is a
large grab-bag of one-off build/backfill/probe utilities (building caches,
backfilling elevations, auditing DBs). Huawei daily exports stage in
`raw/huawei/{cells,groups}/all/daily` before the RAT split.

---

## 10. Frontend / UI shell

- `templates/dashboard.html` — the constellation deck (landing page).
- `templates/radio_module.html` — the shared shell for radio filter modules; do
  not hand-roll filter UI, reuse this.
- `templates/login.html`, `register.html`, `activation.html`.
- Global styles: `static/css/common.css`, `dashboard.css`, `constellation.css`,
  `radio_modules.css`. Constellation background:
  `static/js/constellation.js` + `constellation.css`.
- Bump cache-bust query strings (`?v=X.X`) only on files you actually change.
- Large templates (e.g. `dashboard.html`): edit targeted sections, avoid
  full-file rewrites.

See `docs/FRONTEND_THEME.md` for theme tokens.

---

## 11. Running it

**Local dev:**

```bash
cp .env.example .env
# set in .env:  NCM_SKIP_ACTIVATION=1  and  FLASK_DEBUG=1
python app.py
# → http://localhost:5000/dashboard
```

**Container:** `docker-compose.yml` (prod) / `docker-compose.dev.yml`;
entrypoint bootstraps via `deploy/`. Mount a volume at `NCM_DATA_ROOT` for
persistent `databases/`, `raw/`, `sync_downloads/`.

**Generated, never source:** `raw/`, `*.db`, `sync_downloads/`.

---

## 12. Conventions (from `AGENTS.md`)

1. New blueprint → register it in `app.py` (import + `register_blueprint`).
2. DB access **only** through `db/runtime.py` + `sync_config.py` constants —
   never a literal path or a raw `sqlite3.connect`.
3. Auth via the `@login_required` / `@admin_required` pattern in
   `core/radio/web.py`; session via the `session_token` cookie.
4. Radio modules render `radio_module.html`; reuse the shared filter shell.
5. Access rules go in `core/module_access.py`, nowhere else.
6. Do **not** edit `modules/parameter_dictionary/huawei_params/`, `raw/`,
   `*.db`, or `sync_downloads/`.
7. Module blueprints use `template_folder="templates"` and a module-local
   `static_folder` when needed.

**Session handoff:** read `progress.md` for current work + its `NEXT` pointer;
`checklist.md` defines the active scope.

---

## 13. Request lifecycle, end to end

```
Browser
  │  GET /sleeping-cells   (cookie: session_token)
  ▼
app.py before_request stack
  │  activation? sanitize input? CSRF? password rotation?
  ▼
Blueprint route (modules/sleeping_cells/routes.py)
  │  @admin_required  → core/radio/web.py checks session + role
  ▼
render_template("radio_module.html", api_url="/api/sleeping-cells/issues", ...)
  │
  ▼  (browser JS then calls the API with filter query string)
API route  →  logic.py: detect_sleeping_cells()
  │              ├─ core/radio/metadata.py   (cell inventory)
  │              ├─ core/radio/pm.py         (KPI recipes/aliases)
  │              └─ db/runtime.performance_meta_pm_conn()  (ATTACH + JOIN)
  ▼
core/radio/scoring.py: filter_rows() + summarize()
  ▼
JSON {success, issues, summary}  →  after_request security headers  →  Browser
```

---

## 14. Where to look first, by task

| I want to… | Start in |
|---|---|
| Add a new analysis module | copy a radio module (`sleeping_cells`), register in `app.py`, add a `NAV_SECTIONS` entry |
| Change who can see a page | `core/module_access.py` (`NAV_SECTIONS`) |
| Query PM data | `db/runtime.performance_meta_pm_conn()` + `core/radio/pm.py` recipes |
| Add a DB / path | `sync_config.py` constants |
| Touch login / sessions | `routes/auth_routes.py` + `database_enhanced.py` |
| Change the activation/license flow | `core/activation_gate.py` + `core/license_client.py` |
| Extract live config from a network element | `core/cm_extractor/` (nokia_client / huawei_client) |
| Change ingestion | `pipeline/orchestrators/` |
| Restyle the UI | `static/css/*.css`, `templates/radio_module.html`, `dashboard.html` |
