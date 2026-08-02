"""
Live host memory sampling for adaptive resource limits.

When ``RESOURCE_ADAPTIVE=1`` (default), pipeline workers and heavy-query slots
scale between 1 and the configured env ceilings based on available RAM.
"""

from __future__ import annotations

import logging

from sync_config import (
    RESOURCE_ADAPTIVE,
    RESOURCE_HIGH_MEMORY_MB,
    RESOURCE_LOW_MEMORY_MB,
    RESOURCE_MIN_FREE_MB,
    SCHEDULER_MAX_RSS_MB,
)

logger = logging.getLogger(__name__)


def available_memory_mb() -> float | None:
    """Return available physical RAM in MiB, or None if the host cannot be sampled."""
    try:
        import psutil
    except ImportError:
        return None
    try:
        return float(psutil.virtual_memory().available) / (1024 * 1024)
    except Exception:
        return None


def memory_pressure() -> float:
    """
    Normalized memory pressure in ``[0.0, 1.0]``.

    0.0 — plenty of free RAM (at/above ``RESOURCE_HIGH_MEMORY_MB``)
    1.0 — critical (at/below ``RESOURCE_MIN_FREE_MB`` reserve)
    """
    if not RESOURCE_ADAPTIVE:
        return 0.0

    avail = available_memory_mb()
    if avail is None:
        return 0.0

    reserve = float(RESOURCE_MIN_FREE_MB)
    low = float(RESOURCE_LOW_MEMORY_MB)
    high = float(max(RESOURCE_HIGH_MEMORY_MB, low + 1))

    if avail <= reserve:
        return 1.0
    if avail >= high:
        return 0.0
    if avail <= low:
        span = max(low - reserve, 1.0)
        return 0.5 + 0.5 * ((low - avail) / span)
    span = max(high - low, 1.0)
    return 0.5 * ((high - avail) / span)


def _scale_ceiling(configured_max: int, *, task_count: int | None = None) -> int:
    configured_max = max(1, int(configured_max))
    if not RESOURCE_ADAPTIVE:
        effective = configured_max
    else:
        pressure = memory_pressure()
        if pressure >= 0.95:
            effective = 1
        else:
            effective = max(1, round(configured_max * (1.0 - pressure)))
    if task_count is not None:
        return max(1, min(effective, int(task_count)))
    return effective


def effective_worker_count(configured_max: int, task_count: int | None = None) -> int:
    """Pipeline / ingest thread-pool size for the current memory headroom."""
    return _scale_ceiling(configured_max, task_count=task_count)


def effective_query_concurrency(configured_max: int) -> int:
    """Heavy PM query concurrency for the current memory headroom."""
    return _scale_ceiling(configured_max)


def process_rss_mb(pid: int | None = None) -> float | None:
    """Return resident set size for a process in MiB (current process when pid omitted)."""
    try:
        import psutil
    except ImportError:
        return None
    try:
        proc = psutil.Process(pid) if pid is not None else psutil.Process()
        return float(proc.memory_info().rss) / (1024 * 1024)
    except Exception:
        return None


def pipeline_start_allowed() -> tuple[bool, str]:
    """
    Return ``(allowed, reason)`` before starting a pipeline subprocess cycle.

    When memory is below the reserve, the cycle is deferred so the web UI keeps RAM.
    """
    if not RESOURCE_ADAPTIVE:
        return True, ''

    avail = available_memory_mb()
    if avail is None:
        return True, ''

    if avail < float(RESOURCE_MIN_FREE_MB):
        return False, (
            f'Pipeline deferred: {avail:.0f} MB free RAM '
            f'(reserve {RESOURCE_MIN_FREE_MB} MB for web UI)'
        )
    return True, ''


def scheduler_job_allowed() -> tuple[bool, str]:
    """
    Gate scheduled work when the scheduler process itself is already large or
    the host is low on free RAM.
    """
    rss = process_rss_mb()
    if rss is not None and rss >= float(SCHEDULER_MAX_RSS_MB):
        return False, (
            f'Scheduler deferred: process RSS {rss:.0f} MB '
            f'(limit {SCHEDULER_MAX_RSS_MB} MB — restart scheduler or wait for jobs to finish)'
        )
    return pipeline_start_allowed()


def effective_sqlite_cache_kb(configured_kb: int) -> int:
    if not RESOURCE_ADAPTIVE or configured_kb <= 0:
        return configured_kb
    pressure = memory_pressure()
    return max(4096, int(configured_kb * (1.0 - 0.75 * pressure)))


def effective_sqlite_mmap_mb(configured_mb: int) -> int:
    if not RESOURCE_ADAPTIVE or configured_mb <= 0:
        return configured_mb
    pressure = memory_pressure()
    return max(0, int(configured_mb * (1.0 - 0.85 * pressure)))


def resource_snapshot() -> dict:
    """Lightweight status dict for logs / diagnostics."""
    avail = available_memory_mb()
    rss = process_rss_mb()
    return {
        'adaptive': RESOURCE_ADAPTIVE,
        'available_mb': round(avail, 1) if avail is not None else None,
        'scheduler_rss_mb': round(rss, 1) if rss is not None else None,
        'scheduler_max_rss_mb': SCHEDULER_MAX_RSS_MB,
        'pressure': round(memory_pressure(), 3),
        'min_free_mb': RESOURCE_MIN_FREE_MB,
        'low_memory_mb': RESOURCE_LOW_MEMORY_MB,
        'high_memory_mb': RESOURCE_HIGH_MEMORY_MB,
    }
