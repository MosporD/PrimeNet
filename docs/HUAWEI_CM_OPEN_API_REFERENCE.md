# Huawei U2020 / MAE CM Open API reference

> **Sources:**
> - *U2020 V300R019C10 Open API Development Guide (For CN)* Issue 01 (2019-11-05)
> - *iMaster MAE-Access V100R021C10 Open API Developer Guide (Wireless Network)* Issue 01 (2021-08-26)
>
> **PrimeNet:** `HUAWEI_CM_API_STYLE=wireless` (RAN/eNodeB) or `cn` (core network U2020)

---

## 1. Which API stack?

Huawei exposes **two different northbound REST families** on U2020/MAE:

| Style | `.env` | Default port | Use case |
|-------|--------|--------------|----------|
| **Wireless / RAN** | `HUAWEI_CM_API_STYLE=wireless` | `31943` or `31127` | LTE/NR eNodeB MML (`LST CELL`, …) |
| **CN (Core Network)** | `HUAWEI_CM_API_STYLE=cn` | `31127` | VNF/CGP MML **script tasks** |

Zain Jo RAN CM extraction should use **`wireless`** unless you are on the CN U2020 guide path.

---

## 2. Interconnection (both stacks)

| Parameter | Typical value |
|-----------|---------------|
| Host | U2020 floating IP (e.g. `10.119.10.104`) |
| Open API port | **`31127`** (document default) |
| Web UI port | `31943` (not always the same as Open API) |
| User | Third-party / NBI user (not personal OSS account) |
| Max concurrent API sessions | 5 (CN guide) |
| API response timeout | 300 s (CN guide) |

Create user: *Common → Security → User Management* → Type **Third-party** → role **NBI User Group** → grant **MML command groups** for wireless.

---

## 3. Wireless / RAN API (`wireless`)

### 3.1 Login

```http
PUT /api/rest/securityManagement/v1/oauth/token
Content-Type: application/json

{
  "grantType": "password",
  "userName": "<user>",
  "value": "<password>"
}
```

Response `accessSession` → header `X-Auth-Token` on all calls.

### 3.2 Single MML command

```http
POST /api/rest/mmlManagement/v1/command
X-Auth-Token: <token>

{
  "command": "LST CELL:;",
  "neNames": ["eNodeB_001"]
}
```

Limits: ≤100 NEs, 10 MB response, 15 concurrent requests.

### 3.3 MML batch script (multipart upload)

Optional legacy path for >100 NEs in one script. Many U2020 builds only accept the
``file`` form field (extra fields like ``taskName`` / ``secretKey`` return retCode
90001 "Parameter … does not exist"). **PrimeNet defaults to chunked single-command
calls** (≤100 NEs per request) instead of this API.

```
POST /api/rest/mmlManagement/v1/tasks
GET  /api/rest/mmlManagement/v1/tasks/{taskId}/status
GET  /api/rest/mmlManagement/v1/tasks/{taskId}/result
DELETE /api/rest/mmlManagement/v1/tasks/{taskId}
```

Script line format: `LST VER:; {NE1,NE2}`

### 3.4 Topology cells

```http
POST /api/rest/resourceManagement/v1/topocellsinfo
{ "fdns": ["NE=1201"] }
```

≤500 FDNs per request.

### 3.5 Bulk CM (not in wireless guide body)

JSON example references:

`/api/rest/configurationManagement/v1/bulkCM/exportJobs/{id}`

Full bulk export spec is **not** in either guide — needs separate CM northbound doc if enabled on your U2020.

---

## 4. CN U2020 API (`cn`) — from your docx

### 4.1 Create token (§3.1)

```http
POST /rest/cnopenapi-sm/v1/tokens
Content-Type: application/json

{
  "auth": {
    "identity": {
      "password": {
        "user": {
          "name": "northAPIUser",
          "password": "Changeme_123"
        }
      },
      "methods": ["password"]
    }
  }
}
```

- Success: HTTP **201**
- Token in response header **`X-Auth-Token`** (also JSON body with `token`, `roa_rand`, `expires_at` in minutes)
- Errors: `error_code` 1 = default password; 2 = bad credentials (HTTP 403)

### 4.2 MML script execution task (§3.7.1)

**Important:** CN API does **not** accept inline MML in JSON. You must host the `.txt` script at an **HTTPS URL** U2020 can reach.

