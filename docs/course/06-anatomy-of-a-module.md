# Lesson 06 — Anatomy of a module

**Goal:** read one complete module top to bottom, understand the shared
`radio_module.html` shell it renders into, and then build a brand-new module from
scratch. After this lesson the other ~30 radio modules are copy-paste variants.

Files: `modules/sleeping_cells/` (routes + logic), `modules/overshooting_detector/`,
`templates/radio_module.html`.

---

## 6.1 The standard module skeleton

A radio module is three files:

```
modules/<name>/
  __init__.py     # exports the blueprint (so app.py can import it)
  routes.py       # the Flask blueprint: one page route + one API route
  logic.py        # the detection function (calls the Lesson-05 engine)
```

`__init__.py` is usually one line:

```python
from .routes import sleeping_cells_bp
```

That's it. Everything interesting is `routes.py` (thin) + `logic.py` (the brain).

---

## 6.2 `sleeping_cells/routes.py` line by line

Open `modules/sleeping_cells/routes.py` (70 lines). Here it is in full, annotated.

```python
from flask import Blueprint, jsonify, render_template, request
from core.radio.scoring import filter_rows, summarize                 # Lesson 05
from core.radio.web import (admin_required, format_user,              # Lesson 03
    get_current_user, json_error, query_filters)
from .logic import (DEFAULT_BASELINE_DAYS, DEFAULT_MIN_BASELINE,
    DEFAULT_RECENT_DAYS, detect_sleeping_cells)                       # this module's brain

sleeping_cells_bp = Blueprint("sleeping_cells", __name__)             # the blueprint object
```

### The page route (renders HTML)

```python
@sleeping_cells_bp.route("/sleeping-cells")
@admin_required                                     # only admins (Lesson 03)
def sleeping_cells_page():
    return render_template(
        "radio_module.html",                        # the SHARED shell, not a local template
        user=format_user(get_current_user()),
        module_title="Sleeping Cell Detector",
        module_subtitle="Cells Active in CM but no longer carrying traffic...",
        module_kind="sleeping-cells",
        api_url="/api/sleeping-cells/issues",       # ← where the page fetches its data
        default_technology="all",
    )
```

The page route renders **`templates/radio_module.html`** — the shared shell (next
section). It doesn't build a table itself; it hands the shell a title, a subtitle,
and crucially an **`api_url`**. The shell's JavaScript will call that URL to get
the data. So the page route is pure configuration.

### The API route (returns JSON)

```python
@sleeping_cells_bp.route("/api/sleeping-cells/issues")
@admin_required
def sleeping_cells_issues():
    f = query_filters()                             # parse ?area&vendor&technology&severity&q&limit
    try:
        payload = detect_sleeping_cells(            # ← the module's actual work (logic.py)
            vendor=f["vendor"], technology=f["technology"], limit=f["limit"],
            recent_days=_int_arg("recent_days", DEFAULT_RECENT_DAYS),
            baseline_days=_int_arg("baseline_days", DEFAULT_BASELINE_DAYS),
            min_baseline=_float_arg("min_baseline", DEFAULT_MIN_BASELINE),
        )
        rows = filter_rows(payload.get("issues") or [],   # standard filter+sort (Lesson 05)
            area=f["area"], severity=f["severity"], search=f["search"])
        return jsonify({"success": True, **payload,
            "summary": summarize(rows), "issues": rows})  # standard response shape
    except Exception as exc:
        return json_error(exc)                            # uniform error shape (Lesson 03)
```

Notice how little there is: parse filters → call `logic`, → `filter_rows` →
`summarize` → return `{success, issues, summary}`. **Every** optimization module's
API route is this same five-line dance. The only module-specific line is the call
into `logic.py`. `_int_arg`/`_float_arg` are tiny local helpers for the extra
tuning knobs this particular detector exposes.

---

## 6.3 What `logic.py` does

`modules/sleeping_cells/logic.py` implements `detect_sleeping_cells`. Its docstring
says it best: a "sleeping" cell is **Active in CM** (per metadata) but its recent
daily traffic **collapsed to ~zero** versus its own baseline — a silent outage.

It reuses the Lesson-04/05 engine directly:

```python
from core.radio import metadata, pm
from core.radio.scoring import bounded_score, issue, summarize, utc_now_iso
from modules.son_analytics.pm_helpers import (
    _cell_daily_kpi_series, resolve_kpi_column, vendor_pm_sources)

TRAFFIC_ALIASES = list(pm.KPI_RECIPES["traffic"]["aliases"])   # reuse the traffic concept
```

The logic: for each vendor PM source, resolve the traffic column, pull each cell's
daily series, compute a baseline average vs recent average, and if recent is below
a tiny fraction of baseline (`QUIET_RATIO = 0.02`) while baseline was meaningful
(`min_baseline`), emit an `issue(...)`. It cross-checks metadata so only cells that
are *supposed* to be on-air get flagged. The tuning constants at the top
(`DEFAULT_RECENT_DAYS`, `QUIET_RATIO`, `QUIET_ABS_FLOOR`) are exactly the knobs the
route exposes as query params.

**This is the whole trick of the codebase:** the module contributes a *detection
rule*; the shared engine contributes everything else (PM reads, benchmarking,
scoring, response shape, filters, auth, the UI shell).

### The even-thinner variant

Some modules don't even have a `logic.py` — their detector already lives in
`core/radio/insights.py`. `modules/overshooting_detector/routes.py` (36 lines) is
the minimal case:

