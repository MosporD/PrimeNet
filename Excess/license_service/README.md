# PrimeNet License Service

Standalone service that issues **RSA-signed** monthly license tokens. PrimeNet verifies tokens locally using the **public key only** — the signing private key never leaves this service.

## Setup

```powershell
cd license_service
pip install -r requirements.txt
python generate_keys.py
copy .env.example .env
# Edit .env — set LICENSE_OPERATOR_PASSWORD
python app.py
```

Service listens on `http://0.0.0.0:5055` by default.

## PrimeNet client configuration

On each PrimeNet installation (`.env` or environment):

```env
NCM_LICENSE_SERVER_URL=http://YOUR-LICENSE-SERVER:5055
NCM_LICENSE_PUBLIC_KEY_PATH=C:\path\to\public.pem
```

Copy `license_service/data/public.pem` to the PrimeNet host. Do **not** copy `private.pem`.

Optional:

```env
NCM_LICENSE_INSTANCE_ID=my-datacenter-primenet-1
NCM_LICENSE_ONLINE_VERIFY_HOURS=24
NCM_LICENSE_OFFLINE_GRACE_HOURS=72
```

## API

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check |
| `GET /v1/public-key` | PEM public key (optional; prefer deploying `public.pem`) |
| `POST /v1/unlock` | `{password, instance_id}` → signed `token` |
| `POST /v1/verify` | `{token, instance_id}` → online validity + revocation |
| `POST /v1/admin/revoke` | Revoke an `instance_id` (requires `LICENSE_API_TOKEN`) |

## Revoke an installation

```powershell
curl -X POST http://localhost:5055/v1/admin/revoke `
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" `
  -H "Content-Type: application/json" `
  -d "{\"instance_id\": \"hostname-abc123\"}"
```

PrimeNet will lock on the next online verify (within `NCM_LICENSE_ONLINE_VERIFY_HOURS`).

## Docker (optional)

```dockerfile
FROM python:3.11-slim
WORKDIR /svc
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV LICENSE_DATA_DIR=/data
VOLUME /data
EXPOSE 5055
CMD ["python", "app.py"]
```

Mount `/data` for keys and `licenses.db`. Set `LICENSE_OPERATOR_PASSWORD` via secrets.
