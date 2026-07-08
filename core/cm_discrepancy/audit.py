"""Orchestration for one full-network CM discrepancy audit run.

Pipeline per MO class: pull -> normalize -> common settings -> flags
(mismatched vs consensus, added/removed vs previous successful run) ->
persist (SQLite + Excel + run manifest).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from typing import Any, Callable

from sync_config import DATA_ROOT

from core.cm_discrepancy import mo_recipes, store
from core.cm_discrepancy.common_settings import audit_mo_records
from core.cm_discrepancy.pull import (
    nokia_mo_meta,
    pull_huawei_mo_records,
    pull_nokia_mo_records,
    resolve_huawei_targets,
    resolve_nokia_site_ids,
)

logger = logging.getLogger(__name__)

VENDORS = ('huawei', 'nokia')
OUTPUT_ROOT = os.path.join(DATA_ROOT, 'uploads', 'cm_discrepancy')
RAW_ROOT = os.path.join(OUTPUT_ROOT, 'raw')


def normalize_vendor(vendor: str) -> str:
    value = (vendor or '').strip().lower()
    if value not in VENDORS:
        raise ValueError(f'Vendor must be one of: {", ".join(VENDORS)}')
    return value


def date_label(run_date: str) -> str:
    """ISO ``YYYY-MM-DD`` -> legacy folder/file label ``DD_MM_YYYY``."""
    return datetime.strptime(run_date, '%Y-%m-%d').strftime('%d_%m_%Y')


def run_output_dir(run_date: str) -> str:
    return os.path.join(OUTPUT_ROOT, date_label(run_date))


def workbook_path(vendor: str, run_date: str) -> str:
    label = date_label(run_date)
    return os.path.join(run_output_dir(run_date), f'{vendor.capitalize()}_disc_{label}.xlsx')


def _save_raw(vendor: str, run_date: str, mo: str, records: dict[str, dict[str, Any]]) -> None:
    if (os.getenv('CM_DISCREPANCY_SAVE_RAW') or '').strip().lower() not in ('1', 'true', 'yes'):
        return
    safe_mo = mo.replace(':', '_').replace('/', '_')
    path = os.path.join(RAW_ROOT, date_label(run_date), vendor, f'{safe_mo}.json')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(records, fh, default=str)


def _audit_one_mo(
    conn,
    *,
    run_id: int,
    prev_run_id: int | None,
    mo: str,
    records: dict[str, dict[str, Any]],
    ne_by_key: dict[str, str],
    include_empty: bool,
    detected_date: str,
) -> dict[str, int]:
    """Compute + persist master/summary/detail/object-index for one MO class."""
    result = audit_mo_records(records, include_empty=include_empty)
    store.write_master(conn, run_id, mo, result['master'])
    store.write_summary(conn, run_id, mo, result['summary'])
    store.write_object_index(conn, run_id, mo, list(records.keys()))

    prev_keys = store.get_object_keys(conn, prev_run_id, mo) if prev_run_id else set()
    current_keys = set(records.keys())
    added = sorted(current_keys - prev_keys) if prev_keys else []
    removed = sorted(prev_keys - current_keys) if prev_keys else []

    detail_rows: list[dict[str, Any]] = []
    for object_key, mismatches in result['mismatched_objects'].items():
        detail_rows.append({
            'object_key': object_key,
            'ne_name': ne_by_key.get(object_key, ''),
            'flag': 'mismatched',
            'mismatches': mismatches,
            'payload': records.get(object_key) or {},
            'detected_date': detected_date,
        })
    for object_key in added:
        detail_rows.append({
            'object_key': object_key,
            'ne_name': ne_by_key.get(object_key, ''),
            'flag': 'added',
            'mismatches': [],
            'payload': records.get(object_key) or {},
            'detected_date': detected_date,
        })
    for object_key in removed:
        detail_rows.append({
            'object_key': object_key,
            'ne_name': '',
            'flag': 'removed',
            'mismatches': [],
            'payload': {},
            'detected_date': detected_date,
        })
    if detail_rows:
        store.write_detail(conn, run_id, mo, detail_rows)

    return {
        'objects': len(records),
        'parameters': len(result['master']),
        'mismatched_params': len(result['summary']),
        'mismatches': sum(row['mismatch_count'] for row in result['summary']),
        'mismatched_objects': len(result['mismatched_objects']),
        'added': len(added),
        'removed': len(removed),
    }


def run_audit(
    vendor: str,
    *,
    run_date: str | None = None,
    conf_id: int = 1,
    mo_subset: list[str] | None = None,
    export_excel: bool = True,
    progress_cb: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    Execute one full-network discrepancy audit for a vendor.

    ``mo_subset`` restricts the MO list (used for validation runs against the
    legacy workbook). Re-running for the same vendor+date replaces the
    previous run. Returns the run summary dict (also stored in ``audit_run``).
    """
    vendor = normalize_vendor(vendor)
    run_date = run_date or date.today().isoformat()
    detected_date = run_date

    def report(message: str) -> None:
        logger.info('[cm-discrepancy %s %s] %s', vendor, run_date, message)
        if progress_cb:
            try:
                progress_cb(message)
            except Exception:
                pass

    recipes = mo_recipes.load_recipes()
    include_empty = mo_recipes.audit_options(recipes)['include_empty_values']
    subset = {mo.strip().upper() for mo in (mo_subset or []) if mo.strip()}

    conn = store.connect()
    warnings: list[str] = []
    mo_stats: dict[str, dict[str, int]] = {}
    failed_mos: list[str] = []
    try:
        # A previous successful run is the added/removed baseline; find it
        # before superseding today's earlier attempts.
        store.supersede_runs(conn, vendor=vendor, run_date=run_date)
        run_id = store.create_run(conn, vendor=vendor, run_date=run_date, scope='full-network')
        prev = store.previous_successful_run(conn, vendor=vendor, before_run_id=run_id)
        prev_run_id = int(prev['id']) if prev else None
        report(f'run #{run_id} started (baseline run: {prev_run_id or "none"})')

        if vendor == 'huawei':
            from core.cm_extractor.extraction import build_huawei_client

            mos = mo_recipes.huawei_mos(recipes)
            if subset:
                mos = [mo for mo in mos if mo.upper() in subset]
            ne_names, target_warnings = resolve_huawei_targets()
            warnings.extend(target_warnings)
            if not ne_names:
                raise RuntimeError('No Huawei eNodeB NE names could be resolved from inventory')
            report(f'{len(ne_names)} Huawei eNodeB(s), {len(mos)} MO class(es)')
            client = build_huawei_client()
            for pos, mo in enumerate(mos, 1):
                try:
                    report(f'pulling {mo} ({pos}/{len(mos)})')
                    records, ne_by_key, pull_warnings = pull_huawei_mo_records(client, mo, ne_names)
                    warnings.extend(f'{mo}: {w}' for w in pull_warnings[:20])
                    _save_raw(vendor, run_date, mo, records)
                    mo_stats[mo] = _audit_one_mo(
                        conn,
                        run_id=run_id,
                        prev_run_id=prev_run_id,
                        mo=mo,
                        records=records,
                        ne_by_key=ne_by_key,
                        include_empty=include_empty,
                        detected_date=detected_date,
                    )
                except Exception as exc:
                    failed_mos.append(mo)
                    warnings.append(f'{mo}: {exc}')
                    logger.exception('Huawei discrepancy pull failed for %s', mo)
        else:
            from core.cm_extractor.extraction import build_nokia_client

            client = build_nokia_client()
            mos_by_scope = mo_recipes.nokia_mos_by_scope(recipes)
            for scope_level, scope_mos in mos_by_scope.items():
                mos = [mo for mo in scope_mos if not subset or mo.upper() in subset]
                if not mos:
                    continue
                site_ids = resolve_nokia_site_ids(scope_level)
                report(f'{scope_level}: {len(site_ids)} element(s), {len(mos)} MO class(es)')
                meta_by_class = (
                    nokia_mo_meta(client, mos, scope_level=scope_level)
                    if scope_level in ('RNC', 'BSC')
                    else {}
                )
                for pos, mo in enumerate(mos, 1):
                    try:
                        report(f'pulling {scope_level}/{mo} ({pos}/{len(mos)})')
                        records, ne_by_key, pull_warnings = pull_nokia_mo_records(
                            client,
                            mo,
                            scope_level=scope_level,
                            conf_id=conf_id,
                            meta_parameters=meta_by_class.get(mo),
                        )
                        warnings.extend(f'{mo}: {w}' for w in pull_warnings[:20])
                        _save_raw(vendor, run_date, mo, records)
                        mo_stats[mo] = _audit_one_mo(
                            conn,
                            run_id=run_id,
                            prev_run_id=prev_run_id,
                            mo=mo,
                            records=records,
                            ne_by_key=ne_by_key,
                            include_empty=include_empty,
                            detected_date=detected_date,
                        )
                    except Exception as exc:
                        failed_mos.append(mo)
                        warnings.append(f'{mo}: {exc}')
                        logger.exception('Nokia discrepancy pull failed for %s', mo)

        total_mismatches = sum(stat['mismatches'] for stat in mo_stats.values())
        store.append_trend(
            conn, vendor=vendor, run_date=run_date, run_id=run_id, total=total_mismatches
        )

        stats = {
            'mo_count': len(mo_stats),
            'failed_mos': failed_mos,
            'objects': sum(stat['objects'] for stat in mo_stats.values()),
            'total_mismatches': total_mismatches,
            'mismatched_objects': sum(stat['mismatched_objects'] for stat in mo_stats.values()),
            'added': sum(stat['added'] for stat in mo_stats.values()),
            'removed': sum(stat['removed'] for stat in mo_stats.values()),
            'baseline_run_id': prev_run_id,
            'warnings': warnings[:200],
            'per_mo': mo_stats,
        }

        excel_path = ''
        if export_excel and mo_stats:
            try:
                from core.cm_discrepancy.excel_export import export_run_workbook

                excel_path = export_run_workbook(conn, run_id)
                stats['excel_path'] = excel_path
                report(f'workbook written: {excel_path}')
            except Exception as exc:
                warnings.append(f'excel export failed: {exc}')
                stats['warnings'] = warnings[:200]
                logger.exception('Discrepancy workbook export failed')

        status = 'failed' if not mo_stats else ('partial' if failed_mos else 'success')
        store.finish_run(conn, run_id, status=status, stats=stats)
        _write_manifest(vendor, run_date, run_id, status, stats)
        report(f'run #{run_id} finished: {status} ({total_mismatches} mismatches)')
        return {'run_id': run_id, 'vendor': vendor, 'run_date': run_date, 'status': status, **stats}
    except Exception as exc:
        try:
            store.finish_run(
                conn,
                run_id,
                status='failed',
                stats={'error': str(exc), 'warnings': warnings[:200]},
            )
            _write_manifest(vendor, run_date, run_id, 'failed', {'error': str(exc)})
        except Exception:
            pass
        raise
    finally:
        conn.close()


def _write_manifest(vendor: str, run_date: str, run_id: int, status: str, stats: dict) -> None:
    try:
        out_dir = run_output_dir(run_date)
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, 'run_manifest.json')
        manifest: dict[str, Any] = {}
        if os.path.isfile(path):
            try:
                with open(path, encoding='utf-8') as fh:
                    manifest = json.load(fh) or {}
            except ValueError:
                manifest = {}
        manifest[vendor] = {
            'run_id': run_id,
            'status': status,
            'finished_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'stats': {k: v for k, v in stats.items() if k != 'per_mo'},
        }
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(manifest, fh, indent=2, default=str)
    except Exception:
        logger.exception('Failed writing cm_discrepancy run manifest')