```python
from core.radio.insights import overshooting_candidates
...
payload = overshooting_candidates(vendor=f["vendor"], technology=f["technology"],
                                  area=f["area"], limit=f["limit"])
rows = filter_rows(payload.get("issues") or [], severity=f["severity"], search=f["search"])
return jsonify({"success": True, **payload, "summary": summarize(rows), "issues": rows})
```

`capacity_hotspots`, `layer_coverage`, `neighbor_quality`, `rf_optimization`,
`change_impact`, `radio_morning_report` are all this same 36-line shape — only the
imported detector and the titles differ.

---

## 6.4 The shared shell — `templates/radio_module.html`

Every radio page renders this one template. It provides:
- the PrimeNet header + back-to-dashboard link,
- the **filter bar** (area / vendor / technology / severity / search) — the exact
  fields `query_filters()` parses on the server,
- a summary chip row (fed by `summary`),
- a results table/cards area,
- the JavaScript that, on load and on filter change, `fetch()`es the `api_url`
  passed by the page route and renders `issues` into the table.

This is why modules have no template of their own: the shell + the standard
response contract (`{success, issues, summary}`) mean the same JS renders every
module. The page route just parameterizes the shell (`module_title`, `api_url`,
`default_technology`, `module_kind`). `module_kind` lets the shell/CSS tweak
per-module styling where needed.

The visual styling comes from `static/css/radio_modules.css` (shared) — Lesson 10.

---

## 6.5 Build a new module (hands-on)

Let's add a **"Zombie Cells"** module: cells carrying traffic but with zero
successful setups (made-up example; wiring is what matters).

**1. Create the folder + files:**

```
modules/zombie_cells/__init__.py
modules/zombie_cells/routes.py
modules/zombie_cells/logic.py
```

**2. `__init__.py`:**
```python
from .routes import zombie_cells_bp
```

**3. `logic.py`** — reuse the engine:
```python
from core.radio.scoring import issue, summarize
from modules.son_analytics.pm_helpers import (
    _cell_daily_kpi_series, resolve_kpi_column, vendor_pm_sources)
from core.radio import pm

def detect_zombie_cells(*, vendor="all", technology="4G", limit=200):
    issues = []
    traffic_aliases = pm.KPI_RECIPES["traffic"]["aliases"]
    for vlabel, db_path, table in vendor_pm_sources(vendor, technology, scope="daily"):
        col = resolve_kpi_column(db_path, table, traffic_aliases)
        if not col:
            continue
        series_map = _cell_daily_kpi_series(db_path, table, col, lookback_days=7)
        for cell, series in series_map.items():
            if not series:
                continue
            latest = series[0][1]
            if latest > 0:   # <-- your real rule goes here
                issues.append(issue(
                    module="zombie_cells", category="traffic",
                    title=f"{cell} suspicious", summary="example",
                    score=60, cells=[cell], vendor=vlabel, technology=technology))
    return {"issues": issues[:limit]}
```

**4. `routes.py`** — copy the sleeping-cells shape:
```python
from flask import Blueprint, jsonify, render_template
from core.radio.scoring import filter_rows, summarize
from core.radio.web import admin_required, format_user, get_current_user, json_error, query_filters
from .logic import detect_zombie_cells

zombie_cells_bp = Blueprint("zombie_cells", __name__)

@zombie_cells_bp.route("/zombie-cells")
@admin_required
def zombie_cells_page():
    return render_template("radio_module.html",
        user=format_user(get_current_user()),
        module_title="Zombie Cell Detector", module_subtitle="Example.",
        module_kind="zombie-cells", api_url="/api/zombie-cells/issues",
        default_technology="4G")

@zombie_cells_bp.route("/api/zombie-cells/issues")
@admin_required
def zombie_cells_issues():
    f = query_filters()
    try:
        payload = detect_zombie_cells(vendor=f["vendor"], technology=f["technology"], limit=f["limit"])
        rows = filter_rows(payload.get("issues") or [], area=f["area"], severity=f["severity"], search=f["search"])
        return jsonify({"success": True, **payload, "summary": summarize(rows), "issues": rows})
    except Exception as exc:
        return json_error(exc)
```

**5. Register it in `app.py`** (the step everyone forgets):
```python
from modules.zombie_cells.routes import zombie_cells_bp   # with the other imports
app.register_blueprint(zombie_cells_bp)                    # with the other registrations
```

**6. Add it to the menu** in `core/module_access.py` `NAV_SECTIONS` (else it
works by URL but isn't linked, and — depending on visibility — may be blocked):
```python
{"label": "Zombie Cell Detector", "href": "/zombie-cells", "visibility": "admin"},
```

Restart, log in as admin, open `/zombie-cells`. You just built a module without
writing a single line of HTML, auth, PM-reading, or filtering code — the shared
layers gave you all of it.

---

## Recap

- A radio module = `__init__.py` + `routes.py` (page route renders
  `radio_module.html`, API route returns `{success, issues, summary}`) +
  `logic.py` (the detection rule).
- The page route is configuration; the API route is a five-line dance around a
  `logic` call; the detection rule is the only truly module-specific code.
- Building a new one is copy the shape, write the rule, register in `app.py`, add
  to `NAV_SECTIONS`.

**Next:** [Lesson 07 — Module reference](07-module-reference.md): every module in
the app, grouped, with its real endpoints.
