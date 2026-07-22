# Lesson 09 — The ETL pipeline

**Goal:** understand how raw vendor files on remote servers become the SQLite
rows every module reads. This is the "where does the data come from" answer.

Files: `pipeline/paths.py`, `pipeline/orchestrators/*`, `pipeline/pull/*`,
`pipeline/load/*`, and the sibling `sync/` processors (Lesson 08.4).

ETL = **E**xtract (pull raw files) → **T**ransform (parse) → **L**oad (into
SQLite).

---

## 9.1 The three data sources

From the top of `sync_config.py`:

```
Server 1A — Nokia PM    (10.119.219.77)
Server 1B — Huawei PM   (10.119.10.104)
Server 2  — Metadata    (192.168.7.207)
```

The pipeline connects to these over SFTP, downloads exported files, and loads
them. (On a fresh dev clone with no network access to these servers, the DBs stay
empty — that's why analytics pages render but show no rows.)

---

## 9.2 The folder taxonomy — `pipeline/paths.py`

Raw files and databases share a **parallel folder structure**, and
`pipeline/paths.py` is the authority on it:

```
raw/{vendor}/{domain}/{2g|3g|4g|5g}/{timeframe}/     ← downloaded files, one RAT per folder
databases/{domain}/{vendor}/{technology}/{timeframe}/ ← loaded SQLite (matches sync_config.py)
```

- `VENDORS = ("nokia", "huawei", "metadata")`
- `DOMAINS = ("cells", "groups", "neighbors", "metadata", "admin")`
- `PM_RATS = ("2g", "3g", "4g", "5g")`
- `TIMEFRAMES = ("hourly", "daily", "snapshot")`

Helpers: `raw_path(vendor, domain, tech, timeframe)` and `db_path(...)` build
paths from those pieces; `ensure_taxonomy_dirs()` creates the whole tree.
**Rule:** compute pipeline paths through these helpers, don't string-concat your
own — the same way you use `sync_config.py` constants for DB files.

> Huawei daily exports are the one exception: they stage in
> `raw/huawei/{cells,groups}/all/daily` *before* being split by RAT
> (`AGENTS.md` watch-out). The `all` folder is legacy/staging only.

---

## 9.3 The orchestrators — the entry points

`pipeline/orchestrators/` has the top-level jobs you actually run:

- `orchestrate_daily_full.py` — the daily ETL.
- `orchestrate_hourly_full.py` — the hourly ETL.
- `orchestrate_watcher_cycle.py` — a watcher that reacts to new files.

Read `orchestrate_daily_full.py` — it's short and shows the whole shape:

```python
def main() -> int:
    ensure_taxonomy_dirs()
    pull_rc = _run("pipeline/pull/daily/pull_all.py")     # 1. PULL everything
    if pull_rc not in (0, 2):                             #    (2 = partial: some vendor failed)
        return pull_rc
    load_rc = _run("pipeline/load/daily/load_all.py")     # 2. LOAD everything
    ...
```

Two phases: **pull, then load.** Note the deliberate resilience: return code `2`
means "a partial pull — some vendor's server was unreachable," and the
orchestrator **still runs the load** so one vendor's outage doesn't stall
ingestion of the vendor that did arrive.

Each phase fans out. `pull/daily/pull_all.py` calls the per-vendor pullers
(`pull/nokia/all/daily/pull_all.py`, `pull/huawei/...`, `pull/metadata/...`), and
`load/daily/load_all.py` calls the per-vendor loaders. The structure mirrors the
data taxonomy exactly.

---

## 9.4 Pull and load are thin wrappers over `scripts/pipeline/`

Look inside a puller, e.g. `pipeline/pull/nokia/all/daily/pull_all.py`:

```python
script = os.path.join(PROJECT_ROOT, "scripts", "pipeline", "pull_nokia_raw_daily.py")
proc = subprocess.run([sys.executable, script, "--category", args.category], cwd=PROJECT_ROOT)
return int(proc.returncode or 0)
```

It just shells out to a script under `scripts/pipeline/`. This is the "safe
transition wrapper" pattern the orchestrator docstring mentions: the canonical
`pipeline/` tree provides a clean, taxonomy-shaped interface, while the actual
work still lives in the older `scripts/pipeline/` implementations. Over time the
logic migrates up into `pipeline/`; for now the wrappers give one stable entry
point.

- **Pull scripts** — SFTP-download raw exports into `raw/...`. The heavy lifting
  (SFTP connect, file listing, download) is shared with `modules/sync/sftp_client.py`.
- **Load scripts** — parse the raw files and insert rows into the SQLite DBs
  under `databases/...`. The parsing/loading is the same work
  `modules/sync/pm_processor.py` etc. do; that's the deliberate overlap between
  `pipeline/` (scripted) and `sync/` (UI-driven).

---

## 9.5 How data lands in the tables modules read

Putting Lessons 04 and 09 together, the full journey of one KPI value:

```
Nokia PM server (SFTP)
   │  pull (orchestrator → pipeline/pull → scripts/pipeline)
   ▼
raw/nokia/cells/4g/daily/<export files>
   │  load (orchestrator → pipeline/load → scripts/pipeline)   ← parse, normalize, insert
   ▼
databases/cells/nokia/all/daily/nokia_pm_cells_daily.db   (= NOKIA_PM_DAILY_DB)
   │  read (db/runtime + son_analytics/pm_helpers, Lesson 04/05)
   ▼
a module's /api/.../issues endpoint  →  the browser
```

Everything downstream of the load step is what Lessons 04–08 covered. The
pipeline is simply what keeps those SQLite files fresh.

---

## 9.6 Running / scheduling it

- **Manually:** `python pipeline/orchestrators/orchestrate_daily_full.py`
  (requires network access to the source servers and activation — or
  `NCM_SKIP_ACTIVATION=1`).
- **Scheduled:** in production, `deploy/run_scheduler.py` /
  `modules/sync/scheduler.py` run the orchestrators on a cron-like cadence. The
  daily pull hour and the Network-Health precompute hour are configurable via env
  (`NH_PRECALC_HOUR`, etc., in `network_health/config.py`).
- **From the UI:** the `sync` module (Lesson 08.4) exposes buttons/APIs to
  trigger pulls and watch progress.

> `AGENTS.md` guidance: for new automation, **prefer `pipeline/orchestrators/`**
> over adding more ad-hoc `scripts/`. The scripts are the legacy implementation;
> the pipeline tree is the intended interface.

---

## Recap

- Three SFTP sources (Nokia PM, Huawei PM, metadata) feed the pipeline.
- `pipeline/paths.py` defines the raw + DB folder taxonomy; always build paths
  with its helpers.
- Orchestrators run two phases — **pull then load** — fanning out per vendor, and
  tolerate partial pulls.
- The `pipeline/` tree is a clean wrapper over `scripts/pipeline/` implementations
  that share code with `modules/sync/`.
- The output is the SQLite files under `databases/` that every module reads.

**Next:** [Lesson 10 — Frontend & theming](10-frontend.md).
