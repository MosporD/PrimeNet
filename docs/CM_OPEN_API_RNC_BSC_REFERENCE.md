# Nokia CM Open API — RNC / BSC extraction reference

> **Source:** *MantaRay NM 24R3-NM — CM Open API Web Services* (DN1000149000 Issue 1-0)  
> **Purpose:** Plain-language guide for how the official document says to read 3G RNC and 2G BSC configuration, and how PrimeNet CM Extractor maps to it.

---

## 1. Two REST interfaces (both use HTTP Basic auth)

| Interface | Base path | Used for |
|-----------|-----------|----------|
| **CM Data Repository REST API** | `/netact/cm/open-api/persistency/v1` | Read/write CM via queries, MO lists, parameter reads |
| **CM Operations REST API** | `/netact/cm/open-api/operations/v1` | Start Configurator operations (Provision, Upload, **Import_Export**, Export, …) |

YAML specs (from doc §4.1):

- Persistency: `https://<cluster-host>/netact/cm/open-api/persistency/v1/yaml`
- Operations: `https://<cluster-host>/netact/cm/open-api/operations/v1/yaml`

**Configurations (confId):**

| confId | Meaning |
|--------|---------|
| `1` | Actual (live) network |
| `5` | Reference configuration |
| other | Plan configuration (write workflows) |

---

## 2. Naming conventions the doc uses everywhere

### 2.1 Distinguished names (DN / moId)

DNs are slash-separated paths under PLMN:

```
PLMN-<plmn_instance>/RNC-<rnc_instance>/WBTS-<id>/WCEL-<id>
PLMN-<plmn_instance>/BSC-<bsc_instance>/BAL-<id>
```

Examples from the document:

| Example DN | MO class |
|------------|----------|
| `PLMN-PLMN/RNC-42` | `NOKRNC:RNC` |
| `PLMN-PLMN/RNC-521/WBTS-176` | `NOKRNC:WBTS` |
| `PLMN-clab893/RNC-2520/WBTS-161/WCEL-1` | `NOKRNC:WCEL` |
| `PLMN-PLMN/BSC-479987/BAL-700` | `NOKBSC:BAL` |
| `PLMN-clab893/BSC-54145/BCF-120` | `NOKBSC:BCF` |

**Important:** The numeric suffix after `RNC-` or `BSC-` is the **NetAct instance id** in the PLMN tree — not necessarily the short CM id shown in some MO paths on a live network (e.g. `RNC-12` vs `RNC-2012`).

### 2.2 MO class ids

Format: `<adaptation>:<abbreviation>`

| Scope | Adaptation | Example classes |
|-------|------------|-----------------|
| 3G RNC | `NOKRNC` | `RNC`, `WBTS`, `WCEL`, `ADJI`, `FMCS`, … |
| 2G BSC | `NOKBSC` | `BSC`, `BTS`, `BAL`, `BCF`, … |

Retrieve class lists: `GET …/meta/classes?adaptId=NOKRNC&adaptId=NOKBSC` (§4.4.12).

---

## 3. How the document says to **read** RNC / BSC data (Data Repository API)

The doc does **not** define a single “export whole RNC to Excel” REST call. Reading is a **multi-step pipeline**:

```
meta/classes  →  queryMOLites / query / descendantMOLites  →  getManagedObjects
```

### 3.1 Step A — Find MO instances (MOLites)

#### A1. `POST …/queryMOLites` (§4.4.13)

Search by **MO path** under PLMN. Document REST example for all WCEL under a PLMN:

```json
{
  "confId": 1,
  "moPath": "/NetActCommon:PLMN[instance()=:plmn]//NOKRNC:WCEL",
  "variables": { "plmn": "clab893" }
}
```

Returns:

```json
{
  "result": [
    {
      "moId": "PLMN-clab893/RNC-2520/WBTS-927/WCEL-1",
      "moClass": { "id": "NOKRNC:WCEL", "version": "RNC_VERSION" }
    }
  ]
}
```

**BSC SOAP example (§2.3.3.7)** — descendant path with version variable:

