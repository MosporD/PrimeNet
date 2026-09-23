# NexPulse (Marketing Portal)

Reference second portal under NexusCore — campaigns, offers, audiences, consent.
Not a PrimeNet dashboard tile: lives under `portals/`, not `modules/`.

| | |
|---|---|
| Product | NexPulse |
| Domain | Marketing |
| Route prefix | `/portals/marketing` |
| Package | `portals/marketing/` |
| Store | `data/portals/marketing/marketing.db` (`NEXUS_MARKETING_DB`) |
| Process | `nexpulse_app.py` (users DB + `nexpulse_session` cookie) |
| Identity | `portals/marketing/access.py` → NexPulse users DB (not PrimeNet SSO) |
| Vision | `docs/NEXUSCORE_VISION.md` |

## Purpose

Give Marketing a lifecycle-backed workspace for offers and campaigns, with consent /
suppression / contact policy, before any CRM feed exists. Settles the portal scaffold
(shell, RBAC, provider seam, audit) that Support and Sales inherit.

## Approach

- Own SQLite schema + repositories + templates/static; import nothing from `modules/`.
- Provider seam (`providers.py`): `SegmentSizeProvider`, `CampaignMetricsProvider`,
  `NetworkFootprintProvider`. Network footprint is wired via HTTP to PrimeNet
  (`providers_primenet.py` + `modules/portal_api/`) when
  `NEXUS_PRIMENET_API_URL` + `NEXUS_PORTAL_API_TOKEN` are set.
- Offer lifecycle: draft → in_review → approved → live → retired.
- Campaign lifecycle: 8 states + readiness gate; network rules on a segment block
  approval until the PrimeNet footprint API is connected; capacity pressure is advisory.
- Segment builder: 15 attributes, 11 operators, validated rule expressions.
- MSISDN canonicalisation via `NEXUS_MARKETING_MSISDN_CC`.
- Tests: `portals/marketing/test_marketing.py`, `test_network_bridge.py`.

## User sees

Portal tower → Marketing → NexPulse: home, offer catalog, campaigns, segment builder,
consent/suppression/policy, calendar, audit trail, contactability lookup. Campaign
detail shows a network footprint panel when the PrimeNet API is connected.

## Progress

Dated work log: [`nexpulse.progress.md`](nexpulse.progress.md). Do not duplicate long history here — update the progress file when this feature changes. Keep **Plans** as the module NEXT.


## Plans

- Phase 2 remaining: campaign performance + holdout/uplift reporting, creative asset
  library, promo/quota engine.
- Later: per-platform activation (shared gate is temporary for local suite testing).

## Watch-outs

- Do not read PrimeNet SQLite from this portal — network attributes arrive via
  `/api/portal/network-footprint*`.
- Do not add Marketing features as PrimeNet `modules/` blueprints (portal API is the
  exception: it lives under `modules/portal_api` on the Engineering process).
- Unset `NEXUS_MARKETING_MSISDN_CC` stores digits as entered; DNC on one form will not
  match the other.
