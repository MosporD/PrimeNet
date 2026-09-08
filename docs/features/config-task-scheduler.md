# Config Task Scheduler

Scheduled config jobs (app DB tables).

| | |
|---|---|
| Route | `/config-task-scheduler` |
| Module | `modules/task_scheduler/routes.py` |
| Access | all |
| Version | V1.0 |

## Purpose

User-facing scheduler for config tasks (`config_scheduler_*` tables in ncm_users / app schema).

## Approach

Schema ensure must work on Postgres (`connect_app`, no PRAGMA-only paths). Distinct from `modules/sync/scheduler.py` (PM ETL).

## History

Phase 1 app-DB callers updated (2026-08-31).

## Plans

None parked.

## Watch-outs

Two “schedulers”: this UI vs the PM/metadata APScheduler process.