```
// NOKBSC:BAL[ version()=:ver]
variables: { "ver": "S15" }
→ PLMN-PLMN/BSC-479987/BAL-700
```

#### A2. `POST …/query` (§4.4.11)

Parameterized search with **expressions** (scalar params only — lists/structures not supported in MO path):

```json
{
  "confId": 1,
  "moPath": "/NetActCommon:PLMN[instance()=:plmn]//NOKRNC:WBTS as $wbts/WCEL[@CId in (1,21)]",
  "expressions": ["dn()", "$wbts->instance()", "@name", "@CId"],
  "variables": { "plmn": "clab893" }
}
```

#### A3. `POST …/descendantMOLites` (§4.4.10)

When you already know **parent DNs**, fetch descendants of selected classes:

```json
{
  "confId": 1,
  "moIds": [
    "PLMN-clab893/RNC-2520/WBTS-161",
    "PLMN-clab893/RNC-2600/WBTS-946"
  ],
  "moClasses": ["NOKRNC:WCEL", "NOKRNC:ADJI"]
}
```

#### A4. `POST …/moLites` (§4.4.14)

Lookup lite info for known DNs:

```json
{
  "confId": 1,
  "moIds": ["PLMN-clab893/RNC-2520/WBTS-161"]
}
```

#### A5. `getRelatedMOLites` — CHILD relationship (§2.3.3.6 SOAP)

From `PLMN-PLMN` or `PLMN-PLMN/RNC-521`, returns children including `NOKRNC:RNC`, `NOKRNC:WBTS`, etc.

### 3.2 Step B — Read parameters (`POST …/getManagedObjects`, §4.4.15)

**This is the documented way to get full parameter maps.**

Request (REST example uses **child** MOs — WBTS, not root RNC):

```json
{
  "confId": 1,
  "moIds": [
    "PLMN-clab893/RNC-2520/WBTS-161",
    "PLMN-clab893/RNC-2600/WBTS-946"
  ]
}
```

Response shape:

```json
{
  "managedObjects": [
    {
      "moId": "PLMN-clab893/RNC-2600/WBTS-946",
      "moClass": { "id": "NOKRNC:WBTS", "version": "RNC20FP3" },
      "parameters": {
        "WBTSName": "Flexi BTS.1 IP OSPF with one VLAN",
        "name": "IP OSPF with one VLAN …",
        "PtxDPCHmax": -30
      }
    }
  ]
}
```

SOAP BSC example (§2.3.3.3): `getManagedObjects` on `PLMN-PLMN/BSC-479987/BAL-700`.

**Doc note:** If an MO does not exist, there is **no entry** in the result (batch pattern).

### 3.3 Step C — Parameter metadata (`POST …/meta/parameters`, §4.4.16)

Used to discover parameter names, types, ranges — not live values:

```json
{
  "moClasses": [
    { "id": "NOKRNC:ADJG", "version": "RN8.0" },
    { "id": "NOKBSC:ADCE", "version": "S16" }
  ]
}
```

---

## 4. MO path patterns for RNC / BSC (from doc examples)

| Pattern | Meaning |
|---------|---------|
| `/NetActCommon:PLMN[instance()=:plmn]//NOKRNC:WCEL` | All WCEL under one PLMN; bind `:plmn` |
| `/NetActCommon:PLMN[instance()=:plmn]//NOKRNC:WBTS as $wbts/WCEL[…]` | WCEL filtered under WBTS alias |
| `// NOKBSC:BAL[ version()=:ver]` | All BAL matching adaptation version (SOAP style) |

**PLMN variable binding (§2.3.1.1):** When the MO path contains `:plmn`, `:ver`, etc., you **must** supply matching keys in `variables`.

**Doc does not show** using `RNC[instance()=12]` inside REST `queryMOLites` moPath for RNC scope. RNC/BSC scoping in the examples is done via:

- PLMN instance variable, and/or
- DN structure (`PLMN-…/RNC-…/…`), and/or
- Filtering query results by parent DN.

---

## 5. CM Operations API — bulk / file-based export

