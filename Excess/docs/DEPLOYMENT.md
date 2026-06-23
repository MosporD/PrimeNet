# PrimeNet — Production deployment (Docker)

This guide covers running PrimeNet in containers on a Linux server for **10+ concurrent users**.

## Architecture

| Service | Role |
|---------|------|
| **web** | Gunicorn (multi-threaded workers), HTTP API and UI |
| **scheduler** | SFTP pull watcher and background ingest (separate process) |
| **Volume `primenet-data`** | SQLite DBs, sync downloads, raw KPI headers (`/data`) |

The web tier does **not** run the sync scheduler (avoids duplicate jobs and SQLite lock contention with Gunicorn workers).

## Quick start

```bash
cp .env.example .env
# Edit .env: FLASK_SECRET_KEY, bootstrap admin password, SFTP credentials

docker compose up -d --build
```

Open: `http://<server-ip>:8000/dashboard`

Health check: `http://<server-ip>:8000/health`

## Required environment variables

| Variable | Description |
|----------|-------------|
| `FLASK_SECRET_KEY` | Long random string; **required** for stable sessions |
| `NCM_BOOTSTRAP_ADMIN_PASSWORD` | Initial admin password (only when users table is empty) |
| SFTP vars | `NOKIA_PM_*`, `HUAWEI_PM_*`, `METADATA_*` — see `.env.example` |

Generate a secret:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## Production tuning (10+ users)

In `.env` or `docker-compose.yml`:

```env
GUNICORN_WORKERS=2
GUNICORN_THREADS=4
GUNICORN_TIMEOUT=120
PM_SYNC_MODE=incremental
```

Behind HTTPS reverse proxy (nginx/Traefik), ensure the proxy sets:

```
X-Forwarded-Proto: https
```

Session cookies already honor this for `Secure` flag.

Optional:

```env
NCM_ENABLE_HSTS=1
```

## Data persistence

All runtime data lives under **`NCM_DATA_ROOT`** (default `/data` in the container):

- `databases/` — SQLite files
- `sync_downloads/` — SFTP staging
- `raw/KPIs/` — KPI header DB

Back up the Docker volume regularly:

```bash
docker run --rm -v primenet-data:/data -v $(pwd):/backup alpine \
  tar czf /backup/primenet-data-$(date +%Y%m%d).tar.gz -C /data .
```

### Migrating existing data from a dev machine

1. Stop the app.
2. Copy your local `databases/`, `sync_downloads/`, and `raw/` into the volume:

```bash
docker compose down
docker volume create primenet-data  # if new
docker run --rm -v primenet-data:/data -v /path/to/local/project:/src alpine \
  sh -c "cp -a /src/databases /src/sync_downloads /src/raw /data/ 2>/dev/null; chown -R 1000:1000 /data"
docker compose up -d
```

## Operations

| Task | Command |
|------|---------|
| Logs (web) | `docker compose logs -f web` |
| Logs (scheduler) | `docker compose logs -f scheduler` |
| Restart | `docker compose restart web` |
| DB audit | `docker compose exec web runuser -u primenet -- python scripts/audit_sqlite_databases.py` |
| Bootstrap only | `docker compose run --rm web bootstrap` |
| Web only (no sync) | `docker compose up -d web` |

## Reverse proxy (nginx example)

```nginx
server {
    listen 443 ssl;
    server_name primenet.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        client_max_body_size 100m;
        proxy_read_timeout 120s;
    }
}
```

## Image build (CI / registry)

```bash
docker build -t your-registry/primenet:1.0.0 .
docker push your-registry/primenet:1.0.0
```

On the server, set `image:` in compose instead of `build:`.

## Local development (non-Docker)

Unchanged workflow:

```bash
python app.py
```

Scheduler and live PowerShell logger run automatically unless:

```env
NCM_DISABLE_SCHEDULER=1
NCM_DISABLE_LIVE_LOGGER_TERMINAL=1
```

## Troubleshooting

| Symptom | Likely cause | Action |
|---------|----------------|--------|
| `database is locked` | Sync + heavy queries overlap | Use incremental PM mode; ensure only one **scheduler** container |
| 503 on `/health` | DB volume permissions | `chown -R 1000:1000` on host mount path |
| Sessions reset on restart | Missing `FLASK_SECRET_KEY` | Set in `.env` |
| Stale KPI data | Scheduler down | `docker compose ps` — start `scheduler` service |
| 413 on upload | Body > 100MB | Expected limit in `app.py` |

## Security checklist

- [ ] Strong `FLASK_SECRET_KEY` and admin password in secrets manager / `.env` (not in git)
- [ ] `.env` never committed
- [ ] HTTPS in front of the container
- [ ] SFTP credentials rotated if previously in source control
- [ ] Firewall: only proxy port public; SFTP egress allowed from scheduler host
