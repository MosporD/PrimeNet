# PrimeNet — raw PM ingestion & counter aggregation (design v2)

**Status:** design draft for review. No repo changes.
**Scope:** ingest raw NBI counter files (Nokia + Huawei), store and aggregate
**counters** — time-wise (hourly/daily/weekly/monthly) and object-wise (cell →
site → group/area/network) — in **PostgreSQL**. KPIs are *not* part of
ingestion: they are user-supplied formulas evaluated at query time over the
aggregated counters, femto-module-style.

v2 supersedes v1 on four points, following review:

| # | v1 said | v2 says |
|---|---|---|
| 1 | Nokia-shaped parser | **Format-adapter layer**; three formats identified in-repo (§3) |
| 2 | KPI-driven counter allowlist (~1.5 % of feed) | **Full counter set is the requirement** — user formulas may reference any counter later, so pre-filtering breaks the product. Volume re-done for full scope (§7) |
| 3 | SQLite is sufficient | **PostgreSQL** is the PM warehouse (§8) — right call at full-counter scope, and it was already the direction |
| 4 | KPI evaluation engine discussed alongside ingest | **Ingestion pipeline never touches KPIs.** Aggregation is counters-only; KPI formulas are applied afterwards at query time (§10) |

All numbers are measured from the committed sample
(`PM202604260945+030072LNBTS.xml`, one eNB × one 15-min ROP) and the committed
dictionaries, scaled to **4 200 eNBs × 15 cells = 63 000 cells**.

---

## 1. The one invariant that survives every revision

> **Store counters. Aggregate counters. Apply formulas last, at the target
> grain, on user demand.**

A ratio, once divided, cannot be re-aggregated (v1 §1 had the worked example:
mean-of-ratios vs ratio-of-sums diverge by up to the full range). The current
wide tables store OSS-computed ratios, which is why object groups and time
aggregation are unimplementable today. Everything in this design exists to keep
numerators and denominators apart until the user's query decides the scope.

