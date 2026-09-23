# Admin Panel — progress

Detailed dated log for this blueprint. Brief: [admin-panel.md](admin-panel.md).
Root journal (topics only): [../../progress.md](../../progress.md).

---
## 2026-09-23 (Ops-only Engineering Admin)

- Done: Removed User Administration and Feature Access from PrimeNet Admin (moved to NexusCore Platform Admin).
- Done: Owner-only Engineering Admin; Ops Alerts tab keeps RET/CM accountability panels.
- Done: Nav/dashboard → Eng Admin (`?section=data-sync`); Platform Admin link to NexusCore.
- NEXT: None parked.

## 2026-09-20 (Portal allow-list on users)

- Done: Create-user portal checkboxes; Users table Portals column; PUT /api/admin/users/<id>/portals.
- NEXT: Bulk-grant NexPulse to marketing operators who should keep access after SSO cutover.

## From brief History (migrated 2026-09-17)

Activity log / feature grants evolved with the radio pack (2026-08).
2026-09-11: PM Plus Rules tab — family/counter agg + catalog import under /api/admin/pm-plus/*.
2026-09-17: CM Extractor Activity panel + Activity Log category filter (cm_* actions).
