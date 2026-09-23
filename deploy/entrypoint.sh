#!/bin/sh
set -eu

cd /app

if [ -f /app/deploy/mount_network_balance.sh ]; then
  /app/deploy/mount_network_balance.sh || echo "WARN: Network Balance SMB mount failed (see logs above)" >&2
fi

DATA_ROOT="${NCM_DATA_ROOT:-/data}"
mkdir -p \
  "${DATA_ROOT}/databases" \
  "${DATA_ROOT}/databases/nexuscore" \
  "${DATA_ROOT}/sync_downloads" \
  "${DATA_ROOT}/raw/KPIs" \
  "${DATA_ROOT}/portals/marketing"
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

_run_gunicorn() {
  module="$1"
  if id primenet >/dev/null 2>&1; then
    exec runuser -u primenet -- gunicorn -c deploy/gunicorn.conf.py "${module}"
  else
    exec gunicorn -c deploy/gunicorn.conf.py "${module}"
  fi
}

cmd="${1:-primenet}"
shift || true

case "${cmd}" in
  web|primenet)
    # `web` kept as an alias for PrimeNet during the migration window.
    export NCM_BOOTSTRAP_ON_IMPORT=0
    export NCM_DISABLE_SCHEDULER=1
    export FLASK_PORT="${FLASK_PORT:-8001}"
    _as_primenet python -m deploy.bootstrap
    _run_gunicorn primenet_app:app
    ;;
  nexuscore)
    export NCM_BOOTSTRAP_ON_IMPORT=0
    export NCM_DISABLE_SCHEDULER=1
    export FLASK_PORT="${FLASK_PORT:-8000}"
    _run_gunicorn nexuscore_app:app
    ;;
  nexpulse)
    export NCM_BOOTSTRAP_ON_IMPORT=0
    export NCM_DISABLE_SCHEDULER=1
    export FLASK_PORT="${FLASK_PORT:-8002}"
    _run_gunicorn nexpulse_app:app
    ;;
  dev|dev-primenet)
    export NCM_BOOTSTRAP_ON_IMPORT=0
    export NCM_DISABLE_SCHEDULER=1
    export FLASK_DEBUG=1
    export FLASK_PORT="${FLASK_PORT:-8001}"
    _as_primenet python -m deploy.bootstrap
    if id primenet >/dev/null 2>&1; then
      exec runuser -u primenet -- python primenet_app.py
    else
      exec python primenet_app.py
    fi
    ;;
  dev-nexuscore)
    export NCM_DISABLE_SCHEDULER=1
    export FLASK_DEBUG=1
    export FLASK_PORT="${FLASK_PORT:-8000}"
    if id primenet >/dev/null 2>&1; then
      exec runuser -u primenet -- python nexuscore_app.py
    else
      exec python nexuscore_app.py
    fi
    ;;
  dev-nexpulse)
    export NCM_DISABLE_SCHEDULER=1
    export FLASK_DEBUG=1
    export FLASK_PORT="${FLASK_PORT:-8002}"
    if id primenet >/dev/null 2>&1; then
      exec runuser -u primenet -- python nexpulse_app.py
    else
      exec python nexpulse_app.py
    fi
    ;;
  scheduler)
    export NCM_BOOTSTRAP_ON_IMPORT=0
    export NCM_RUN_SCHEDULER=1
    export NCM_ENABLE_ETL="${NCM_ENABLE_ETL:-1}"
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
