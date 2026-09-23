# NexusCore — Platform Vision

NexusCore is the umbrella platform ("Unified Telecom & ISP Platform") that will
grow to cover the mainstream functions a telecom operator needs. **PrimeNet**
— the existing Flask application in this repository — is the first portal under
that umbrella: the Engineering Portal, focused on radio network performance,
configuration, and optimization.

This document is the shared plan: what the complete system spans, how the
portals map onto industry domains, the architectural rules that keep the build
sane, and the order in which the portals get built. Every new project under
NexusCore should start from this page.

---

## 1. Where we are today

PrimeNet is a deep, working slice of one domain: a RAN-focused OSS, now a
**separate process** from the NexusCore lobby and from NexPulse.

- PM (performance) and CM (configuration) ingestion for **Nokia and Huawei**,
  radio technologies **2G–5G**, stored in SQLite.
- ~40 modules behind PrimeNet login: performance analytics, fault management,
  SON/optimization detectors (sleeping cells, overshooting, capacity hotspots,
  neighbor quality, …), config extraction/audit/history, RET management,
  network maps, dashboards, and reporting.
- Shared shell: NexusCore lobby (`nexuscore_app.py`) hosts the portal-tower
  selector; operators log in once there. Identity is the PrimeNet users database
  (`ncm_users.db`) with a shared `nexus_session` cookie (optional
  `NEXUS_COOKIE_DOMAIN` for subdomains). Each user has a portal allow-list
  (Admin Panel → Portals). In-portal RBAC stays inside each portal.

In industry terms (TM Forum eTOM/ODA): PrimeNet covers **network performance
management, configuration management, and part of fault management** — the
hardest corner of OSS to build. Everything else is still open.

## 2. The complete operator platform — domain map

| Domain | Mainstream functions | NexusCore status |
|---|---|---|
| **Network / OSS** | Performance, fault, configuration, SON, inventory, service provisioning | **Strong** via PrimeNet; missing network inventory and service provisioning |
| **BSS — revenue** | Billing, charging, rating, invoicing, payments | Not started |
| **BSS — customer** | CRM, ordering, product catalog, customer self-care | Not started (Sales portal is a placeholder) |
| **Service assurance** | Ticketing, SLA management, customer-facing incident flows | Not started (Support portal is a placeholder) |
| **ISP / access operations** | Subscriber management (RADIUS/PPPoE/FTTH), CPE management, IP address management | Not started — implied by the "ISP" half of the tagline |
| **Field & workforce** | Work orders, dispatch, site access, drive tests | Seeds exist (drive test viewer, task scheduler) |
| **Business intelligence** | Cross-domain KPIs, executive dashboards | Partial (Power BI gallery, reports) |

## 3. Portal-to-domain assignments

The portal tower is the product structure. Each portal owns one or more
domains:

| Portal | Product name | Domains | Notes |
|---|---|---|---|
| **Engineering** | **PrimeNet** | Network/OSS, field & workforce seeds | Exists. Keeps the PrimeNet sub-brand. |
| **Marketing** | **NexPulse** | Campaigns, offers, audiences, consent | Built first as the reference portal: it carries the shared portal scaffold (shell, RBAC, provider seam) the others inherit. |
| **Support** | **NexResolve** | Service assurance, ticketing | Consumes PrimeNet fault/health data over an API. |
| **Sales** | **NexArpu** | BSS-customer (CRM, ordering, catalog) | Reads the NexPulse offer catalog rather than declaring its own. |
| *(future)* **ISP Operations** | Subscriber/CPE/IPAM | Add as a tower level when scoped. |
| *(future)* **Billing** | BSS-revenue | Last; consider buying/integrating instead of building. |

## 4. Architecture rules

PrimeNet's single-app Flask + SQLite design is excellent for the Engineering
Portal and stops there. BSS workloads need isolation from heavy PM ingestion.
The rules:

1. **NexusCore is the umbrella, not a monolith.** Each portal is a separately
   deployable application (own process / Docker service). Entry points:
   `nexuscore_app.py`, `primenet_app.py`, `nexpulse_app.py`. New portals do
   **not** become PrimeNet blueprints.
2. **Central identity + portal allow-list.** Operators authenticate once at
   NexusCore against the PrimeNet users database (`ncm_users.db` /
   `database_enhanced`). All platforms share the `nexus_session` cookie
   (set `NEXUS_COOKIE_DOMAIN=.your.domain` for cross-subdomain SSO; leave empty
   on localhost). Each user has an `allowed_portals` list (`primenet`,
   `nexpulse`, …) managed in Admin Panel. Portals do **not** own separate login
   accounts. Domain data stores remain separate — only identity is shared.
3. **One design system.** The constellation/tower theme, NexusCore branding,
   and shared UI conventions (`docs/FRONTEND_THEME.md`) apply to every portal.
   PrimeNet keeps its own sub-brand inside the Engineering Portal.
4. **Separate data stores per domain.** No portal reads another portal's
   database directly. Cross-portal data flows through explicit APIs (e.g.
   Support pulls degraded-cell lists from a PrimeNet API, never from its
   SQLite files).
5. **The tower is the contract.** Adding a portal = adding a tower level with
   an owner domain, not adding links into an existing portal's navigation.

## 5. Build order (value per effort)

0. **Marketing Portal (NexPulse) — done first, by decision.** Reference portal for
   shell, portal-local RBAC, entity lifecycles, audit trail, and the provider
   seam. Runs as `nexpulse_app.py` with its own users DB. Support and Sales
   inherit the portal scaffold rather than re-deriving it under delivery pressure.
1. **Support Portal — service assurance.** Smallest leap, biggest integration
   story: auto-create tickets from PrimeNet fault/health signals ("cell X
   degraded → ticket"), manual tickets, assignment, SLA timers, and a simple
   customer-impact view.
2. **ISP subscriber management.** RADIUS/subscriber/CPE tooling; closest to the
   existing network-data skill set and high daily-operations value.
3. **Sales / CRM.** Accounts, pipeline, product catalog, ordering.
4. **Billing — last.** Most regulated, least forgiving. Prefer integrating an
   existing billing system behind a NexusCore portal over building one.

PrimeNet itself keeps evolving in parallel (optimization suite, RNO workflows)
— it is the anchor tenant, not a finished wing.

## 6. Naming

- **NexusCore** — the platform: login, portal tower, shared services, brand.
- **PrimeNet** — the Engineering Portal's product name only.
- **NexPulse** — Marketing Portal. **NexArpu** — Sales Portal.
  **NexResolve** — Customer Support Portal.
- A portal's tower level keeps the domain label ("Marketing"); the product name
  is the badge on the card and the brand inside the portal.
