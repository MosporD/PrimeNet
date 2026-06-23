"""Offline batch build for Network Health precomputed tables."""

from __future__ import annotations

import logging
import time

from modules.son_analytics.pm_helpers import PM_DATA_SCOPE, collect_all_kpi_benchmarks

from . import config as cfg
from .logic import _enrich_benchmark_rows, _slim_table_row, list_kpi_columns, resolve_precompute_kpis
from .precalc_store import get_build_meta, load_precalc_meta, pm_fingerprint, save_payload

logger = logging.getLogger(__name__)


def _kpis_to_build(all_kpis: list[str], *, all_kpis_mode: bool) -> list[str]:
    if not all_kpis:
        return []
    if all_kpis_mode or cfg.PRECOMPUTE_CRON_ALL_KPIS:
        return list(all_kpis)
    return resolve_precompute_kpis(all_kpis)


def build_vendor_rat(
    vendor: str,
    rat: str,
    *,
    force: bool = False,
    all_kpis: bool | None = None,
) -> dict:
    """Compute and persist tables for one vendor + RAT."""
    t0 = time.time()
    all_kpi_mode = cfg.PRECOMPUTE_CRON_ALL_KPIS if all_kpis is None else all_kpis
    if not force:
        meta = get_build_meta(vendor, rat)
        if meta and not meta.get("is_stale") and load_precalc_meta(vendor, rat, allow_stale=False):
            return {
                "vendor": vendor,
                "rat": rat,
                "skipped": True,
                "reason": "up_to_date",
                "built_at": meta.get("built_at"),
            }

    all_kpis_list = list_kpi_columns(vendor, rat)
    kpi_columns = _kpis_to_build(all_kpis_list, all_kpis_mode=all_kpi_mode)
    if not kpi_columns:
        save_payload(
            vendor,
            rat,
            {},
            precomputed_kpis=[],
            total_kpi_count=0,
            fingerprint=pm_fingerprint(vendor, rat),
            build_seconds=time.time() - t0,
        )
        return {
            "vendor": vendor,
            "rat": rat,
            "skipped": False,
            "kpi_count": 0,
            "row_count": 0,
            "seconds": round(time.time() - t0, 2),
        }

    pm_tech = cfg.pm_technology_for_rat(rat)
    raw = collect_all_kpi_benchmarks(
        kpi_columns,
        vendor=vendor,
        technology=pm_tech,
        scope=PM_DATA_SCOPE,
        lookback_days=cfg.WOW_LOOKBACK_DAYS,
        min_history_days=cfg.WOW_MIN_HISTORY_DAYS,
        no_change_threshold=cfg.WOW_NO_CHANGE_THRESHOLD,
    )

    tables: dict[str, list[dict]] = {}
    for kpi, rows in raw.items():
        enriched = _enrich_benchmark_rows(rows, rat=rat)
        tables[kpi] = [_slim_table_row(r) for r in enriched]

    save_payload(
        vendor,
        rat,
        tables,
        precomputed_kpis=kpi_columns,
        total_kpi_count=len(all_kpis_list),
        fingerprint=pm_fingerprint(vendor, rat),
        build_seconds=time.time() - t0,
    )
    row_count = sum(len(v) for v in tables.values())
    elapsed = round(time.time() - t0, 2)
    logger.info(
        "Network Health precalc %s/%s: %s KPIs, %s rows in %ss",
        vendor,
        rat,
        len(kpi_columns),
        row_count,
        elapsed,
    )
    return {
        "vendor": vendor,
        "rat": rat,
        "skipped": False,
        "kpi_count": len(kpi_columns),
        "total_kpi_count": len(all_kpis_list),
        "row_count": row_count,
        "seconds": elapsed,
    }


def build_all(*, force: bool = False, all_kpis: bool | None = None) -> list[dict]:
    """Build precalc for every configured vendor × RAT."""
    results: list[dict] = []
    for vendor in cfg.VENDOR_OPTIONS:
        vkey = vendor["key"]
        for rat in cfg.RAT_OPTIONS:
            rkey = rat["key"]
            if (vkey, rkey) in cfg.PRECALC_SKIP_COMBOS:
                results.append(
                    {
                        "vendor": vkey,
                        "rat": rkey,
                        "skipped": True,
                        "reason": "no_pm_table",
                    }
                )
                continue
            try:
                results.append(
                    build_vendor_rat(vkey, rkey, force=force, all_kpis=all_kpis)
                )
            except Exception as exc:
                logger.exception("Network Health precalc failed for %s/%s", vkey, rkey)
                results.append(
                    {
                        "vendor": vkey,
                        "rat": rkey,
                        "error": str(exc),
                        "skipped": False,
                    }
                )
    return results
