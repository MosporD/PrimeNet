# PrimeNet — Server Network Policy

**Document purpose:** Permanent firewall / proxy allowlist for deploying, updating, and operating PrimeNet (`MosporD/PrimeNet`).

**Audience:** IT / network security, platform ops, telecom engineering.

**Last reviewed:** 2026-07-23

---

## 1. Overview

PrimeNet is a Flask telecom platform for radio network performance and configuration management (Nokia + Huawei, 2G–5G).

Traffic falls into four classes:

| Class | Direction | Who needs it |
|-------|-----------|--------------|
| **Deploy & update** | Server → Internet | Build host, prod server (git, PyPI, Docker) |
| **ETL pipeline** | Server → OSS / SFTP / vendor APIs | Scheduler + pull scripts |
| **Application runtime** | Users → PrimeNet server | Browser → app on port 8000 (prod) or 5000 (dev) |
| **Map / embed UI** | User browser → CDNs & tile servers | Workstations running the web UI |

**Important:** Most dashboard “external tool” links are **browser-only bookmarks** for operators. The Linux server does **not** call those URLs unless explicitly noted.

---

## 2. Git — source control (pull / push)

| Purpose | URL / host | Port | Protocol |
|---------|------------|------|----------|
| Git remote | `https://github.com/MosporD/PrimeNet` | 443 | HTTPS |
| GitHub | `github.com` | 443 | HTTPS |
| Archive / codeload | `codeload.github.com` | 443 | HTTPS |
| Raw content (optional) | `raw.githubusercontent.com` | 443 | HTTPS |

**Tools:** `git` (required), `gh` GitHub CLI (optional, for PRs).

**Typical commands:**
```bash
git clone https://github.com/MosporD/PrimeNet.git
git pull origin main
git push origin main
```

---

## 3. Python dependencies (install & future updates)

All Python packages are installed from **PyPI**.

| Purpose | URL | Port |
|---------|-----|------|
| Package index | `https://pypi.org` | 443 |
| Package files (wheels) | `https://files.pythonhosted.org` | 443 |

**Install:**
```bash
pip install -r requirements.txt
```

**Python version:** 3.11 (matches `Dockerfile` and `pyproject.toml`).

### 3.1 Current production libraries (`requirements.txt`)

| Package | Version constraint | Role |
|---------|-------------------|------|
| Flask | 3.0.0 | Web application |
| Werkzeug | 3.0.1 | HTTP / WSGI utilities |
| gunicorn | 22.0.0 | Production app server |
| openpyxl | 3.1.2 | Excel read/write |
| pandas | 2.1.4 | PM & neighbor ingest |
| lxml | 5.1.0 | XML parsing |
| paramiko | 3.4.0 | SFTP (Nokia/Huawei/metadata pulls) |
| APScheduler | 3.10.4 | Background scheduler |
| python-dotenv | 1.0.1 | `.env` configuration |
| cryptography | ≥42.0.0 | Encryption (sessions, vendor credentials) |
| defusedxml | 0.7.1 | Safe XML parsing |
| openai | ≥1.40.0 | Parameter Dictionary AI (**optional**) |
| psutil | ≥5.9.0 | Resource monitoring |

### 3.2 Likely future / dev-only packages

| Package | When needed |
|---------|-------------|
| `ruff` | Linting (referenced in `pyproject.toml`, not in `requirements.txt`) |
| `pytest` | Automated tests (if added) |
| `psycopg2-binary` or `psycopg[binary]` | Only if PostgreSQL support is re-enabled |

**Note:** Application PM/KPI storage is **SQLite** under `databases/` today. PostgreSQL env vars may exist locally but are not the active backend in current code.

---

## 4. Docker deployment (recommended production)

| Purpose | URL / host | Port |
|---------|------------|------|
| Docker Hub registry | `registry-1.docker.io` | 443 |
| Docker Hub auth | `auth.docker.io` | 443 |
| Base image | `docker.io/library/python:3.11-slim-bookworm` | 443 |

**Inside image build (Debian Bookworm apt):**

| Purpose | URL | Port |
|---------|-----|------|
| Debian packages | `deb.debian.org` | 443 |
| Debian security | `security.debian.org` | 443 |

**OS packages installed in image:** `libxml2`, `libxslt1.1`, `util-linux`

**Compose stack:** `web` (port 8000) + `scheduler` (pipeline jobs). See `docker-compose.yml`.

---

## 5. Ubuntu bare-metal (alternative to Docker)

Use **Ubuntu 22.04 LTS** or **24.04 LTS**.

| Purpose | URL | Port |
|---------|-----|------|
| Ubuntu packages | `archive.ubuntu.com` | 443 |
| Ubuntu security | `security.ubuntu.com` | 443 |
| Docker CE (if installing Docker on host) | `download.docker.com` | 443 |

