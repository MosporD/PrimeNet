# Lesson 05 — The shared radio engine

**Goal:** understand the reusable brain behind ~12 optimization modules: how raw
PM series become "this cell degraded," how issues are scored into severities, and
how a response is shaped. Once you get this, those modules are 30-line wrappers.

Files: `modules/son_analytics/pm_helpers.py`, `core/radio/pm.py`,
`core/radio/scoring.py`, `core/radio/insights.py`, `modules/network_health/`.

---

## 5.1 The core question: "is this cell worse than usual?"

Almost every optimization module answers a variant of the same question:
*compared to its own recent history, has this cell's KPI gotten meaningfully
worse?* The single function that answers it is `_benchmark_from_series`
(`son_analytics/pm_helpers.py:488`). Read it carefully — it's the analytical
heart of the app.

Input: a cell's daily series, **newest first**: `[(day, value), ...]`.

```python
latest_day, latest_val = series[0]            # today
history = [val for _, val in series[1:]]      # the prior days
week_avg = sum(history) / len(history)        # baseline = average of prior days
raw_delta = latest_val - week_avg             # how far today is from baseline
change_pct = (raw_delta / max(abs(week_avg), 0.01)) * 100.0
```

Then it decides "degraded" **using the KPI's direction** (Lesson 04):

```python
if direction == "higher_worse":               # e.g. utilization, call drops
    severity_delta = raw_delta                 # worse = went UP
    degraded = severity_delta >= min_absolute_delta and change_pct >= degradation_pct
else:                                          # "lower_worse": throughput, accessibility
    severity_delta = week_avg - latest_val     # worse = went DOWN
    degraded = severity_delta >= min_absolute_delta and change_pct >= degradation_pct
```

So "degraded" requires **both**:
- a big enough absolute move (`min_absolute_delta`, default 0.5), **and**
- a big enough relative move (`degradation_pct`, default 5%).

Requiring both prevents two classic false positives: tiny wiggles that are
huge in percent (a KPI going 0.01→0.03 is +200% but meaningless), and large
absolute moves that are trivial in context. There are special cases for
near-zero baselines and near-100% baselines (lines 518–527) so percentages stay
sane at the extremes.

Output is a dict: `today_value`, `week_avg`, `delta`, `change_pct`,
`change_direction` ("increased"/"decreased"/"no_change"), `degraded` (bool), and
the `daily_series` for sparklines.

Three thin wrappers select how much of that you want:
- `benchmark_cell_vs_week` (line 543) → returns a row **only if degraded**
  (used by "show me the problems" views).
- `benchmark_cell_change` (line 569) → returns the comparison for **any** cell
  with enough history (used by "show me all cells and their trend" views).

---

## 5.2 Scanning many cells efficiently

Running that benchmark for every cell means reading a lot of PM data. The engine
has two collection entry points:

- `collect_degraded_cells(category_presets, ...)` (line 589) — loops over KPI
  categories, resolves each to a real column per vendor source, pulls each cell's
  daily series, benchmarks, and keeps only degraded ones. Returns a flat list of
  degraded-cell dicts tagged with `category`, `vendor`, `technology`.
- `collect_all_kpi_benchmarks(kpi_columns, ...)` (line 762) — the **bulk** path.
  `_scan_all_kpi_daily_series` (line 700) reads *all* requested KPI columns in a
  **single table scan** and builds `{kpi: {cell: [(day, value)...]}}`, then
  benchmarks everything. One pass over the table instead of one pass per KPI —
  much faster when a page needs many KPIs at once. Results are cached with the
  mtime-aware cache from Lesson 04.

`core/radio/pm.py` sits on top with friendlier names: `degraded_cells(vendor,
technology, limit)` (line 105) just calls `collect_degraded_cells` with the
Network-Health tuning constants (`WOW_LOOKBACK_DAYS`, `WOW_DEGRADATION_PCT`, …
from `network_health/config.py`) and sorts by magnitude of change. "WoW" =
week-over-week.

---

## 5.3 Turning findings into scored issues — `core/radio/scoring.py`

Detection gives you facts ("traffic down 40%"). The UI needs **ranked,
severity-tagged issues** with a stable identity. That's `scoring.py` (148 lines),
and every module produces the same object shape via `issue(...)` (line 69):

```python
issue(module=..., category=..., title=..., summary=..., score=0-100,
      cells=[...], site_id=..., area=..., vendor=..., technology=...,
      evidence={...}, recommendation=..., source_url=...)
```

