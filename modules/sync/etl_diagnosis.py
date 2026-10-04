"""ETL pipeline diagnosis snapshot for Engineering Admin.

Aggregates ETL gate, scheduler mode, in-process progress/lock, Postgres domain
routing, store row counts, and recent sync_log signals. Durable visibility comes
from ``sync_log`` (shared across web + scheduler containers); in-memory progress
only reflects jobs running in *this* process.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from db.pg_domains import ALL_GROUPS, DOMAIN_GROUPS, enabled_groups, postgres_url
from db.runtime import list_tables, open_db, store_available
from sync_config import (
    HUAWEI_GROUPS_DAILY_DB,
    HUAWEI_GROUPS_DB,
    HUAWEI_NEIGHBOR_RAW_DB,
    HUAWEI_PM_DAILY_DB,
    HUAWEI_PM_DB,
    METADATA_DB,
    NEIGHBOR_KPI_DB,
    NOKIA_GROUPS_DAILY_DB,
    NOKIA_GROUPS_DB,
    NOKIA_PM_DAILY_DB,
    NOKIA_PM_DB,
)


_STORE_SURVEY = (
    ('metadata', 'metadata', METADATA_DB),
    ('pm', 'pm_nokia_hourly', NOKIA_PM_DB),
    ('pm', 'pm_huawei_hourly', HUAWEI_PM_DB),
    ('pm', 'pm_nokia_daily', NOKIA_PM_DAILY_DB),
    ('pm', 'pm_huawei_daily', HUAWEI_PM_DAILY_DB),
    ('groups', 'groups_nokia_hourly', NOKIA_GROUPS_DB),
    ('groups', 'groups_huawei_hourly', HUAWEI_GROUPS_DB),
    ('groups', 'groups_nokia_daily', NOKIA_GROUPS_DAILY_DB),
    ('groups', 'groups_huawei_daily', HUAWEI_GROUPS_DAILY_DB),
    ('neighbors', 'neighbors_nokia', NEIGHBOR_KPI_DB),
    ('neighbors', 'neighbors_huawei', HUAWEI_NEIGHBOR_RAW_DB),
)


def _table_row_counts(db_path: str) -> dict[str, int]:
    if not store_available(db_path):
        return {}
    out: dict[str, int] = {}
    try:
        conn = open_db(db_path)
    except Exception:
        return {}
    try:
        for tbl in list_tables(conn):
            try:
                n = conn.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0]
                out[str(tbl)] = int(n or 0)
            except Exception:
                continue
    except Exception:
        return {}
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return out


def _serialize_dt(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    return str(value)


def _row_to_sync_dict(r) -> dict:
    if isinstance(r, dict):
        return {
            'id': r.get('id'),
            'sync_type': r.get('sync_type'),
            'technology': r.get('technology'),
            'status': r.get('status'),
            'rows_affected': r.get('rows_affected'),
            'message': r.get('message'),
            'started_at': _serialize_dt(r.get('started_at')),
        }
    return {
        'id': r[0],
        'sync_type': r[1],
        'technology': r[2],
        'status': r[3],
        'rows_affected': r[4],
        'message': r[5],
        'started_at': _serialize_dt(r[6]),
    }


def _fetch_sync_rows(limit: int = 80) -> list[dict]:
    from db.runtime import connect_app, execute_query

    conn = connect_app()
    try:
        cur = execute_query(
            conn,
            '''
            SELECT id, sync_type, technology, status, rows_affected, message, started_at
            FROM sync_log
            ORDER BY id DESC
            LIMIT ?
            ''',
            (int(limit),),
        )
        rows = cur.fetchall() or []
        return [_row_to_sync_dict(r) for r in rows]
    finally:
        conn.close()


def _last_ok_by_type(rows: list[dict], types: tuple[str, ...]) -> dict[str, dict | None]:
    found = {t: None for t in types}
    remaining = set(types)
    for row in rows:
        st = str(row.get('sync_type') or '')
        if st not in remaining:
            continue
        if str(row.get('status') or '').lower() == 'ok':
            found[st] = row
            remaining.discard(st)
        if not remaining:
            break
    # Also scan older history for types not in the recent window.
    if remaining:
        from db.runtime import connect_app, execute_query

        conn = connect_app()
        try:
            for sync_type in list(remaining):
                cur = execute_query(
                    conn,
                    '''
                    SELECT id, sync_type, technology, status, rows_affected, message, started_at
                    FROM sync_log
                    WHERE sync_type = ? AND status = 'ok'
                    ORDER BY id DESC
                    LIMIT 1
                    ''',
                    (sync_type,),
                )
                hit = cur.fetchone()
                if hit:
                    found[sync_type] = _row_to_sync_dict(hit)
        finally:
            conn.close()
    return found


def _pipeline_stuck_signal(rows: list[dict]) -> dict:
    """Detect the 'another pipeline cycle is already running' storm.

    Neighbor uses a separate lock from hourly/daily/watcher, so neighbor skips
    are not counted as a PM pipeline lock storm.
    """
    pipeline_types = {'db_loader', 'daily_full_sync'}
    relevant = [
        r for r in rows
        if str(r.get('sync_type') or '') in pipeline_types
    ]
    skip_msgs = [r for r in relevant if 'already running' in str(r.get('message') or '').lower()]
    non_skip = [r for r in relevant if 'already running' not in str(r.get('message') or '').lower()]

    stuck = False
    streak = 0
    oldest_skip = None
    newest_skip = None
    for r in relevant:
        if 'already running' in str(r.get('message') or '').lower():
            streak += 1
        else:
            break
    if streak >= 3:
        stuck = True
        newest_skip = skip_msgs[0].get('started_at') if skip_msgs else None
        oldest_skip = skip_msgs[min(streak - 1, len(skip_msgs) - 1)].get('started_at') if skip_msgs else None

    return {
        'appears_stuck': stuck,
        'skip_streak': streak if stuck else 0,
        'oldest_skip_in_streak': oldest_skip,
        'newest_skip_in_streak': newest_skip,
        'last_non_skip': non_skip[0] if non_skip else None,
        'hint': (
            'Hourly/daily/watcher share an in-memory lock in the scheduler process. '
            'Restart the scheduler container to clear a hung cycle.'
            if stuck else None
        ),
    }


def _scheduler_jobs_snapshot() -> list[dict]:
    try:
        from modules.sync.scheduler import get_scheduler
        sched = get_scheduler()
    except Exception:
        return []
    if sched is None:
        return []
    out = []
    try:
        for job in sched.get_jobs():
            next_run = getattr(job, 'next_run_time', None)
            out.append({
                'id': job.id,
                'name': job.name,
                'next_run_time': _serialize_dt(next_run) if next_run else None,
                'pending': bool(getattr(job, 'pending', False)),
            })
    except Exception as exc:
        return [{'error': str(exc)}]
    out.sort(key=lambda j: (j.get('next_run_time') or '9999', j.get('id') or ''))
    return out


def build_etl_diagnosis(*, history_limit: int = 80) -> dict:
    from core.etl_gate import etl_disabled_reason, etl_enabled
    from core.load_monitor import resource_snapshot
    from modules.sync.scheduler import (
        get_scheduler,
        get_scheduler_mode_summary,
        get_sync_progress,
        neighbor_cycle_lock_held,
        pipeline_cycle_lock_held,
    )
    from modules.sync.reset_mode import sync_reset_mode

    groups = sorted(enabled_groups())
    url = postgres_url()
    domains = {
        'postgres_configured': bool(url),
        'ncm_pg_domains_env': (os.getenv('NCM_PG_DOMAINS') or '').strip() or None,
        'enabled_groups': groups,
        'all_groups': list(ALL_GROUPS),
        'missing_groups': [g for g in ALL_GROUPS if g not in groups] if url else list(ALL_GROUPS),
        'schemas_by_group': {
            g: list(DOMAIN_GROUPS.get(g, ()))
            for g in groups
        },
        'metadata_pm_backend_mismatch': (
            ('metadata' in groups) != ('pm' in groups)
        ) if url else False,
    }

    stores = []
    for group, label, path in _STORE_SURVEY:
        try:
            counts = _table_row_counts(path)
            available = store_available(path)
            err = None
        except Exception as exc:
            counts = {}
            available = False
            err = str(exc)
        total = sum(counts.values())
        stores.append({
            'group': group,
            'store': label,
            'backend': 'postgresql' if group in enabled_groups() else 'disabled',
            'available': available,
            'table_count': len(counts),
            'row_total': total,
            'tables': counts,
            'empty': total == 0 and not err,
            'error': err,
        })

    try:
        recent = _fetch_sync_rows(limit=history_limit)
    except Exception as exc:
        recent = []
        alerts_bootstrap = [{
            'level': 'critical',
            'code': 'sync_log_unavailable',
            'message': f'Could not read sync_log: {exc}',
        }]
    else:
        alerts_bootstrap = []

    last_ok = _last_ok_by_type(
        recent,
        (
            'db_loader',
            'daily_full_sync',
            'neighbor_sync',
            'metadata',
            'nokia_cm_inventory',
            'rru_inventory_ingest',
            'adjacency_gis_ingest',
            'network_health_precalc',
            'son_ml',
        ),
    ) if recent or not alerts_bootstrap else {t: None for t in (
        'db_loader', 'daily_full_sync', 'neighbor_sync', 'metadata',
        'nokia_cm_inventory', 'rru_inventory_ingest', 'adjacency_gis_ingest',
        'network_health_precalc', 'son_ml',
    )}
    # Metadata often logged as db_loader metadata:* historically; also check sync_type metadata.
    errors = [r for r in recent if str(r.get('status') or '').lower() == 'error'][:25]
    admin_cmds = [r for r in recent if str(r.get('sync_type') or '') == 'admin_command'][:15]

    sched = get_scheduler()
    mode = get_scheduler_mode_summary()
    progress = get_sync_progress()

    alerts: list[dict] = list(alerts_bootstrap)
    if not etl_enabled():
        alerts.append({
            'level': 'critical',
            'code': 'etl_disabled',
            'message': etl_disabled_reason() or 'ETL is disabled (NCM_ENABLE_ETL=0).',
        })
    if sync_reset_mode():
        alerts.append({
            'level': 'warning',
            'code': 'reset_mode',
            'message': 'Sync reset mode is active — many pulls are disabled.',
        })
    if domains['metadata_pm_backend_mismatch']:
        alerts.append({
            'level': 'critical',
            'code': 'meta_pm_mismatch',
            'message': 'metadata and pm must both be enabled under NCM_DATABASE_URL / NCM_PG_DOMAINS.',
        })
    empty_meta = next((s for s in stores if s['store'] == 'metadata' and s['empty']), None)
    if empty_meta and etl_enabled():
        alerts.append({
            'level': 'warning',
            'code': 'metadata_empty',
            'message': 'Metadata store has 0 rows. Trigger Metadata pull or wait for the daily metadata job.',
        })
    stuck = _pipeline_stuck_signal(recent)
    if stuck.get('appears_stuck'):
        alerts.append({
            'level': 'critical',
            'code': 'pipeline_lock_stuck',
            'message': (
                f"Pipeline lock storm detected (streak={stuck.get('skip_streak')}). "
                f"{stuck.get('hint') or ''}"
            ).strip(),
        })
    if not mode.get('scheduler_in_process', True) and sched is None:
        # get_scheduler_mode_summary sets scheduler_in_process False when not hosting.
        pass
    if sched is None:
        alerts.append({
            'level': 'info',
            'code': 'scheduler_not_in_web',
            'message': (
                'This web process is not hosting APScheduler. Live progress bars only update when '
                'a job runs here (manual trigger). Scheduled work + lock state live in the scheduler container; '
                'use sync_log and store counts below for cross-process visibility.'
            ),
        })

    return {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'etl': {
            'enabled': etl_enabled(),
            'disabled_reason': None if etl_enabled() else etl_disabled_reason(),
            'reset_mode': bool(sync_reset_mode()),
            'ncm_enable_etl': (os.getenv('NCM_ENABLE_ETL') or '').strip() or None,
            'ncm_disable_scheduler': (os.getenv('NCM_DISABLE_SCHEDULER') or '').strip() or None,
        },
        'scheduler': {
            **mode,
            'in_process': sched is not None,
            'pipeline_lock_held_here': bool(pipeline_cycle_lock_held()),
            'neighbor_lock_held_here': bool(neighbor_cycle_lock_held()),
            'jobs': _scheduler_jobs_snapshot(),
        },
        'progress': progress,
        'domains': domains,
        'stores': stores,
        'pipeline_health': stuck,
        'last_ok': last_ok,
        'recent_errors': errors,
        'recent_admin_commands': admin_cmds,
        'recent_events': recent[:40],
        'resources': resource_snapshot(),
        'alerts': alerts,
        'manual_operations': [
            {'key': 'hourly_full', 'label': 'Hourly full (pull + load)', 'endpoint': '/api/sync/trigger/hourly_full'},
            {'key': 'daily_full', 'label': 'Daily full (pull + load)', 'endpoint': '/api/sync/trigger/daily_full'},
            {'key': 'neighbor_sync', 'label': 'Neighbor sync', 'endpoint': '/api/sync/trigger/neighbor_sync'},
            {'key': 'metadata', 'label': 'Metadata pull', 'endpoint': '/api/sync/trigger/metadata'},
            {'key': 'nokia_pm', 'label': 'Nokia PM + groups', 'endpoint': '/api/sync/trigger/nokia_pm'},
            {'key': 'huawei_pm', 'label': 'Huawei PM + groups', 'endpoint': '/api/sync/trigger/huawei_pm'},
            {'key': 'cells_hourly', 'label': 'Cells hourly', 'endpoint': '/api/sync/trigger/cells_hourly'},
            {'key': 'cells_daily', 'label': 'Cells daily', 'endpoint': '/api/sync/trigger/cells_daily'},
            {'key': 'groups_hourly', 'label': 'Groups hourly', 'endpoint': '/api/sync/trigger/groups_hourly'},
            {'key': 'groups_daily', 'label': 'Groups daily', 'endpoint': '/api/sync/trigger/groups_daily'},
            {'key': 'test', 'label': 'Test SFTP connectivity', 'endpoint': '/api/sync/test', 'method': 'GET'},
        ],
    }