This is exactly the femto module's model — `FEMTO_VALUES(unique_id, timestamp,
kpi_name, kpi_value)` plus user formulas in `femto_user_kpis.db` translated to
SQL at query time (`modules/femto_pm/kpi_store.py:196` turns `SUM(pattern)` into
`SUM(CASE WHEN kpi_name LIKE … THEN kpi_value END)`) — scaled up ~4 000 × and
given a proper aggregation pyramid.

---

## 2. Aggregation semantics (unchanged from v1, restated tightly)

Per-counter aggregate state, stored at every grain:

```
S = (sum, min, max, n_present, n_expected)
merge(S₁,S₂) = (sum₁+sum₂, min(min₁,min₂), max(max₁,max₂), n₁+n₂, e₁+e₂)
```

Merge is a **commutative monoid** ⇒ rollups compose exactly (`day` from `hour`
≡ `day` from raw), order never matters, late files merge correctly, and
**object aggregation is the same operation as time aggregation** with different
GROUP BY keys.

Finalisation per counter comes from the dictionary's `Logical Type`
(measured distribution over the 5 934-counter 4G dictionary):

| Logical Type | Share | Finalise as |
|---|---|---|
| `Sum`, `Denominator` | 81.3 % | `sum` |
| `Average` | 9.4 % | `sum / n_present` |
| `Max` / `Min` | 8.9 % | `max` / `min` |
| `Cumulative` | 0.2 % | delta before summing; delta < 0 ⇒ NE restart |
| `Current` | 0.1 % | last value (carry `last_ts`) |

`n_present`/`n_expected` (4 ROPs/hour, 24 h/day…) makes partial buckets
**visible** instead of silently wrong. Percentiles do not compose — histogram
families (e.g. `LTE_SINR`, 560 bins, each bin a `Sum`) are the supported answer
for distribution questions.

---

## 3. Format adapters — the vendor reality

Three raw formats are already in evidence **inside this repo**, and a fourth is
expected. The pipeline core must be format-blind; each source gets an adapter
that emits one normalised stream:

```python
Measurement = (
    vendor,          # nokia | huawei | femto
    object_dn,       # vendor-native base DN, verbatim
    dims,            # {dim_name: value} — may be empty
    family,          # measurement group (measInfoId / <mn> / Huawei function subset)
    counter_native,  # 'M8007C1' | 'Oam_Bootup_Sum' | Huawei counter id
    bucket_start_utc, granularity_sec,
    value,
)
```

### 3.1 Nokia macro — 3GPP TS 32.435 XML (sample committed, fully measured)

`measCollecFile` / `measInfoId` / positional `measTypes`↔`measResults`,
`measObjLdn` = base DN + comma-separated dimension bindings
(`MCCMNC=…`, `HANDOVER_ADJACENT_CELL=…`). One file per eNB per ROP, gzip ~9.1×.
Everything quantified in §6–7 comes from this format.

### 3.2 Femto — 3GPP TS 32.432/32.401 `mdc` (sample committed at `femto/`)

The *older* DTD-based encoding: `<mfh>`/`<md>`/`<mn>`(name)/`<mt>`(counter)/
`<mv>`(value), `<gp>3600</gp>`, `.tgz` container, one file per Home NodeB per
hour. **The repo already parses this** (`scripts/pipeline/load_femto_pm_to_db.py`)
— the femto adapter is a port of existing code to the normalised stream, not new
work. Note `<sf>` (suspect flag) exists in this format and must map to a
quality mark, and `<nesw>` carries metadata (tac, MCC/MNC, coords) worth
harvesting into `dim_object`.

### 3.3 Huawei — two distinct things, be precise about which

- **What the repo ingests today:** PRS **xlsx** exports in zips
  (`raw/huawei/.../Performance_Groups(72).zip` → one xlsx, verified). That is a
  *curated KPI export* — same model being replaced on the Nokia side, same
  ratio problem. It is the interim feed, not the target.
- **The target: U2020 PM NBI result files.** Huawei's northbound PM delivery is
  file-based (FTP/SFTP push), typically **CSV keyed by counter ID and object
  FDN**, optionally 3GPP XML where licensed. **No sample exists in this repo**,
  and the Huawei counter catalog CSVs (`data/huawei_pm_counters/*.csv`,
  expected by `core/huawei_pm/counter_catalog.py`) are **not committed** —
  though that module's header says the catalog carries
  *"Time/Reference Time/Object aggregations"*, i.e. Huawei ships per-counter
  aggregation rules just like Nokia's `Logical Type`.

**Consequence:** the Huawei adapter is specified as an interface with a CSV
skeleton, and is finalised only against a real U2020 NBI sample + the catalog
CSVs. This is the top blocking input (§12). The design does not otherwise
depend on it — dimensions, DN shape and counter naming are adapter-local.

### 3.4 Where vendors meet

Vendor never blends silently: `dim_counter` and `dim_object` are keyed by
vendor, and no formula may mix vendors' counters in one expression (Nokia and
Huawei counters measure different things under different triggers). Cross-vendor
comparison happens at the *KPI result* level in the UI, exactly as the current
Performance module does with its side-by-side vendor filters.

---

## 4. Schema (PostgreSQL)

### 4.1 Dimensions — small, ordinary tables

```sql
CREATE TABLE pm.dim_object (
  object_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  vendor      text NOT NULL,
  ne_class    text NOT NULL,              -- LNBTS|LNCEL|LNADJ|HNB|…
  base_dn     text NOT NULL,
  parent_id   bigint REFERENCES pm.dim_object,
  site_id     text,  cell_name text,  technology text,  area text,
  first_seen  timestamptz, last_seen timestamptz,
  UNIQUE (vendor, base_dn)
);

CREATE TABLE pm.dim_binding (
  binding_id  int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  binding_key text NOT NULL UNIQUE,       -- canonical 'k=v;k=v'; row 0 = empty
  dims        jsonb NOT NULL
);

CREATE TABLE pm.dim_counter (
  counter_id  int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  vendor      text NOT NULL,  technology text NOT NULL,
  native_id   text NOT NULL,              -- 'M8007C1' / Huawei id
  family      text NOT NULL,              -- 'LTE_EPS_Bearer'
  column_name text NOT NULL,              -- its column in the family tables
  agg_rule    text NOT NULL,              -- SUM|AVG|MAX|MIN|LAST|CUM
  unit text, display_name text, netact_name text, dict_version text,
  UNIQUE (vendor, technology, native_id)
);
```

`site_id`/`area` are denormalised via the existing `core/site_area.py` logic —
that module stays the single source of truth for area routing.

### 4.2 Facts — **one table per measurement family, counters as columns**

This is the load-bearing storage decision, so the alternatives are stated:

| Layout | fact rows/day (hourly grain, full scope) | Why not |
|---|---|---|
| Narrow EAV `(object, counter, bucket, state)` | **2.29 billion** (measured: 24 254 kept values/eNB-ROP ÷ 4) | 23-byte tuple header per *value*; 5–10 × the storage; the femto narrow table does not survive ×4 000 |
| One giant wide table | 1 row/object/bucket | 4 449 columns exceeds practical limits; every family's dimensions collide |
| **Per-family wide table** | **223 million** | — |

One table per `measInfoId`, columns = that family's counters (2–560 cols;
Postgres limit 1 600), rows = one per `(object, binding, bucket)`:

```sql
CREATE TABLE pm.h_lte_eps_bearer (            -- hourly grain, family LTE_EPS_Bearer
  object_id  bigint  NOT NULL,
  binding_id int     NOT NULL DEFAULT 0,
  bucket     timestamptz NOT NULL,
  n_present  smallint NOT NULL,
  n_expected smallint NOT NULL,
  m8006c0    real,  m8006c1 real,  /* … one col per counter … */
  PRIMARY KEY (object_id, binding_id, bucket)
) PARTITION BY RANGE (bucket);                -- monthly partitions
```

Why this layout wins here specifically:

- **Zeros/absent become NULL, and Postgres NULLs cost one bit** in the null
  bitmap. The measured 71 % zero-density is nearly free without any special
  encoding, while staying exactly correct (`NULL` = absent; reads use
  `COALESCE(c,0)` for SUM-rule counters only).
- **The 23-byte tuple header amortises** over ~32 counters/row instead of
  burning per value.
- **It mirrors the wire format 1:1** — a `measValue` block *is* a row, so the
  parser emits rows without pivoting.
- **Formulas compile to plain SQL** — `sum([M8006C1])` → `SUM(m8006c1)` on the
  family table; the femto `CASE WHEN` contortion disappears (§10).
- It is the same schema-evolution pattern the repo already runs
  (`_ensure_columns` → `ALTER TABLE ADD COLUMN` on new counters), now driven by
  the dictionary instead of by CSV headers.

Per-counter `min`/`max`/`avg` state: for `Sum` counters (81 %) the single
column *is* the state. For `Average/Max/Min` counters the family table carries
companion columns (`c123_min`, `c123_max`) — generated only for the ~19 % of
counters whose rule needs them, which is why this stays cheap.

**Grain set per family:** `r_<family>` (ROP, short retention, optional per
tier), `h_` (hourly), `d_` (daily), `w_`, `m_`. Identical shape; `n_expected`
differs. Weekly/monthly build from daily.

**DDL is generated, not hand-written**: a builder reads `dim_counter` (itself
loaded from the committed Nokia dictionary JSON + Huawei catalog CSVs when
supplied) plus observed `measTypes`, emits `CREATE TABLE`/`ALTER TABLE ADD
COLUMN`, and records every schema action. Unknown counters seen in a file are
added with `agg_rule='SUM'` + a review flag rather than dropped — at 99.2 %
measured dictionary coverage, unknowns are rare but must not be lost.

### 4.3 Object groups

```sql
CREATE TABLE pm.object_group (
  group_id   int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name text NOT NULL, owner_id int,       -- NULL = shared
  ne_class text NOT NULL,
  dim_policy jsonb NOT NULL               -- per dimension: pin to value | sum over
);
CREATE TABLE pm.object_group_member (
  group_id int REFERENCES pm.object_group ON DELETE CASCADE,
  object_id bigint REFERENCES pm.dim_object,
  PRIMARY KEY (group_id, object_id)
);
```

Enumerated membership by default (predicate-defined groups silently change
membership over time, which corrupts period-over-period comparisons — offer
predicates as a *builder*, storing the resolved list). `dim_policy` is what
makes "multi-NE single value" well-defined: every dimension is either pinned or
summed over — mixed bound/unbound rows must never be blended (that
double-counts, and in the sample the unbound rows are a *different* population
from the MCCMNC-bound rows — verified: zero overlap in (base DN, counter)
pairs, so the rule costs nothing today but prevents the classic accident
later).

### 4.4 Ingest ledger

As v1: `pm.ingest_ledger(file_key PRIMARY KEY, …, state, rows, timings, error)`
with content-derived `file_key = sha256(vendor, ne_dn, rop_end_utc, size)`.
The ledger is the idempotency guard — without it the monoid merge would
double-count on re-delivery — and the observability surface.

---

## 5. Pipeline

```
SFTP watchers (per-vendor, per-ROP landing dirs — never ls a 400k-file tree)
      │ file paths
      ▼
