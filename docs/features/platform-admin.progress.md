# Platform Admin — progress

Detailed dated log for this blueprint. Brief: [platform-admin.md](platform-admin.md).
Root journal (topics only): [../../progress.md](../../progress.md).

---

## 2026-10-05 (CM Approver flag)

- Done: `users.can_approve` column; Platform Admin Users table **Approver** checkbox; `PUT /api/platform-admin/users/<id>/approve`.
- Owners always count as approvers (checkbox disabled). Flagged emails feed Teams MessageCards via `list_approver_emails()`.

## 2026-10-07 (Owner persistent session)

- Done: Owners (`role=admin`) skip `is_password_change_required`; login creates ~100y session + cookie `max_age`; `get_user_by_session` extends Owner expiry on use. Other roles still use `SESSION_LIFETIME_HOURS`.
- NEXT: Re-login once as Owner after deploy so the long-lived cookie is set.

## 2026-10-07 (Platform Access vs module access)

- Done: Renamed tab to **Platform Access** (portals only). Removed Module Access UI/API from NexusCore (410 → Engineering Admin module-access-by-role).
- NEXT: NOC smoke — User Administration + Platform Access tab; portal edits unchanged.

## 2026-10-07 (CM Live Write moved to Engineering Admin)

- Done: Removed Approver UI and approve API from Platform Admin. Assignment lives on PrimeNet Engineering Admin → **CM Live Write** (`/admin-panel?section=cm-live-write`).
- NEXT: Set `NCM_TEAMS_WEBHOOK_URL` and smoke an ETL finish card (approver emails unchanged — same DB flag).

---
## 2026-09-29 (Postgres-only)

- How it works on PG: catalogued stores open via `open_db` / `open_store` into Postgres schemas (`NCM_DATABASE_URL` required). No SQLite file fallback for this module's data plane.
- NEXT: Smoke primary routes after Daily load on server PG.

## 2026-09-23 (Entry only on portal tower)

- Done: Removed Platform Admin links from PrimeNet dashboard and Eng Admin; Owner/NOC entry is portals topbar **Admin** only.
- Done: Removed `common.js` `_injectModuleAdminLink` (was stacking Admin/Settings on every module header).

## 2026-09-23 (Initial — moved from PrimeNet)

- Done: NexusCore `/admin` with User Administration + Module Access (feature_access matrix).
- Done: APIs under `/api/platform-admin/*`; linked from portal tower topbar.
- Done: PrimeNet Admin stripped of users/feature-access (410 redirect to this page).
- NEXT: None parked.
