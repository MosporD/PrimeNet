# Conflict Map

PCI / PSC / frequency conflicts on a map.

| | |
|---|---|
| Route | `/conflict-map` |
| Module | `modules/conflict_map/` (`routes.py`, `logic.py`) |
| Access | all |
| Version | V1.0 |

## Purpose

Detect identifier collisions from metadata (and related CM fields).

## Approach

Logic in `logic.py`. Map UI is local templates/static. Do not fold this into Network Map without an explicit ask.

## Progress

Dated work log: [`conflict-map.progress.md`](conflict-map.progress.md). Do not duplicate long history here — update the progress file when this feature changes. Keep **Plans** as the module NEXT.


## Plans

None parked.

## Watch-outs

Conflicts are configuration identity, not HO neighbor quality.