work queue  ── ledger.claim(file_key) ──►  N parser workers
      │        adapter: stream-parse → normalised Measurements
      │        fold in-memory: (object,binding,family,hour) → row of counter states
      ▼
per-(family, hour) batches ──►  writer: COPY into staging, then
      │                         INSERT … ON CONFLICT DO UPDATE (monoid merge)
      ▼
h_<family> partitions ──(bucket close + dirty-bucket queue)──► d_ ► w_/m_
      │
      └─ raw file → archive (short retention) → delete
```

Design properties (argued in v1 §7, unchanged): idempotent, constant-memory
(`iterparse` + `elem.clear()`), order-independent, restartable per file,
fail-isolated (quarantine one file, never stall the ROP), auditable.

Points that change with Postgres:

- **COPY, not INSERT loops.** Batches land in an UNLOGGED staging table via
  `COPY`, then merge into the partition with a single
  `INSERT … ON CONFLICT (object_id,binding_id,bucket) DO UPDATE SET
  c = COALESCE(t.c,0)+COALESCE(excluded.c,0), n_present = …` statement.
  Required sustained rate is **~2 600 rows/s** network-wide (223 M/day across
  ~55 family tables); COPY+merge handles an order of magnitude more on modest
  hardware.
- **Rollups are set-based SQL in the database** (`INSERT INTO d_x … SELECT …
  GROUP BY` with the same ON CONFLICT merge), scheduled per closed bucket plus
  a dirty-bucket re-roll for late arrivals. No Python row-shuffling.
- **Concurrency is native.** No WAL busy-timeout dance; parser workers scale
  with `core/resource_limits.py` governing counts, writers per family-partition
  never contend.

Parse cost is a solved question — measured 31 ms per gz file including
decompress; 4 200 files/ROP = 131 core-seconds in a 900 s window = **0.15
cores** for the whole network, ~1–2 cores with 10 × margin. The parser needs no
further optimisation; the engineering effort belongs in the write path and
retention.

---

## 6. What one eNB-ROP contains (measured, unchanged)

1.78 MB XML (195 KB gz): 2 361 blocks, 55 families, 4 449 counters, 75 058
values, 71.2 % zeros; 225 base DNs × dimension bindings → 1 959 LDNs; LNCEL
carries 98 % of values. Dictionary resolves 99.2 % of counters. `MCCMNC` has
one value in this eNB (single PLMN) — **verify network-wide** before assuming
`binding_id=0` dominates; the schema keeps `binding_id` regardless so RAN
sharing is a data question, not a migration.

---

## 7. Sizing at full-counter scope — 63 000 cells

The requirement is the **entire counter set** (user formulas may reference any
counter later). No allowlist. The levers that remain are layout, zero-as-NULL,
per-tier retention, and grain.

Measured/derived per day, network-wide:

| | Narrow EAV | **Per-family layout** |
|---|---|---|
| Raw values/day | 28.4 G | 28.4 G (through memory only) |
| Kept values/day (zeros→NULL for SUM-rule) | 9.17 G | — (NULLs ≈ free) |
| **Hourly-tier rows/day** | 2.29 G | **223 M** |
| Daily-tier rows/day | ~150 M | **9.3 M** |
| Write rate sustained | 26 500 rows/s | **2 600 rows/s** |

Postgres heap estimates (24 B header + keys + null bitmap + 4 B per non-NULL
`real`; non-zero density per family measured, union-widening across ROPs
estimated ×1.6 hourly / ×2.5 daily; add ~30–40 % for the PK index):

| Tier | GB/day | Retention | Size (heap) | With index |
|---|---|---|---|---|
| ROP (optional, tiered) | ~60 | 3–7 d | 0.2–0.4 TB | 0.3–0.6 TB |
| **Hourly** | **21.6** | 90 d | **1.9 TB** | **~2.6 TB** |
| Hourly | | 30 d | 0.65 TB | ~0.9 TB |
| **Daily** | **1.0** | 730 d | **0.7 TB** | **~1.0 TB** |
| Weekly + monthly | ≪ 0.1 | indefinite | < 0.1 TB | < 0.1 TB |
| Raw archive (gz as delivered) | 78.6 | 7–14 d | 0.55–1.1 TB | — |

**Planning envelope: a 4–6 TB Postgres volume carries the full counter set with
90-day hourly and 2-year daily retention.** That is a real but ordinary server.
The knobs, in order of power:

1. **Hourly retention** — 90 d → 30 d saves ~1.7 TB. Daily+ is where long
   history lives; 90 hourly days covers every "what happened that evening"
   investigation.
2. **Family tiers** — full aggregation for all, but shorter hourly retention
   for the two per-relation HO families: `LTE_Neighb_Cell_HO` +
   `LTE_ISYS_HO_UTRAN_NB` are **7.5 GB/day of the 21.6** (measured) while being
   95–100 % zeros and feeding a daily-cadence use case (neighbour audit).
   30 d hourly for those two families alone saves ~0.45 TB and nothing of value.
3. **`real` vs `double precision`** — 4 bytes vs 8. Counters are integers or
   coarse averages; `real`'s 24-bit mantissa is exact up to 16.7 M, and large
   counters (byte counts) lose only low-order bits at ROP grain. Where exactness
   matters at high magnitude (traffic-volume counters summed over months), mark
   those columns `double precision` from the dictionary's Unit field
   (`bytes`/`bit` → double; ~210 of 4 449 counters). Cheap and targeted.
4. **Source-side filtering** remains the biggest lever *if* NetAct can restrict
   emitted measurement families — that shrinks everything upstream of the
   pipeline. Still worth the question even though the system no longer depends
   on it.

Growth headroom: these figures are LTE-only. 2G/3G (BSC/RNC-level objects, far
fewer NEs) add little; 5G NR at cell grain adds roughly proportionally to NR
cell count — re-run the same measurement on one gNB file when available.

---

## 8. PostgreSQL integration into PrimeNet

The decision is Postgres; this section is how it lands in *this* repo without
breaking its conventions.

- **Split, not migration.** The PM warehouse (schema `pm`) moves to Postgres.
  Users/sessions/metadata/app DBs **stay SQLite** — 39 modules depend on that
  stack and nothing about counter volume applies to them. The old wide KPI
  tables keep working during transition; the femto module is untouched.
- **`db/runtime.py` grows a real second backend.** It already contains
  vestigial Postgres shims (`is_postgresql()`, `adapt_placeholders()` — v1
  called them dead code; they become live again). Add `connect_pm_pg()`
  (psycopg3, pooled via `psycopg_pool`), DSN from `NCM_PG_DSN` env with
  components overridable (`NCM_PG_HOST`, …). All PM-warehouse access goes
  through it — same rule as today, new engine.
- **The activation gate does not see psycopg.** `core/activation_gate.py`
  monkeypatches `sqlite3.connect` only. `connect_pm_pg()` must call
  `require_activation()` explicitly, or the licence lock silently stops
  covering the platform's main dataset. One line, easy to forget, so it goes in
  the connector, not at call sites.
- **Metadata joins across engines.** Today `performance_meta_pm_conn()` ATTACHes
  SQLite files to JOIN inventory×PM. Cross-engine, that becomes: resolve the
  object set from `pm.dim_object` (which denormalises `site_id`/`area`/
  `technology`/`cell_name` from metadata at sync time — the refresh hook rides
  the existing metadata sync). The JOIN happens inside Postgres against
  `dim_object`; SQLite metadata remains authoritative and is mirrored, not
  queried per-request.
- **Deploy.** `docker-compose.yml` gains a `postgres:16` service with a
  dedicated volume (the PM volume sizing of §7, *separate* from
  `NCM_DATA_ROOT`), healthcheck, and `shared_buffers`/`max_wal_size` tuned for
  bulk COPY. Non-Docker installs get a documented external-DSN path. Backups:
  the warehouse is *rebuildable from the raw archive* within its retention
  window — `pg_dump` of dims + daily/weekly/monthly tiers is small; hourly can
  be declared re-derivable to keep backup windows sane.
- **Ops guardrails.** Monthly partitions dropped by the retention job
  (partition drop is instant; no `DELETE` storms — this replaces
  `core/pm_retention.py`'s row-delete approach for the warehouse), autovacuum
  mostly irrelevant on append-only partitions, BRIN index on `bucket` per
  partition for range scans, `pg_stat_statements` on from day one.

---

## 9. Query model — aggregation as the product surface

What the user asked for, precisely: *time aggregation* and *object aggregation*
of counters, selected by criteria at query time.

One parameterised query shape serves all of it:

```sql
SELECT <object_grouping>, <time_grouping>,
       SUM(c.m8006c1) …,                        -- SUM-rule counters
       SUM(c.x_sum)/NULLIF(SUM(c.n_present),0), -- AVG-rule counters
       MAX(c.y_max) …                           -- MAX-rule counters
