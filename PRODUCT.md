# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary users are radio network / optimization engineers at a multi-vendor mobile operator. Their job is day-to-day RAN performance management, configuration audit, fault/SON investigation, and reporting across Nokia and Huawei networks (2G–5G), after signing in once and entering the Engineering portal.

Other audiences (marketing operators on NexPulse; future Support/Sales) exist as portal roles under the same umbrella, but they are not the primary persona for product decisions unless a surface is explicitly that portal.

## Product Purpose

NexusCore is a unified telecom & ISP platform umbrella. Operators authenticate once at the NexusCore lobby (portal tower), then enter a domain portal.

- **PrimeNet** (Engineering) — the deep, working RAN OSS: PM/CM ingestion and analysis, fault/SON detectors, config extraction/audit, inventory/maps/reporting.
- **NexPulse** (Marketing) — active second portal: offers, campaigns, segments, consent/contactability (explicit empty/"not connected" states when providers have no data).
- **NexResolve** (Support) / **NexArpu** (Sales) — named on the tower; Coming soon.

Success means engineers can trust the data, finish real optimization and config workflows without leaving the platform for vendor OSS for routine jobs, and navigate a coherent multi-portal shell as new domains come online.

## Positioning

In-house, operator-shaped RAN depth (Nokia + Huawei PM/CM, 2G–5G) behind a single SSO and portal-tower contract — not a generic dashboard bolted onto vendor UIs, and not a monolith that folds Marketing/Support into Engineering modules.

## Operating Context

- Entry: NexusCore login → activation gate when unlicensed → portal tower → PrimeNet dashboard (constellation deck) or other portal.
- Shared identity via `nexus_session`; portal allow-list per user; in-portal RBAC inside each portal.
- Vendors/tools in the real workflow: Nokia (e.g. NetAct), Huawei (e.g. U2020/MantaRay), PRS-class PM, Excel/exports; PrimeNet sits beside those systems with its own SQLite-backed stores and ETL pipeline.
- Dark/light theme preference persists across module pages; module UIs must remain usable in both.

## Capabilities and Constraints

Confirmed:

- Separate deployable apps/processes: lobby (`nexuscore_app.py`), Engineering (`primenet_app.py`), Marketing (`nexpulse_app.py`); local suite via `app.py`.
- ~40 PrimeNet engineering blueprints under `modules/`; new business domains are portals, not PrimeNet dashboard tiles.
- PM/CM for Nokia and Huawei; RATs 2G–5G; SQLite runtime stores; ETL under `pipeline/`.
- Module and portal access control; licensing/activation gate.
- Cross-portal data only through explicit APIs — no direct reads of another portal’s DB.
- UI must not fabricate live KPIs or marketing metrics; show honest empty / not-connected states.

Undecided / not established for this record:

- Formal accessibility standard (e.g. WCAG level) — not set.
- Corporate/operator visual brand rules beyond the product names and existing shell — not set here (visual world is out of scope for PRODUCT.md).

## Brand Commitments

- Umbrella name: **NexusCore**.
- Portal product names: **PrimeNet** (Engineering), **NexPulse** (Marketing), **NexResolve** (Support), **NexArpu** (Sales).
- Architecture rule: one shared design system / constellation–tower shell across portals; PrimeNet keeps its Engineering sub-brand inside that portal.
- Do not invent customer testimonials, fake benchmarks, or fake connected-provider numbers.

## Evidence on Hand

- Working PrimeNet module suite and NexPulse Phase 1 spine in this repository.
- Platform vision: `docs/NEXUSCORE_VISION.md`.
- Feature catalog and briefs: `docs/feature.md`, `docs/features/`.
- Frontend theme / dark-mode contract: `docs/FRONTEND_THEME.md`.
- No approved marketing case studies or third-party testimonials in-repo — do not fabricate them.

## Product Principles

1. **Engineer job-first** — PrimeNet surfaces optimize for scanability and trust in real RAN workflows over marketing spectacle.
2. **Honest data** — Prefer empty, degraded, and not-connected states over placeholder metrics.
3. **Portal boundaries** — Domains stay in their portals; Engineering depth does not absorb BSS/marketing as dashboard tiles.
4. **Shared shell, local depth** — One identity and tower contract; each portal owns its data and RBAC.
5. **Multi-vendor truth** — Nokia and Huawei, 2G–5G, remain first-class; UI and copy must not pretend a single-vendor world.