```http
POST /rest/cnopenapi-config/v1/mml-script-task
X-Auth-Token: <token>

{
  "mml_script_path": "https://<your-server>/test.txt",
  "serial": "false",
  "stop_when_error": "false",
  "start_number": "1",
  "client_ip": "10.52.29.23"
}
```

| Parameter | Description |
|-----------|-------------|
| `mml_script_path` | HTTPS URL to `.txt` script (filename: letters/numbers only) |
| `serial` | `true` = sequential; `false` = concurrent NE execution (faster) |
| `stop_when_error` | `true` = stop on first failure |
| `client_ip` | **Mandatory** — caller IP for audit logs |

**Response (success):**

```json
{
  "error_code": 0,
  "error_desc": "",
  "task_id": "104",
  "result_file": "/export/home/sysm/ftproot/itf_n/nms_mml_server/result/test_....rst"
}
```

Only **one** MML script task at a time on U2020.

### 4.3 Query task status (§3.7.2)

```http
GET /rest/cnopenapi-config/v1/mml-script-task/{task-id}
X-Auth-Token: <token>
```

```json
{
  "status": "Success",
  "error_code": 0,
  "error_desc": ""
}
```

| status | Meaning |
|--------|---------|
| `Running` | In progress |
| `Success` | Done — fetch `result_file` via **FTP** |
| `Failed` | Task failed |

### 4.4 CN vs wireless — PrimeNet mapping

| Step | Wireless | CN |
|------|----------|-----|
| Auth | `PUT …/oauth/token` | `POST …/cnopenapi-sm/v1/tokens` |
| Run MML | JSON `command` + `neNames` | HTTPS script URL + poll + FTP result |
| PrimeNet module | `HuaweiCmClient.run_mml()` | `create_cn_mml_script_task()` + `wait_for_cn_mml_script_task()` |

---

## 5. Environment variables

```env
# RAN (typical for eNodeB CM)
HUAWEI_CM_API_STYLE=wireless
HUAWEI_CM_HOST=10.119.10.104
HUAWEI_CM_PORT=31127
HUAWEI_CM_USER=<nbi_user>
HUAWEI_CM_PASSWORD=<password>
HUAWEI_CM_VERIFY_SSL=0

# CN-only extras
# HUAWEI_CM_API_STYLE=cn
# HUAWEI_CM_CLIENT_IP=10.x.x.x
# HUAWEI_CM_SCRIPT_BASE_URL=https://your-server/scripts/
```

Falls back to `HUAWEI_PM_*` when `HUAWEI_CM_*` unset.

---

## 6. PrimeNet implementation status

| Feature | Wireless | CN |
|---------|----------|-----|
| Login | ✅ | ✅ |
| Single MML → Excel | ✅ | N/A (use script task) |
| MML batch (multipart) | ✅ | N/A |
| CN script task create/poll | — | ✅ |
| FTP result download | — | ❌ (needs SFTP/FTP config) |
| Topology cells | ✅ | — |
| NE discovery (FM alarms → meName) | ✅ | — |
| MO column probe (LST on sample NE) | ✅ | — |
| NE picker (DB + U2020 sync) | ✅ | — |

---

## 7. NE naming (important)

U2020 MML ``neNames`` must be OSS **meName** values, not PrimeNet metadata ``site_name`` labels.

| PrimeNet metadata | U2020 meName (example) |
|-------------------|------------------------|
| `1006-Zawahrah_End_PD_Fiber_TASC` | `1006-ULT_Zawahrah_End_PD_Fiber_TASC` |
| `1005-Zarqa_Madina_Monawara_PD_EBand_TASC_O` | `1005-ULT_Zarqa_Madina_Monawara_PD_EBand_TASC_O` |

PrimeNet discovers meNames from **FM current alarms** (`GET /api/rest/faultSupervisonManagement/v1/alarms?dataType=CURRENT`) and maps metadata ``site_id`` → meName by numeric prefix.

API: ``POST /api/cm-extractor/huawei/discover`` or **Sync NEs from U2020** in the CM Extractor UI.

---

## 8. Recommended next steps

1. Confirm with ops: **wireless** vs **cn** on `10.119.10.104`
2. For wireless: NBI user + MML groups + test `LST CELL:;`
3. For CN: HTTPS script hosting + FTP path for `result_file`
4. If you have a **RAN Open API** PDF (non-CN), share it — may add `bulkCM` export
