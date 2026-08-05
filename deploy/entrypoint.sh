#!/bin/sh
set -eu

cd /app

if [ -f /app/deploy/mount_network_balance.sh ]; then
  /app/deploy/mount_network_balance.sh || echo "WARN: Network Balance SMB mount failed (see logs above)" >&2
fi

DATA_ROOT="${NCM_DATA_ROOT:-/data}"
mkdir -p "${DATA_ROOT}/databases" "${DATA_ROOT}/sync_downloads" "${DATA_ROOT}/raw/KPIs"
if id primenet >/dev/null 2>&1; then
  chown -R primenet:primenet "${DATA_ROOT}" 2>/dev/null || true
fi

_as_primenet() {
  if id primenet >/dev/null 2>&1; then
    runuser -u primenet -- "$@"
  else
    "$@"
  fi
}

cmd="${1:-web}"
shift || true

case "${cmd}" in
  web)
    export NCM_BOOTSTRAP_ON_IMPORT=0
    export NCM_DISABLE_SCHEDULER=1
    _as_primenet python -m deploy.bootstrap
    if id primenet >/dev/null 2>&1; then
      exec runuser -u primenet -- gunicorn -c deploy/gunicorn.conf.py app:app
    else
      exec gunicorn -c deploy/gunicorn.conf.py app:app
    fi
    ;;
  dev)
    export NCM_BOOTSTRAP_ON_IMPORT=0
    export NCM_DISABLE_SCHEDULER=1
    export FLASK_DEBUG=1
    _as_primenet python -m deploy.bootstrap
    if id primenet >/dev/null 2>&1; then
      exec runuser -u primenet -- python app.py
    else
      exec python app.py
    fi
    ;;
  scheduler)
    export NCM_BOOTSTRAP_ON_IMPORT=0
    export NCM_RUN_SCHEDULER=1
    export NCM_DISABLE_SCHEDULER=0
    if id primenet >/dev/null 2>&1; then
      exec runuser -u primenet -- python deploy/run_scheduler.py
    else
      exec python deploy/run_scheduler.py
    fi
    ;;
  bootstrap)
    if id primenet >/dev/null 2>&1; then
      exec runuser -u primenet -- python -m deploy.bootstrap
    else
      exec python -m deploy.bootstrap
    fi
    ;;
  *)
    exec "${cmd}" "$@"
    ;;
esac
