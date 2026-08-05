#!/bin/sh
# Mount Network Balance SMB share using NETWORK_BALANCE_SMB_* from the environment.
# Called from deploy/entrypoint.sh (Docker) or deploy/mount_network_balance_from_env.sh (host).

set -eu

_enabled="${NETWORK_BALANCE_SMB_ENABLED:-}"
case "$(printf '%s' "$_enabled" | tr 'A-Z' 'a-z')" in
  1|true|yes|on) ;;
  *) exit 0 ;;
esac

_host="${NETWORK_BALANCE_SMB_HOST:-}"
_share="${NETWORK_BALANCE_SMB_SHARE:-Network Balance}"
_user="${NETWORK_BALANCE_SMB_USER:-}"
_pass="${NETWORK_BALANCE_SMB_PASSWORD:-}"
_domain="${NETWORK_BALANCE_SMB_DOMAIN:-}"
_mount="${NETWORK_BALANCE_SMB_MOUNT:-${NETWORK_BALANCE_PATH:-/network-balance}}"

if [ -z "$_host" ] || [ -z "$_user" ] || [ -z "$_pass" ]; then
  echo "mount_network_balance: NETWORK_BALANCE_SMB_ENABLED=1 but HOST, USER, or PASSWORD is missing" >&2
  exit 1
fi

if ! command -v mount.cifs >/dev/null 2>&1; then
  echo "mount_network_balance: cifs-utils not installed (mount.cifs missing)" >&2
  exit 1
fi

mkdir -p "$_mount"

if findmnt -rn -o TARGET --target "$_mount" >/dev/null 2>&1; then
  echo "mount_network_balance: already mounted at $_mount"
  exit 0
fi

_cred="/tmp/.primenet-network-balance-smb"
umask 077
{
  printf 'username=%s\n' "$_user"
  printf 'password=%s\n' "$_pass"
  if [ -n "$_domain" ]; then
    printf 'domain=%s\n' "$_domain"
  fi
} > "$_cred"

# shellcheck disable=SC2086
if mount -t cifs "//${_host}/${_share}" "$_mount" \
  -o "credentials=${_cred},vers=3.0,sec=ntlmssp,uid=1000,gid=1000,file_mode=0644,dir_mode=0755"; then
  echo "mount_network_balance: mounted //${_host}/${_share} at ${_mount}"
  _rc=0
else
  echo "mount_network_balance: mount failed for //${_host}/${_share}" >&2
  _rc=1
fi

rm -f "$_cred"
exit "$_rc"