Section **4.5** worked examples are LTE-centric (LNCEL query → plan → Provision → Upload).  
Section **4.5.2** shows **Export** operation for a Working Set to XLSX with `outputFile` attachment.

For **full configuration dumps**, the document describes **standard Configurator operations** via Operations API (§3.2.3.3, §4.3.3):

1. `GET …/operations/v1/definitions` — list operations and required attributes  
2. `POST …/operations/v1/start` — start operation  
3. Poll `…/statuses?operationIds=…` until `FINISHED` / `FAILED`  
4. Read `…/feedbacks?operationIds=…`  
5. Read `…/attributes?operationIds=…` for output file name  

**Import_Export** (Configurator GUI “Import/Export”) is one such standard operation. Attributes (from live NetAct definitions, not repeated verbatim in the PDF body):

| Attribute | Typical value |
|-----------|----------------|
| `importExportOperation` | `actualExport` |
| `fileFormat` | `RAML2` |
| `DN` | Comma-separated scope, e.g. `PLMN-PLMN/RNC-2012` |
| `fileName` | Output XML name on OMC |
| `classFilterInclude` | Optional, e.g. `*:WCEL` or `*:FMCS,*:WCEL` (not `NOKRNC:WCEL`) |
| `useQualifiedClassAbbreviation` | `true` |

Export file lands on the **NetAct OMC filesystem** (e.g. `/d/oss/global/var/racops/export/`). The REST API starts the job; **retrieving the file requires SFTP/attachment**, not the persistency API.

---

## 6. Documented REST use cases vs RNC/BSC

| Use case (§4.5) | Technology in example | Relevant to RNC/BSC? |
|-----------------|----------------------|----------------------|
| #1 | LNCEL query + plan + Provision + Upload | Pattern only (Operations workflow) |
| #2 | Provision Mass Modification + Export WS | Operations + file transfer pattern |
| #3 | LNCEL + LNCEL_TDD parameter query | Same **query** pattern applies to `NOKRNC:WCEL` etc. |

**All RNC/BSC read examples in the PDF** use **child MO classes** (`WBTS`, `WCEL`, `BAL`, `BCF`) with `queryMOLites` / `getManagedObjects`, not bulk read of root `NOKRNC:RNC` parameters via persistency API.

The plan-write example (§4.4.4.1) shows `NOKRNC:RNC` parameters (`name`, `ActivePRNC`) at `PLMN-clab893/RNC-840` — that is **updating a plan**, not reading actual config via `getManagedObjects` on confId 1.

---

## 7. PrimeNet CM Extractor mapping

### 7.1 Open API extract (UI: “Extract to Excel (Open API)”)

Implements the doc pipeline for selected MO classes + parameters:

| Doc step | PrimeNet |
|----------|----------|
| `meta/classes` | MO class picker (`GET …/nokia/mo-classes`) |
| `meta/parameters` | Parameter checkboxes |
| `queryMOLites` with `//NOKRNC:…` / `//NOKBSC:…` | Built MO paths; site scope via **distName filtering** (`/RNC-2012`, `/BSC-408025`) |
| `getManagedObjects` in batches | Full-MO or selected-parameter export |
| `query` with `@param` | Selected parameters (≤250); falls back to full MO if more |

**RNC/BSC path rule (aligned with doc descendant examples):** use `//NOKRNC:WCEL` under PLMN, **not** `RNC[instance()=…]` in the moPath. Scope is applied after query via DN needles.

### 7.2 Bulk export (UI: “Bulk export (CM Operations)”)

Implements §4.3 Operations workflow + Configurator **Import_Export actualExport**:

| Step | PrimeNet |
|------|----------|
| Resolve DN scope | `PLMN-PLMN/RNC-2012` (NetAct PLMN instance, not short `12`) |
| `POST …/operations/v1/start` | `nokia_operations_client.start_operation('Import_Export', …)` |
| Poll statuses / feedbacks | `wait_for_operation()` |
| SFTP from OMC | `NOKIA_PM_*` or `NOKIA_CM_SSH_*` → `/d/oss/global/var/racops/export/` |
| RAML/XML → Excel | `XMLToExcelConverter` (`ncm_core.py`) |