**Suggested packages:**
```bash
sudo apt update
sudo apt install -y git python3.11 python3.11-venv python3-pip \
  libxml2 libxslt1.1 build-essential
```

---

## 6. Server outbound — ETL & vendor integration

These destinations must be reachable **from the PrimeNet host or scheduler container**.

### 6.1 SFTP — performance & neighbor exports

| System | Host | Port | Protocol | Env vars |
|--------|------|------|----------|----------|
| Nokia PM + neighbor | `10.119.219.77` | 22 | SFTP | `NOKIA_PM_HOST`, `NOKIA_PM_USER`, `NOKIA_PM_PASSWORD` |
| Huawei PM + neighbor | `10.119.10.104` | 22 | SFTP | `HUAWEI_PM_HOST`, `HUAWEI_PM_USER`, `HUAWEI_PM_PASSWORD` |
| Cell metadata | `192.168.7.207` | 22 | SFTP | `METADATA_HOST`, `METADATA_USER`, `METADATA_PASSWORD` |
| Femto PM | `10.253.92.68` | 22 | SFTP | Hardcoded in pull watcher script |

Neighbor remote paths (Nokia default SFTP tree):
```
/d/oss/global/var/pm/shared/content3/scheduler/exportCustom/Malek/Performance Project Neighbor/{2G,3G,4G}
```
Override with `NOKIA_NEIGHBOR_ROOT` or per-RAT `NOKIA_NEIGHBOR_DIR_*` if paths differ.

### 6.2 Nokia NetAct CM / FM (HTTPS)

| System | Host | Port | Protocol | Env vars |
|--------|------|------|----------|----------|
| CM Open API / login | `login.rc02.netact.zainjo.net` | 443 | HTTPS | `NOKIA_CM_HOST`, `NOKIA_CM_USER`, `NOKIA_CM_PASSWORD` |
| FM OAuth (Keycloak) | same cluster | 10448 | HTTPS | `NOKIA_FM_CLIENT_ID`, `NOKIA_FM_CLIENT_SECRET` |

### 6.3 Huawei U2020 CM northbound (HTTPS)

| System | Host | Port | Protocol | Env vars |
|--------|------|------|----------|----------|
| CM / MML API | `10.119.10.4` | 31127 | HTTPS | `HUAWEI_CM_HOST`, `HUAWEI_CM_PORT`, `HUAWEI_CM_USER`, `HUAWEI_CM_PASSWORD` |

### 6.4 Optional server-side external APIs

| Feature | URL | Required when |
|---------|-----|---------------|
| Elevation (primary) | `https://api.open-meteo.com/v1/elevation` | Network map elevation cache |
| Elevation (fallback) | `https://api.opentopodata.org/v1/srtm90m` | Reports module |
| OpenAI | `https://api.openai.com/v1` | `OPENAI_API_KEY` set (Parameter Dictionary AI) |
| License service | Value of `NCM_LICENSE_SERVER_URL` | Remote activation enabled |

---

## 7. Scheduler cadence (pipeline load profile)

Understanding load helps size firewall rules and DB maintenance windows.

| Job | Default schedule | What it does |
|-----|------------------|--------------|
| PM hourly ingest | Every `RAW_PULL_INTERVAL_HOURS` (default **1 h**) | SFTP pull + SQLite PM/groups load |
| PM daily ingest | `DAILY_PULL_HOUR:05` (default **07:05**) | Daily scope pull + load |
| **Neighbor sync** | Every `NEIGHBOR_PULL_INTERVAL_HOURS` at `:NEIGHBOR_PULL_CRON_MINUTE` (default **3 h at :30**) | Neighbor SFTP pull + **full replace** of neighbor SQLite tables |
| Remote watcher | Every `WATCH_POLL_INTERVAL_SEC` (default **30 min**) | Probe remotes, gap-fill PM/metadata |
| Metadata | With hourly / watcher cycles | Full replace of `cells_*` metadata tables |

**Neighbor sync is intentionally offset from hourly PM ingest** to reduce concurrent SQLite load.

Env vars:
```env
NEIGHBOR_PULL_INTERVAL_HOURS=3
NEIGHBOR_PULL_CRON_MINUTE=30
NCM_DISABLE_NEIGHBOR_SCHEDULER=0   # set 1 to disable neighbor job
```

---

## 8. User browser outbound — maps & embeds

Required on **operator workstations**, not on the Linux server (unless traffic is proxied through the server).

### 8.1 Map modules (Leaflet)

Used by: Network Map, Neighbor Analysis, Cell Heatmap, Conflict Map, Drive Test Viewer.