FROM pm.h_lte_eps_bearer c
JOIN pm.dim_object o USING (object_id)
[JOIN pm.object_group_member g ON g.object_id = c.object_id AND g.group_id = :gid]
WHERE c.bucket >= :t0 AND c.bucket < :t1
  AND c.binding_id = ANY(:bindings)             -- pin or enumerate, never implicit
  AND <object criteria: o.area / o.technology / o.site_id / group>
GROUP BY <object_grouping>, <time_grouping>
```

- **Time axis:** grain picked by range (raw/hour for a day, day for a quarter,
  week/month beyond), `date_trunc` or bucket passthrough. Busy-hour = window
  over the hourly tier (`argmax` of a nominated traffic counter per day, then
  report all counters at that hour).
- **Object axis:** `GROUP BY` on `object_id` (per-cell), `o.parent_id` (per
  eNB), `o.site_id`, `o.area`, `g.group_id` (user groups), or nothing
  (network). The object lattice is data (`dim_object`), not code.
- **Completeness always travels with the value:**
  `SUM(n_present)::float / SUM(n_expected)` returned per row; the UI flags
  < 95 %.

This endpoint (`/api/pm/query`, module `pm_explorer` or an evolution of
`performance`) is the "sophisticated femto": pick counters (or a saved KPI —
§10), pick object scope, pick time scope, get correctly-aggregated numbers.

---

## 10. KPIs — query-time formulas, exactly like femto but compiled

KPIs live entirely **above** the warehouse:

```sql
CREATE TABLE pm.user_kpi (           -- mirrors femto_pm/kpi_store.py shape
  kpi_id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name text NOT NULL UNIQUE, category text, unit text, description text,
  vendor text NOT NULL, technology text NOT NULL,
  formula text NOT NULL,             -- '100*sum([M8007C1])/sum([M8007C0])'
  created_by text, created_at timestamptz, updated_at timestamptz
);
```

Evaluation path:

1. **Parse** the formula (60-line recursive-descent; grammar: `+ - * /`,
   parentheses, numbers, `sum(...)`, `[COUNTER]` tokens — verified sufficient
   for 99.7 % of the 1 957 vendor 4G formulas, which can be offered as a
   pre-seeded read-only catalog on day one). Never `eval()`.
2. **Resolve** each `[counter]` via `dim_counter` → (family table, column,
   agg_rule). Reject mixed-vendor formulas.
3. **Compile** to SQL: each counter token becomes its aggregate expression from
   §9 (`sum([c])` → `SUM(COALESCE(c,0))` for SUM-rule; AVG/MAX rules
   substitute their finalisation); formulas spanning multiple families compile
   to a join of the family tables on `(object_id, binding_id, bucket)` — or
   two grouped subqueries joined on the grouping keys, whichever the planner
   prefers.
4. **Guard:** denominator `NULLIF(...,0)` ⇒ KPI is `NULL` (never 0, never an
   error) where undefined; completeness ratio attached; grain/object-level
   sanity from the vendor dictionary's `Time Summary Levels` / `Object Summary
   Levels` where known (warn, don't block, for user-authored formulas).

Because the reduction happens in `GROUP BY` *before* the arithmetic, the §1
invariant is structurally enforced — a user cannot express mean-of-ratios by
accident; the compiled SQL always computes ratio-of-sums at the requested
scope.

No KPI materialisation in phase 1. If specific dashboard KPIs later prove hot,
materialise those as cached tables keyed by formula hash — an optimisation,
never a source of truth.

---

## 11. Correctness checklist (v1 §12, deltas only)

All 16 v1 hazards stand. Postgres/femto-specific additions:

| # | Hazard | Handling |
|---|---|---|
| 17 | Femto `<sf>` suspect flag | Map to a per-row quality bit; excluded rows count in `n_expected`, not `n_present` |
| 18 | Huawei counter semantics assumed Nokia-like | Blocked on catalog CSVs; `agg_rule` is per-vendor data, never defaulted across vendors |
| 19 | psycopg bypasses the activation gate | `require_activation()` inside `connect_pm_pg()` (§8) |
| 20 | `real` precision on huge counters | `Unit ∈ {bytes, bit}` → `double precision` columns (§7.3) |
| 21 | Cross-engine metadata drift | `dim_object` refresh rides the metadata sync; staleness alarm if refresh age > sync cadence |
| 22 | User formulas as injection surface | Formula → AST → parameterised SQL built from whitelisted column names out of `dim_counter`; user text never enters SQL |

---

## 12. Open questions (re-prioritised)

1. **A real Huawei U2020 PM NBI sample file + the counter catalog CSVs**
   (`data/huawei_pm_counters/*.csv`). Blocks the Huawei adapter and confirms
   Huawei-side aggregation rules. Everything Nokia-side proceeds without it.
2. **Postgres placement & budget:** same host as the app or dedicated? Available
   volume size (§7 wants 4–6 TB for the comfortable configuration)? Existing PG
   ops experience in the team (backups, upgrades)?
3. **Hourly retention target** — 30 vs 90 days is the single biggest disk
   decision (~1.7 TB swing).
4. **Can NetAct restrict emitted measurement families at source?** No longer a
   dependency, still the cheapest possible win.
5. **Single-PLMN confirmed network-wide?** (One eNB proves nothing about RAN
   sharing agreements.)
6. **NBI delivery details:** landing path, per-NE vs bundled files, SLA after
   ROP close, and whether 2G/3G/5G ROPs differ from `PT900S`.
7. **Scope of "63 000 cells":** LTE only (as stated), or should 2G/3G/5G volumes
   be measured now from sample files?

---

## 13. Build order (revised)

| Phase | Deliverable | Gate |
|---|---|---|
| 0 | Postgres service + `connect_pm_pg()` + activation coverage; dictionary loaders → `dim_counter` (Nokia JSON; Huawei when CSVs arrive) | Schema generator emits DDL for all 55 families from the dictionary + sample file |
| 1 | Nokia 32.435 adapter (port of the measured parser) + ledger + fold + COPY/merge writer; **one eNB, one day** end-to-end | Re-ingest the same day twice ⇒ bit-identical tables (idempotency) |
| 2 | Rollups h→d→w→m + dirty-bucket re-roll + partition/retention jobs | `d` from `h` ≡ `d` from raw replay; partition drop verified |
| 3 | Femto adapter (port `load_femto_pm_to_db.py`) — small, proves the adapter interface with a second format | Femto module parity on its existing pages |
| 4 | Query endpoint (§9) + formula compiler (§10) + vendor-formula catalog seed | **Recompute 10–20 KPIs for one eNB-day and diff against the OSS's own exported values** — the acceptance test for the whole model |
| 5 | Object groups + dim policy + UI (Performance Explorer evolution) | Multi-NE single value on a real group |
| 6 | Huawei U2020 adapter (blocked on sample) | Same phase-4 diff, Huawei side |
| 7 | Scale-up: full-network watcher, backpressure via `core/resource_limits.py`, ops dashboards on `ingest_ledger` | Sustained ROP-close-to-queryable < 5 min at full load |

Phase 4 remains the moment of truth: if counter-recomputed KPIs match the OSS's
own numbers for the same cell and hour, the model is proven on one eNB before
any cutover risk exists.

---

## 14. Summary

- **Counters in, counters aggregated, formulas on top at query time** — the
  femto model, industrialised. Ingestion never computes a KPI (point 4,
  adopted).
- **Three source formats already live in this repo** (Nokia 32.435, femto
  32.432 mdc, Huawei PRS xlsx-interim) and a fourth expected (U2020 NBI); a
  thin adapter layer normalises them, and the Huawei adapter is the one
  genuinely blocked input (point 1, adopted).
- **Full counter set, no allowlist** (point 4's consequence): 28.4 G raw
  values/day network-wide. Made tractable not by filtering but by *layout* —
  one table per measurement family with counters as columns turns 2.29 G
  narrow rows/day into **223 M rows/day**, and Postgres NULL-bitmap encoding
  makes the 71 % zero-density nearly free (point 2, adopted: it *is* a lot,
  and this is the shape that survives it).
- **PostgreSQL as the PM warehouse** (point 3, adopted): monthly-partitioned
  family tables, COPY + monoid ON CONFLICT merges at ~2 600 rows/s required,
  set-based rollups in-database, partition-drop retention. App/users/metadata
  stay SQLite; `db/runtime.py` gains the PG connector; the activation gate gets
  explicit PG coverage.
- **Planning envelope: 4–6 TB** for full counters at 90 d hourly + 2 y daily;
  hourly retention and two HO families are the big knobs.
- The acceptance gate is unchanged and non-negotiable: **recomputed KPIs must
  match the OSS's own numbers** on one eNB before anything is cut over.