### 7.3 When to use which (per doc intent)

| Goal | Doc-recommended approach | PrimeNet |
|------|-------------------------|----------|
| Specific MO classes / parameters for one RNC | `queryMOLites` → `getManagedObjects` | Open API extract |
| Parameter search / filters | `query` with expressions | Open API extract (preview) |
| Full controller dump (all MOs, all params) | Configurator Import_Export (Operations) | Bulk export |
| Root `NOKRNC:RNC` parameters on actual conf | **Not shown** as persistency read pattern | Bulk export or read child MOs |

---

## 8. Zain Jo / live NetAct notes (from PrimeNet probing)

These are **deployment-specific** but explain common confusion:

| Topic | Observation |
|-------|-------------|
| PLMN prefix | `PLMN-PLMN` (not `PLMN-clab893`) |
| RNC12 site id | PrimeNet DB: `2012`; NetAct PLMN instance: `2012`; short CM id: `12` |
| Import_Export DN | Must use `PLMN-PLMN/RNC-2012` — `RNC-12` exports **0 objects** |
| Open API root RNC | `getManagedObjects` on `PLMN-PLMN/RNC-12` returns empty parameters on this network |
| SFTP host | Export files on OMC (`10.119.219.77`), **not** CM REST login hostname |
| Child MOs | `NOKRNC:WCEL`, `NOKRNC:WBTS`, etc. return full parameters via Open API |

---

## 9. Quick copy-paste examples (adapt for your PLMN)

### 9.1 List all WCEL for RNC 2012 (Open API)

**1. queryMOLites**

```http
POST /netact/cm/open-api/persistency/v1/queryMOLites
Content-Type: application/vnd.nokia-query-mos-request-v1+json

{
  "confId": 1,
  "moPath": "/NetActCommon:PLMN//NOKRNC:WCEL"
}
```

Then filter results where `moId` contains `/RNC-2012/`.

**2. getManagedObjects** (batch moIds from step 1)

```http
POST /netact/cm/open-api/persistency/v1/getManagedObjects
Content-Type: application/vnd.nokia-moids-request-v1+json

{
  "confId": 1,
  "moIds": ["PLMN-PLMN/RNC-2012/WBTS-…/WCEL-…"]
}
```

### 9.2 Full RNC dump (Operations)

```http
POST /netact/cm/open-api/operations/v1/start
Content-Type: application/vnd.nokia-operation-start-v1+json

{
  "operationName": "Import_Export",
  "operationAlias": "RNC 2012 full export",
  "operationAttributes": {
    "importExportOperation": "actualExport",
    "fileFormat": "RAML2",
    "DN": "PLMN-PLMN/RNC-2012",
    "fileName": "rnc_2012_export.xml",
    "useQualifiedClassAbbreviation": "true"
  }
}
```

Then poll statuses/feedbacks, SFTP the file from the OMC export directory.

---

## 10. API limits mentioned in the doc

- **Overload protection** on heavy queries (OpenAPIMOQueryTimeout)
- **Batch pattern** — missing MOs omitted silently from getManagedObjects results
- **MO path query** — no list/structure parameters in `@param` expressions
- **Mass operations** — use variable binding and batching (§2.3.1.1.2, §2.3.1.2)
- Operations feedback pagination — `limit` max 500 recommended (§4.3.8)

---

## 11. References in repository

| File | Role |
|------|------|
| `core/cm_extractor/nokia_client.py` | Data Repository REST client |
| `core/cm_extractor/nokia_operations_client.py` | Operations REST client |
| `core/cm_extractor/nokia_semantics.py` | MO paths, query/export logic |
| `core/cm_extractor/nokia_bulk_export.py` | Import_Export orchestration |
| `core/cm_extractor/site_catalog.py` | RNC/BSC site ids → export DNs |
| Original PDF | `cm_open_api_web_services.pdf` (MantaRay NM 24R3-NM) |
