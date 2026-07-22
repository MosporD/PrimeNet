# Lesson 04 — The data model

**Goal:** understand where PrimeNet's data physically lives, how connections are
opened, the shape of PM/metadata data, and the two tricks that make cross-vendor
analytics possible: the **ATTACH+JOIN** and **KPI name resolution**.

Files: `sync_config.py`, `db/runtime.py`, `core/radio/pm.py`,
`modules/son_analytics/pm_helpers.py`.

---

## 4.1 Everything is SQLite files

PrimeNet has no Postgres/MySQL server. It's a set of **SQLite database files**
on disk under `databases/`, laid out in a strict taxonomy. `db/runtime.py:26`
literally hardcodes `is_postgresql() → False`; the Postgres-shaped helpers next
to it (`adapt_placeholders`, `quote_ident`) are vestigial. Treat it as
SQLite-only.

### `sync_config.py` is the map of every path

**Never hardcode a database path.** Import the constant. The key ones
(`sync_config.py:89`–110):

| Constant | Holds |
|---|---|
| `NCMUSERS_DB` | users, sessions, tasks (Lesson 03) |
| `METADATA_DB` | **the cell inventory** — every cell/site: vendor, RAT, location, activity status |
| `NOKIA_PM_DB` / `HUAWEI_PM_DB` | **hourly** performance counters per cell |
| `NOKIA_PM_DAILY_DB` / `HUAWEI_PM_DAILY_DB` | **daily** rollups (what the insight modules read) |
| `NEIGHBOR_KPI_DB`, `HUAWEI_NEIGHBOR_RAW_DB` | neighbor relations + KPIs |
| `NOKIA_GROUPS_DB` / `HUAWEI_GROUPS_DB` (+ daily) | cell groups |
| `KPI_HEADERS_DB` | catalog of KPI column names |

The folder taxonomy is `databases/<domain>/<vendor>/all/<hourly|daily>/file.db`,
e.g. `NOKIA_PM_DB = databases/cells/nokia/all/hourly/nokia_pm_cells.db`. The top
of `sync_config.py` also `os.makedirs(..., exist_ok=True)` for every folder on
import (lines 66–86), so paths always exist even on a fresh clone.

`DATA_ROOT` (line 40) lets you relocate all of this with `NCM_DATA_ROOT` — in
Docker you mount a volume there so the data survives container restarts.

---

## 4.2 Opening connections — `db/runtime.py`

**The only sanctioned way to open these DBs.** Every helper does the same three
things:

```python
def connect_metadata():
    require_activation()                          # 1. license gate (Lesson 02)
    conn = sqlite3.connect(METADATA_DB, timeout=120)
    return _configure_sqlite_conn(conn)           # 2+3. row factory + WAL + busy timeout
```

`_configure_sqlite_conn` (line 68) sets:
- `row_factory = sqlite3.Row` → rows are dict-like (`row["cell_name"]`), not
  bare tuples.
- `PRAGMA journal_mode=WAL` → **W**rite-**A**head **L**ogging lets readers keep
  reading while the pipeline writes. Critical here because sync writes while
  users browse.
- `PRAGMA busy_timeout=120000` → wait up to 120 s for a lock instead of failing
  instantly.

And `execute_query` (line 50) retries 3× on "database is locked." Together these
make the app resilient to the background pipeline hammering the same files.

Helpers: `connect_app()`, `connect_metadata()`, `connect_nokia_pm()`,
`connect_huawei_pm()`, and the generic `connect_pm_db(path)`.

---

## 4.3 The single most important query trick: ATTACH + JOIN

Here's the core problem. **Cell inventory** (name, location, vendor, RAT, is-it-
active) lives in `metadata.db`. **Performance** (traffic, drops, throughput)
lives in a *separate* file, `nokia_pm_cells.db` or `huawei_pm_cells.db`. To ask
"show me active 4G cells whose traffic collapsed," you need to join across two
files.

SQLite can do this with `ATTACH DATABASE`. `performance_meta_pm_conn(vendor)`
(`db/runtime.py:121`) sets it up:

```python
conn = sqlite3.connect(METADATA_DB, timeout=120)      # base = metadata
if vendor == 'Nokia':
    conn.execute(f"ATTACH DATABASE '{NOKIA_PM_DB}' AS pm")
    return conn, 'pm'
if vendor == 'Huawei':
    conn.execute(f"ATTACH DATABASE '{HUAWEI_PM_DB}' AS pm")
    return conn, 'pm'
# both vendors:
conn.execute(f"ATTACH DATABASE '{NOKIA_PM_DB}'  AS nokia_pm")
conn.execute(f"ATTACH DATABASE '{HUAWEI_PM_DB}' AS huawei_pm")
return conn, None
```

Now a single query can reference `metadata` tables **and** `pm.<table>` in one
`JOIN`. Single-vendor → the PM file is attached under the alias `pm`; both
vendors → two aliases `nokia_pm` / `huawei_pm`, and the caller unions them. This
attach-and-join is the backbone of nearly every analytics query in the app.

---

## 4.4 The shape of PM data (and why it's messy)

PM tables are **wide and vendor-specific**. A row is roughly:

```
<cell identifier column> | <timestamp column> | KPI_1 | KPI_2 | ... | KPI_n
```

But nothing about the column names is standardized:

