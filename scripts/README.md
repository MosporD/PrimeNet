## Pipeline Scripts (Canonical + Compatibility)

The canonical pipeline entrypoints now live under `pipeline/`:

- **Orchestrators**
  - `pipeline/orchestrators/orchestrate_hourly_full.py`
  - `pipeline/orchestrators/orchestrate_daily_full.py`
  - `pipeline/orchestrators/orchestrate_watcher_cycle.py`
- **Pull**
  - `pipeline/pull/hourly/pull_all.py`
  - `pipeline/pull/daily/pull_all.py`
  - `pipeline/pull/{vendor}/all/{timeframe}/pull_all.py`
- **Load**
  - `pipeline/load/hourly/load_all.py`
  - `pipeline/load/daily/load_all.py`
  - `pipeline/load/{vendor}/all/{timeframe}/load_all.py`
- **Path taxonomy**
  - `pipeline/paths.py`

Legacy `scripts/*.py` remain for one-offs; **production pull/load/watch** backends live in `scripts/pipeline/`.

### Old to New Intent Mapping

- `scripts/pull_all_raw.py` -> `pipeline/pull/hourly/pull_all.py`
- `scripts/pull_all_raw_daily.py` -> `pipeline/pull/daily/pull_all.py`
- `scripts/pipeline/load_raw_csv_to_databases.py --scope hourly` -> `pipeline/load/hourly/load_all.py`
- `scripts/pipeline/load_raw_daily_to_databases.py` -> `pipeline/load/daily/load_all.py`
- Full hourly pull+load -> `pipeline/orchestrators/orchestrate_hourly_full.py`
- Full daily pull+load -> `pipeline/orchestrators/orchestrate_daily_full.py`
- Watcher one-cycle -> `pipeline/orchestrators/orchestrate_watcher_cycle.py`

To delete local PM/group SQLite files (destructive):
`python scripts/drop_legacy_performance_storage.py --confirm`