Key mechanics:

- **Score → severity.** `severity_from_score` (line 44): ≥85 Critical, ≥70 High,
  ≥45 Medium, >0 Low, else Info. Modules compute a 0–100 score; the label is
  derived, so severity is consistent across the whole app.
- **Stable IDs.** `stable_id(...)` (line 18) hashes the identifying parts
  (module, category, title, site, cells) into a 16-char id, so the *same*
  problem gets the *same* id across refreshes — the frontend can dedupe and
  track it.
- **`bounded_score(*values)`** (line 60) sums positive contributions and clamps
  to 100 — modules add up several evidence signals into one score.
- **`to_float`** (line 23) — the same unit/percent-tolerant parser you saw in PM
  helpers, for turning display strings back into numbers.

Then two functions finish every API response:

- `filter_rows(rows, area, vendor, technology, severity, search)` (line 105) —
  applies the standard filter set (from `query_filters`, Lesson 03) **and sorts**
  by severity, then score, then title. This is why results always come back
  worst-first.
- `summarize(rows)` (line 136) — returns `{total, by_severity, by_module}` for
  the summary chips at the top of each page.

**So the universal response shape is:** `{success, issues: [...], summary: {...}}`.
Learn it once; every optimization API returns it.

---

## 5.4 `core/radio/insights.py` — the heuristic detectors

Where `pm_helpers` is generic benchmarking, `insights.py` holds the
*domain-specific* detectors that combine multiple signals. For example
`overshooting_candidates(...)` (used by the Overshooting Detector) blends
long-neighbor evidence, distance, and handover data into `issue(...)` objects.
Other radio modules import their detector from here or from a local `logic.py`.
The pattern is always: gather PM/metadata signals → compute a 0–100 score →
`issue(...)`.

`core/radio/metadata.py` provides the inventory-side helpers these detectors
need (`list_areas()` for the area dropdown, cell lookups), and
`core/radio/neighbor.py` provides neighbor-relation reads.

---

## 5.5 Network Health: the precompute variant

`modules/network_health/` is worth a special look because it does the *opposite*
of on-demand scanning. Its `config.py` (Lesson 04 referenced its presets)
declares that a **cron job precomputes** KPI benchmarks into a SQLite store, and
the web page just reads that store — no PM scan on page load:

- `precalc_job.py` / `precalc_store.py` — build and read the precomputed table.
- `logic.py:get_precomputed_table` (line 167) — the fast read path;
  `_compute_precomputed_table_runtime` (line 218) is the fallback that scans live
  if the store is missing and `NH_PRECALC_RUNTIME_BUILD` is enabled.
- `list_kpi_columns(vendor, rat)` (line 288) and `get_kpi_cells(...)` (line 382)
  are what `core/radio/pm.py` calls to enumerate/rank KPIs.

This precompute pattern is the answer to "how do we show a whole-network
scorecard without a 30-second query." Other heavy pages (femto, cell-heatmap)
use similar caches. When you see a `precalc`/`precompute` file, that's the trade:
freshness (updated on a schedule) for instant page loads.

---

## 5.6 The end-to-end data flow (memorize this diagram)

```
vendor_pm_sources()        → which (db, table) for this vendor+RAT+scope
   └─ resolve_kpi_column() → concept alias → real column name
        └─ _cell_daily_kpi_series() / _scan_all_kpi_daily_series()
                            → {cell: [(day, value)...]}  (rowid-windowed, cached)
             └─ _benchmark_from_series(direction=...)
                            → today vs baseline → degraded?  change_pct?
                  └─ issue(score=...) → severity label + stable id
                       └─ filter_rows() + summarize()
                            → {success, issues, summary}  → JSON → page
```

Every optimization module is just a specific detector plugged into this pipeline.

---

## Recap

- `_benchmark_from_series` compares today vs a prior-days baseline, using the
  KPI's `direction`, and flags "degraded" only when the move is big both in
  absolute and percent terms.
- `collect_degraded_cells` / `collect_all_kpi_benchmarks` scan cells (the latter
  in one bulk pass, cached) using the Lesson-04 PM helpers.
- `scoring.py` turns findings into uniform `issue()` objects with derived
  severity and stable ids, then `filter_rows` + `summarize` finish the standard
  `{success, issues, summary}` response.
- Network Health shows the precompute alternative: a cron builds a store, the
  page just reads it.

**Next:** [Lesson 06 — Anatomy of a module](06-anatomy-of-a-module.md) — we build
one on top of this engine.
