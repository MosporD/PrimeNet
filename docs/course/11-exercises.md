# Lesson 11 — Exercises & capstone

**Goal:** cement the course with small, real changes against this repo. Each
exercise names the lessons it exercises and the files you'll touch. Do them in
order; they build up.

> Work on a branch, keep `NCM_SKIP_ACTIVATION=1` for local runs, and verify in
> the browser at `http://localhost:5000` after each one.

---

## Warm-ups (reading, no code)

**E0.1 — Trace a request.** Pick `GET /overshooting-detector/issues`. Starting at
`app.py`, list every function that runs before the JSON is returned (gates → the
view → the detector → scoring). Check yourself against Lesson 01.3 + Lesson 06.
*(Lessons 01, 03, 05, 06)*

**E0.2 — Find the DB.** Without grepping, predict which SQLite file
`detect_sleeping_cells` reads for Nokia 4G daily data, then confirm by following
`vendor_pm_sources` → `sync_config.py`. *(Lesson 04)*

**E0.3 — Map a module you haven't opened.** Run
`grep -nE "\.route\(" modules/fault_management/routes.py`, read the page route +
one API route, and write one sentence on what it does. *(Lesson 07)*

---

## Tier 1 — One-line/one-block changes

**E1.1 — Add a KPI alias.** A Huawei 4G throughput column isn't being found. Add a
plausible alias to `KPI_RECIPES["throughput"]["aliases"]` in `core/radio/pm.py`
and explain why the 3-pass `resolve_kpi_column` (Lesson 04.5) would now match it.
*(Lesson 04)*

**E1.2 — Tune a detector.** In `modules/sleeping_cells/logic.py`, change
`QUIET_RATIO` from `0.02` to `0.05` and predict whether the detector flags *more*
or *fewer* cells. Reason about it, then (if you have data) verify on the page.
*(Lessons 05, 06)*

**E1.3 — Change a severity threshold.** In `core/radio/scoring.py`,
`severity_from_score` labels ≥85 as Critical. Change it to ≥90 and describe which
issues across the *whole app* would drop from Critical to High — and why this one
edit affects every optimization module. *(Lesson 05)*

**E1.4 — Restyle via shared CSS.** Find a duplicated inline style in two module
templates and move it into a shared class in `static/css/radio_modules.css` or
`common.css`. Bump only those files' `?v=` tokens. *(Lesson 10, `checklist.md`)*

---

## Tier 2 — Small features

**E2.1 — Add a filter param.** Give the sleeping-cells API a `min_traffic` query
param (like the existing `recent_days`). Add an `_int_arg`/`_float_arg` read in
`routes.py`, thread it into `detect_sleeping_cells`, and use it in the rule.
*(Lessons 03, 06)*

**E2.2 — Add a dashboard widget field.** Extend one `/api/dashboard/...` response
in `routes/auth_routes.py` with an extra computed field and surface it in
`dashboard.html`. Watch the JOIN-against-metadata pattern. *(Lessons 03, 04, 10)*

**E2.3 — Add access control.** Take an existing `all`-visibility module and make
it `admin`-only by editing its `NAV_SECTIONS` entry in `core/module_access.py`.
Verify a non-admin both loses the menu link *and* gets 403/redirect on the URL —
proving the "one table, two jobs" design. *(Lesson 03)*

**E2.4 — Write a test.** `modules/ret_management/` and
`core/cm_extractor/` ship `test_*.py`. Add one test case to an existing test file
for a helper you understand. Run it. *(Lessons 07, 08)*

---

## Tier 3 — Capstone: build a module end to end

**E3 — "Traffic Spike Detector."** Build a full optimization module that flags
cells whose latest daily traffic is *far above* their baseline (the mirror image
of sleeping cells).

Steps (all from Lesson 06):

1. `modules/traffic_spikes/__init__.py` — export the blueprint.
2. `modules/traffic_spikes/logic.py` — `detect_traffic_spikes(...)`:
   - use `vendor_pm_sources` + `resolve_kpi_column` with
     `pm.KPI_RECIPES["traffic"]["aliases"]`,
   - pull `_cell_daily_kpi_series`,
   - reuse `benchmark_cell_change(series, direction="higher_worse")` from
     `son_analytics/pm_helpers.py` and keep cells where `change_pct` exceeds a
     threshold you choose,
   - emit `issue(...)` objects with a score derived from `change_pct`
     (`bounded_score`).
3. `modules/traffic_spikes/routes.py` — copy the sleeping-cells shape: page route
   renders `radio_module.html` with a new `api_url`; API route does
   `query_filters` → `detect_traffic_spikes` → `filter_rows` → `summarize` →
   `{success, issues, summary}`.
4. Register the blueprint in `app.py` (import + `register_blueprint`).
5. Add a `NAV_SECTIONS` entry in `core/module_access.py` (e.g. under "Radio
   Optimization", `admin`).
6. Run, log in as admin, open `/traffic-spikes`, exercise the filters.

**Definition of done:** the page loads through the shared shell, the filter bar
works, severities sort worst-first, and you wrote **zero** HTML, auth, PM-reading,
or filtering plumbing — only a detection rule. If you hit that, you've understood
the whole architecture.

**Stretch:** add a unit test for `detect_traffic_spikes` using a tiny in-memory
series; add a tuning query param; make the score scale smoothly with `change_pct`.

---

## Where to go after the course

- **Deepen a heavy module:** pick one of `cm_extractor` / `performance` /
  `network_map` / `sync` (Lesson 08) and read it with its tests/CLI.
- **Follow the data backward:** run an orchestrator dry (Lesson 09) and watch a
  file go raw → parsed → SQLite.
- **Keep the docs alive:** when you learn something the course got thin on,
  add it here or to `docs/ARCHITECTURE.md`. The next person (or the next you)
  will thank you.

---

## Recap of the whole course

1. Flask shell + request pipeline (`app.py`) — L01
2. License gate via `sqlite3.connect` monkeypatch + security hooks — L02
3. Users/sessions/roles; `NAV_SECTIONS` as the one access source — L03
4. SQLite topology; ATTACH+JOIN; KPI alias resolution — L04
5. The benchmark engine: today-vs-baseline → scored issues — L05
6. Module anatomy: thin routes over the shared engine — L06
7. All 40 modules, grouped — L07
8. The four heavy subsystems — L08
9. The ETL pipeline that feeds the DBs — L09
10. Shared templates, CSS, and the theme system — L10

The spine is L01→L06. Everything else is that spine with a vendor SDK, a big UI,
or a data source attached. You know the tool now — go build.