| Purpose | URL / pattern |
|---------|---------------|
| Leaflet CDN | `https://unpkg.com` |
| OpenStreetMap | `https://*.tile.openstreetmap.org` |
| OSM HOT | `https://*.tile.openstreetmap.fr` |
| Esri imagery / terrain | `https://server.arcgisonline.com` |
| Carto dark basemap | `https://*.basemaps.cartocdn.com` |

Content-Security-Policy in `app.py` already allows these for browser clients.

### 8.2 Power BI module

| Purpose | URL |
|---------|-----|
| Production embed | `https://app.powerbi.com` |
| MSIT / test | `https://msit.powerbi.com` |

### 8.3 Dashboard external tool links (browser bookmarks)

Examples in `templates/dashboard.html` — allow on **corporate user network**, not server egress:

- `https://login.rc02.netact.zainjo.net`
- `https://10.119.10.4:31943`, `https://10.119.10.104:31943` (Huawei web SSO)
- `https://zainsites.jo.zain.com`
- `https://services.jo.zain.com`
- `https://gis.jo.zain.com`
- `https://doc.networks.nokia.com`
- Other Zain internal portals listed on the dashboard

---

## 9. Infrastructure (non-HTTP)

| Service | Requirement |
|---------|-------------|
| **DNS** | Resolve all hosts in sections 2–6 |
| **NTP** | Accurate time for cron jobs (neighbor :30, daily 07:05, etc.) |
| **PrimeNet HTTP** | Inbound to server on **8000** (Docker prod) or **5000** (dev) |
| **PostgreSQL** | Only if re-enabled; current app uses local SQLite files |

---

## 10. Consolidated allowlist (IT copy/paste)

### 10.1 Server — HTTPS outbound (443)

```
github.com
codeload.github.com
raw.githubusercontent.com
pypi.org
files.pythonhosted.org
registry-1.docker.io
auth.docker.io
deb.debian.org
security.debian.org
archive.ubuntu.com
security.ubuntu.com
download.docker.com
login.rc02.netact.zainjo.net
api.open-meteo.com              # optional
api.opentopodata.org            # optional
api.openai.com                  # optional
```

### 10.2 Server — SFTP outbound (22)

```
10.119.219.77      # Nokia PM + neighbor
10.119.10.104      # Huawei PM + neighbor
192.168.7.207      # Metadata
10.253.92.68       # Femto PM
```

### 10.3 Server — vendor HTTPS (internal)

```
10.119.10.4:31127                    # Huawei CM northbound
login.rc02.netact.zainjo.net:443     # Nokia CM
login.rc02.netact.zainjo.net:10448   # Nokia FM OAuth (if used)
```

### 10.4 User browsers — map / CDN (443)

```
unpkg.com
*.tile.openstreetmap.org
*.tile.openstreetmap.fr
server.arcgisonline.com
*.basemaps.cartocdn.com
app.powerbi.com
msit.powerbi.com                   # optional — Power BI test tenant
```

### 10.5 Inbound to PrimeNet server

```
TCP 8000   # production (docker compose)
TCP 5000   # development (python app.py)
```

---

## 11. Explicitly NOT required on the server

- **npm / nodejs.org** — no Node build in production; Chart.js is vendored under `static/`
- **Map tile CDNs** — fetched by user browsers, not the backend
- **Dashboard bookmark URLs** — operator browser navigation only
- **Huawei/Nokia operator web UIs** — unless CM Extractor or RET modules call them server-side (CM API hosts in §6 are the server-side exceptions)

---

## 12. Security notes

1. **Secrets live only in `.env`** — never commit `.env` to git. Includes SFTP passwords, `FLASK_SECRET_KEY`, CM/FM credentials, optional `OPENAI_API_KEY`.
2. **`FLASK_SECRET_KEY`** must be stable across restarts for sessions and encrypted RET vendor credentials.
3. **SFTP pulls clear raw folders** before download; neighbor SQLite is **full-replaced** each neighbor sync cycle.
4. **KPI query strings** are stripped from access logs in production (`ConciseRequestHandler` in `app.py`).
5. Review this document when adding modules that call new external APIs or CDNs.

---

## 13. Change log

| Date | Change |
|------|--------|
| 2026-07-23 | Initial policy — git, PyPI, Docker, Ubuntu, SFTP/vendor hosts, map CDNs, neighbor 3h/:30 schedule |

---

## 14. References (in-repo)

| Topic | Path |
|-------|------|
| Architecture | `docs/ARCHITECTURE.md` |
| Pipeline entrypoints | `pipeline/orchestrators/` |
| Neighbor sync | `pipeline/orchestrators/orchestrate_neighbor_sync.py` |
| Requirements | `requirements.txt` |
| Docker | `Dockerfile`, `docker-compose.yml` |
| Env template | `.env.example` |
| Agent conventions | `AGENTS.md` |
