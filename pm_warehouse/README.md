# pm_warehouse — raw PM counter ingestion & aggregation (pilot)

Store **counters**, aggregate counters (time-wise and object-wise) in
**PostgreSQL**, apply KPI **formulas at query time**. Replaces the
OSS-curated-KPI export model, whose stored ratios cannot be re-aggregated.
Standalone subsystem: no Flask dependency, nothing in the existing app changes.

## Layout

| File | Role |
|---|---|
| `db.py` | psycopg3 connections (`NCM_PG_*` env); calls `require_activation()` explicitly — the sqlite gate cannot see psycopg |
| `dictionary.py` | loads the committed Nokia counter/KPI dictionaries; `Logical Type` → per-counter agg rule |
| `nokia_adapter.py` | TS 32.435 streaming parser → `Block`s; zero→NULL for SUM-rule counters; misalignment ⇒ quarantine |
| `schema.py` | dims + ledger + **generated per-family fact tables** (counters as columns), grains `h/d/w/m` |
| `ingest.py` | ledger claim → in-memory ROP→hour fold → COPY + rule-driven `ON CONFLICT` merge (ACCUMULATE) |
| `rollup.py` | set-based h→d→w→m inside Postgres (REPLACE semantics — re-rolls are idempotent) |
| `kpi.py` | formula → AST → SQL compiler; reduction in GROUP BY *before* arithmetic (ratio-of-sums enforced); `/0` ⇒ NULL |
| `pilot.py` | CLI: `init · ingest · synth · rollup · kpi · verify · stats` |

## Run

```bash
pip install lxml "psycopg[binary]"
# Postgres 16+, database + role, then:
export NCM_PG_DSN="host=127.0.0.1 dbname=pm_pilot user=primenet password=..."
export NCM_SKIP_ACTIVATION=1                    # local dev only

python -m pm_warehouse.pilot init               # 55 families x 4 grains from the sample + dictionary
python -m pm_warehouse.pilot verify             # idempotency proof (double-ingest)
python -m pm_warehouse.pilot synth --enbs 10 --rops 96
python -m pm_warehouse.pilot rollup
python -m pm_warehouse.pilot kpi LTE_5003a --grain day --scope cell
python -m pm_warehouse.pilot kpi LTE_5004d --grain day --scope enb
python -m pm_warehouse.pilot stats
```

## Measured results (this sandbox, Postgres 16, single-threaded)

Sample: committed `PM202604260945+030072LNBTS.xml` — one eNB (16 cells), one
15-min ROP, 55 families, 4,449 counters, 75,058 values.

| Stage | Measured |
|---|---|
| init (DDL for 220 fact tables + 5,934 counters + 1,957 KPI formulas) | 4.3 s |
| parse+fold, real file | ~80–110 ms/file |
| fold, per file-equivalent | 13.8 ms |
| write (COPY + merge across 55 family tables) | **47,000 rows/s** |
| synthetic day, 10 eNBs × 96 ROPs (960 file-equivalents) | **25 s wall** (+65 s parse if files were real) |
| rollup h→d→w→m, 11 eNB-days | 1.6 s |
| KPI query (day grain, per cell, 110 rows) | **5 ms** |
| DB size, 11 eNB-days, all grains + indexes | 148 MB |

**Correctness gates passed:**
- double-ingest of the same file: skipped by ledger, facts bit-identical;
- `LTE_5003a` (DRB Setup SR) hand-summed from raw XML = warehouse value,
  **exact to 6 decimals** (99.725350), including summing across the MCCMNC
  dimension binding;
- object aggregation: 14-counter `LTE_5004d` drop ratio at eNB scope across
  16 cells;
- completeness surfaced per row (the real eNB shows 1% for its single ROP of
  the day; synthetic full days show 100%).

**Throughput extrapolation** (single-threaded, ~95 ms/file all-in):
4,200 files per 15-min ROP ⇒ ~0.45 cores to keep up with the full network.

**Storage observation:** the pilot's measured density extrapolates to roughly
55–65 GB/day for the hourly tier at 4,200 eNBs — about 2× the design's
heap-only estimate, and ~80 % of the *rows* come from just three per-relation
families (`LTE_Neighb_Cell_HO`, `LTE_ISYS_HO_UTRAN_NB`,
`LTE_X2_SCTP_Statistics`). Family-tiered hourly retention for those three is
the first knob to turn at scale; daily+ tiers are small regardless.

## Pilot simplifications (deliberate, documented)

- No ROP-grain tables (fold goes straight to hourly; the raw file archive is
  the ROP-fidelity record).
- No monthly partitioning yet (needed at network scale, not at pilot scale).
- `dim_object.site_id/area` not yet enriched from `metadata.db`.
- Companion `_min/_max` columns for AVG-rule counters not generated (hourly
  min/max of an average-type counter is not retained; the average itself is
  exact).
- `LAST`-rule merge is arrival-order overwrite (2 counters in the sample).
- Huawei adapter absent — blocked on a real U2020 NBI sample file and the
  `data/huawei_pm_counters/*.csv` catalog.
