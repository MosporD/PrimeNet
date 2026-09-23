# Platform Admin — progress

Detailed dated log for this blueprint. Brief: [platform-admin.md](platform-admin.md).
Root journal (topics only): [../../progress.md](../../progress.md).

---
## 2026-09-23 (Entry only on portal tower)

- Done: Removed Platform Admin links from PrimeNet dashboard and Eng Admin; Owner/NOC entry is portals topbar **Admin** only.
- Done: Removed `common.js` `_injectModuleAdminLink` (was stacking Admin/Settings on every module header).

## 2026-09-23 (Initial — moved from PrimeNet)

- Done: NexusCore `/admin` with User Administration + Module Access (feature_access matrix).
- Done: APIs under `/api/platform-admin/*`; linked from portal tower topbar.
- Done: PrimeNet Admin stripped of users/feature-access (410 redirect to this page).
- NEXT: None parked.