- The **cell column** might be `LNCEL name` (Nokia 4G), `NRCEL name` (Nokia 5G),
  `WCEL name` (3G), `Cell Name` / `Cell CI` (Huawei), etc. See
  `_CELL_COL_CANDIDATES` in `son_analytics/pm_helpers.py:20`.
- The **timestamp column** might be `PERIOD_START_TIME`, `Date`, `timestamp`…
  (`_TS_COL_CANDIDATES`, line 30).
- Timestamps come in different formats — Huawei uses **day-first** `DD/MM/YYYY`,
  others `YYYY-MM-DD`. `parse_pm_timestamp` (line 349) tries day-first before
  US month-first to avoid mixing up the 5th and the month.
- KPI *values* can carry units or commas (`"1,234"`, `"55 m"`, `"90%"`).
  `_to_float` (line 156) strips them with a regex before parsing.

Because of this, PM code never assumes column names. It calls
`PRAGMA table_info(...)` to list actual columns, then finds the ones it needs by
matching against candidate lists (`_find_col`, line 178). This "discover the
schema at runtime" style is everywhere in `pm_helpers.py` — now you know why.

Which PM table? `pm_table_name(technology)` (in `sync_config.py`) maps a RAT to a
table like `..._HOURLY`, and `pm_table_name_for_scope` swaps `_HOURLY`→`_DAILY`.
4G-FDD and 4G-TDD share one 4G table; metadata tells the two apart.

---

## 4.5 KPI name resolution: one concept, many vendor names

The second big trick. Nokia and Huawei name the *same* KPI differently. So the
code works in terms of **concepts** ("traffic", "utilization") that each map to a
list of possible real column names — **aliases**.

`core/radio/pm.py:13` — `KPI_RECIPES`:

```python
KPI_RECIPES = {
  "utilization": {"direction": "higher_worse",
      "aliases": ["DL PRB Usage Rate(%)", "E-UTRAN Avg PRB usage per TTI DL", "PRB util PDSCH", "PRB", "Utilization"]},
  "throughput":  {"direction": "lower_worse",
      "aliases": ["User Throughput", "Average Throughput", "DL Throughput", "Cell Throughput"]},
  "traffic":     {"direction": "higher_worse", "aliases": [...]},
  ...
}
```

Two things per recipe:
- **`aliases`** — every name a vendor might use for this concept.
- **`direction`** — is a *higher* number worse (utilization, drops) or is a
  *lower* number worse (throughput, accessibility)? This drives whether "went
  up" counts as degradation. Remember it — it recurs in Lesson 05.

Resolving a concept to the real column in a given table is `resolve_kpi_column`
(`son_analytics/pm_helpers.py:195`), which tries three increasingly fuzzy passes:

1. exact case-insensitive match,
2. **normalized** match (strip everything non-alphanumeric, so
   `DL PRB Usage Rate(%)` == `dlprbusagerate`),
3. substring containment either way.

This is how one detector runs across both vendors and all RATs without a giant
hand-maintained mapping table. The `mobility` / `accessibility` / `retainability`
/ `interference` recipes even borrow their alias lists from
`network_health/config.py`'s `CATEGORY_PRESETS` (line 37) so the two modules
stay consistent.

---

## 4.6 Performance = caching, because PM tables are big

PM tables have millions of rows. Two techniques keep queries fast
(`son_analytics/pm_helpers.py`):

- **Rowid windowing** — `_rowid_scan_cutoff` (line 67). PM DBs are append-only,
  so recent data has the highest `rowid`s. Instead of scanning the whole table,
  queries add `WHERE rowid >= <cutoff>` to only touch roughly the last N days.
- **mtime-aware caching** — `_cache_get`/`_cache_set` (lines 52–64) cache results
  for an hour, but **invalidate automatically if the DB file's modification time
  changed** (i.e., the pipeline wrote new data). So you get cache speed without
  serving stale numbers after a sync.

You don't need to memorize these, but when you see `rowid >= ?` or a
`(expires_at, mtime, payload)` tuple, that's what's going on.

---

## 4.7 Quick reference: "I need to read PM data"

- One KPI's latest value per cell → `latest_kpi_values(db, table, col)`
  (`pm_helpers.py:228`).
- A cell's daily history → `_cell_daily_kpi_series(...)` (line 369).
- Which (db, table) do I read for vendor+tech? → `vendor_pm_sources(vendor,
  technology, scope)` (line 303) returns `[(vendor_label, db_path, table), ...]`
  and even falls back from an empty daily table to hourly.
- Concept → real column → `resolve_kpi_column(db, table, aliases)`.

You almost never open PM files yourself — you go through these helpers, and they
handle vendor/RAT/scope/column discovery for you.

---

## Recap

- Data = SQLite files under `databases/`; `sync_config.py` names every path;
  `db/runtime.py` is the only opener (with WAL + busy-timeout for concurrency).
- `performance_meta_pm_conn` ATTACHes PM onto metadata so one query can JOIN
  inventory against counters — single-vendor alias `pm`, both-vendor
  `nokia_pm`/`huawei_pm`.
- PM tables are wide and non-standardized; code discovers cell/timestamp/KPI
  columns at runtime and normalizes messy values.
- KPI concepts map to alias lists (`KPI_RECIPES`) with a `direction`;
  `resolve_kpi_column` finds the real column across vendors.

**Next:** [Lesson 05 — The shared radio engine](05-radio-engine.md), where these
reads become "this cell is degraded."
