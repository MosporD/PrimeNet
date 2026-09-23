# Alarm–PM Correlator — progress

Detailed dated log for this blueprint. Brief: [`alarm-impact.md`](alarm-impact.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

---
## From brief History (migrated 2026-09-17)

- 2026-08-17: added.

## 2026-08-17 (roadmap)

- Done: Nokia LB pipeline verify (rules + RAML XML dry-run + `/api/nokia-load-balancing/verify`). Live OSS import stays confirmation-gated; this host does not auto-push.
- Done: Huawei Load Balancing on Network Balance SQLite (CellMLB propose → Excel/MML). No U2020 push.
- Done: Neighbor 5G-5G + azimuth/freshness; sleeping-cell vs live FM; groups API on Network Health; Change Impact PM across RATs
- Done: Mobility Explorer, Alarm–PM Correlator, Group Health, IRAT/Vendor Border
- Done: KPI aliases for 2G/3G/5G; feature-access guards on radio insight modules; morning report composes the new outputs
- Modified: `app.py`, `core/radio/`, `core/module_access.py`, `core/module_versions.py`, `modules/nokia_load_balancing/`, `modules/huawei_load_balancing/`, new radio modules, `templates/dashboard.html`
