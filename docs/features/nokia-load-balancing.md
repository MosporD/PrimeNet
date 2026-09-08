# Nokia Load Balancing

AMLE optimizer: Network Balance CSVs → proposals → Excel/RAML; optional NetAct import.

| | |
|---|---|
| Route | `/nokia-load-balancing` (legacy `/amle-optimizer` redirects) |
| Module | `modules/nokia_load_balancing/` (`logic.py`, `rules.py`, `balance_store.py`, `push.py`, `ingest_job.py`, …) |
| Access | admin |
| Version | V1.2 |

## Purpose

Admin AMLE workflow on Network Balance sector snapshots. Live CM extract `NOKLTE:AMLEPR` via CM Extractor client. Verify API: `/api/nokia-load-balancing/verify`.

## Approach

- Rules in `config.py` / `rules.py` — do not scatter magic numbers in routes.
- **Live OSS `actualImport` is confirmation-gated.** This host must not auto-push.
- Balance DB: `connect_network_balance()` (Postgres domain `balance` when enabled).
- SMB share auto-load: `\\RNO-WAN\Network Balance` (`smb_config.py`).

## History

- 2026-08-03: module + ingest. 2026-08-11: ingest process monitor.
- 2026-08-17: pipeline verify (rules + RAML dry-run). No auto-push on this host.

## Plans

Browser-verify with NetAct CM credentials was an older NEXT — only when Malek is on a host that can reach OSS.

## Watch-outs

Huawei LB **reuses** Nokia balance ingest/store. Do not fork the snapshot schema.
