#!/bin/sh
# Host helper: load .env from project root, then mount the Network Balance share.
# Usage (on Linux server):
#   sudo ./deploy/mount_network_balance_from_env.sh

set -eu

_root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$_root"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

exec "$_root/deploy/mount_network_balance.sh"
