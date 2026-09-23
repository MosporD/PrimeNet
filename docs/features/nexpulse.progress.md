# NexPulse (Marketing Portal) — progress

Detailed dated log for this blueprint. Brief: [`nexpulse.md`](nexpulse.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

**NEXT:** Phase 2 remaining — campaign performance/holdout reporting, creative library, promo/quota engine.

---
## From brief History (migrated 2026-09-17)

- 2026-09-16: Phase 1 spine shipped — 31 routes, portal-local RBAC (5 roles / 13
  permissions), readiness gate, MSISDN CC flag, unit tests. Tower card Active.
- 2026-09-16: Split to `nexpulse_app.py` with own users DB / session cookie.
- 2026-09-16: Phase 2 slice — network-aware targeting bridge (PrimeNet portal API +
  capacity / coverage / technology footprint provider + campaign readiness gate).

## 2026-09-16 (NexPulse Phase 2 — network targeting bridge)

- Done: PrimeNet `modules/portal_api` — Bearer-token endpoints for technology footprint, congested sites (Capacity Hotspots), serviceability (layer coverage).
- Done: NexPulse `providers_primenet.PrimeNetNetworkFootprint` registered when `NEXUS_PRIMENET_API_URL` + `NEXUS_PORTAL_API_TOKEN` are set (`python app.py` wires local defaults).
- Done: Campaign readiness blocks approval when the audience uses network attributes but the API is offline; capacity pressure is advisory (soft gate at 25 congested sites).
- Done: Campaign detail network panel + overview provider status when connected.
- Tests: `portals/marketing/test_network_bridge.py`.
- **NEXT:** Phase 2 remaining — campaign performance/holdout reporting, creative library, promo/quota engine.

## 2026-09-16 (NexPulse — Marketing Portal)

- Done: `portals/` — NexusCore portals live outside `modules/`, as separate applications. `portals/marketing/` (NexPulse) owns its own SQLite store (`NEXUS_MARKETING_DB`, default `data/portals/marketing/marketing.db`), templates, static, and access rules; mounted with `create_marketing_portal(app)` in `app.py`. Splitting it into its own service = calling the same factory against a standalone Flask app
- Done: Phase 1 spine — Offer catalog (draft→in_review→approved→live→retired), Campaigns (8-state lifecycle + readiness gate), Segment builder (15 attributes, 11 operators, validated rule expressions), Consent / suppression / contact policy, plus calendar, audit trail, contactability lookup. 31 routes
- Done: Portal-local RBAC (5 roles, 13 permissions). Identity still comes from PrimeNet's login, isolated to `portals/marketing/access.py` — the only file that imports `database_enhanced`, per vision rule 2
- Done: Provider seam (`providers.py`) — `SegmentSizeProvider`, `CampaignMetricsProvider`, `NetworkFootprintProvider`. All null-backed; screens render explicit "not connected" states. No fixtures, no invented numbers. Real ingestion is a `providers.register()` swap
- Done: MSISDN canonicalisation via `NEXUS_MARKETING_MSISDN_CC` — without it `0791234567` and `962791234567` are two subscribers and a DNC entry on one will not stop a send to the other. Unset is allowed but flagged in the UI
- Done: Campaign readiness gate blocks approval without audience, channels, offers, schedule, and an active contact policy; holdout/templates/budget are advisory
- Done: `portals/marketing/test_marketing.py` — 25 tests (lifecycles, rule validation, consent precedence, MSISDN matching, RBAC layering, audit, architecture isolation). `python -m pytest portals/marketing/test_marketing.py` — 25/25. Full suite 172 passed (2 pre-existing collection errors in `scripts/test_personal_vendor_credentials.py`, a manual CLI script)
- Done: Portal tower — Marketing now Active and routed to the portal; product names NexPulse / NexArpu / NexResolve on the cards
- Modified: `app.py`, `routes/auth_routes.py`, `templates/portal_select.html`, `templates/portal_coming_soon.html`, `docs/NEXUSCORE_VISION.md`, new `portals/`
- **NEXT:** Phase 2 for NexPulse — campaign performance + holdout/uplift reporting, creative asset library, promo/quota engine, and the network-aware targeting bridge (coverage, serviceability, capacity gating) over a PrimeNet API
