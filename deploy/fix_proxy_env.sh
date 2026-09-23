#!/usr/bin/env bash
# Idempotent: align .env for single-host nginx path proxy.
# Run on the server after git pull:  bash deploy/fix_proxy_env.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${1:-$ROOT/.env}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "No .env at $ENV_FILE" >&2
  exit 1
fi
tmp="$(mktemp)"
grep -Ev '^(NEXUSCORE_PUBLIC_URL|PRIMENET_PUBLIC_URL|NEXPULSE_PUBLIC_URL|NEXUS_COOKIE_DOMAIN|NEXUS_PUBLIC_URL|NEXUS_PUBLIC_URL_FROM_REQUEST)=' \
  "$ENV_FILE" > "$tmp" || true
{
  cat "$tmp"
  echo ""
  echo "# ── Public URLs (Docker proxy — path routing, same origin) ──────────────────"
  echo "NEXUS_PUBLIC_URL_FROM_REQUEST=1"
  echo "NEXUS_COOKIE_DOMAIN="
} > "$ENV_FILE"
rm -f "$tmp"
echo "Updated $ENV_FILE for single-host proxy (FROM_REQUEST=1, cleared cookie domain / old PUBLIC_URLs)."
