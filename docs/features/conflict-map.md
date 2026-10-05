# Conflict Map

PCI / PSC / BCCH conflicts on a map (co-channel; 2G also adjacent ±1).

| | |
|---|---|
| Route | `/conflict-map` |
| Module | `modules/conflict_map/` (`routes.py`, `logic.py`) |
| Access | all |
| Version | V1.1 |

## Purpose

Detect identifier collisions from metadata (and related CM fields).

## Approach

Logic in `logic.py`. Map UI is local templates/static. Do not fold this into Network Map without an explicit ask.

- **3G/4G/5G:** co-channel PCI/PSC reuse with coband key from cell name; standard distance/azimuth strictness.
- **2G:** BCCH co-channel and adjacent (±1 ARFCN), selectable mode; no band split (all L900); same strictness profiles as 3G–5G.
- Study scope: **on-air cells only** (vendor active_state / admin_state via `metadata_active_sql`).
- Excel report: Reports → Conflict Report (same engine).

## Progress

Dated work log: [`conflict-map.progress.md`](conflict-map.progress.md). Do not duplicate long history here — update the progress file when this feature changes. Keep **Plans** as the module NEXT.


## Plans

None parked.

## Watch-outs

Conflicts are configuration identity, not HO neighbor quality. Adjacency GIS BCCH highlighter is a separate paint tool — not a pair/report engine.
