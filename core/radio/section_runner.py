"""Run insight section builders with a time budget and a shared TTL cache.

The fused views (RF Optimization Workbench, Radio Morning Report) call many
detectors whose first build can scan large PM/CM/neighbor stores. Building them
serially inside one request can take minutes, which the UI sees as an endless
"Loading" state. Sections therefore build on a shared worker pool: finished
payloads are cached for a short TTL, a request waits only up to its budget, and
slow sections keep building in the background so the next refresh finds them
in the cache.
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Callable

_TTL_SECONDS = float(os.getenv("NCM_RADIO_SECTION_TTL", "900"))
_DEFAULT_BUDGET_SECONDS = float(os.getenv("NCM_RADIO_SECTION_BUDGET", "45"))

_lock = threading.Lock()
_cache: dict[str, tuple[float, dict]] = {}
_pending: dict[str, Future] = {}
_executor = ThreadPoolExecutor(
    max_workers=int(os.getenv("NCM_RADIO_SECTION_WORKERS", "6")),
    thread_name_prefix="radio-section",
)


def _build_and_store(key: str, builder: Callable[[], dict]) -> dict:
    try:
        payload = builder() or {}
        with _lock:
            _cache[key] = (time.time() + _TTL_SECONDS, payload)
        return payload
    finally:
        with _lock:
            _pending.pop(key, None)


def run_sections(
    builders: dict[str, tuple[str, Callable[[], dict]]],
    *,
    budget_seconds: float | None = None,
) -> tuple[dict[str, dict], list[str]]:
    """Build every section, waiting at most ``budget_seconds`` overall.

    ``builders`` maps section name -> (cache_key, zero-arg builder). The cache
    key must include every argument the builder closes over (filters, limits).

    Returns ``(payloads, skipped)``: ``payloads`` has an entry per section
    ({} when unavailable this request); ``skipped`` holds human-readable
    reasons for the missing ones.
    """
    budget = _DEFAULT_BUDGET_SECONDS if budget_seconds is None else float(budget_seconds)
    deadline = time.monotonic() + max(1.0, budget)
    payloads: dict[str, dict] = {}
    waiting: dict[str, Future] = {}
    skipped: list[str] = []

    now = time.time()
    with _lock:
        for name, (key, builder) in builders.items():
            hit = _cache.get(key)
            if hit and hit[0] > now:
                payloads[name] = hit[1]
                continue
            fut = _pending.get(key)
            if fut is None:
                fut = _executor.submit(_build_and_store, key, builder)
                _pending[key] = fut
            waiting[name] = fut

    for name, fut in waiting.items():
        remaining = deadline - time.monotonic()
        try:
            payloads[name] = fut.result(timeout=max(0.1, remaining))
        except FutureTimeoutError:
            payloads[name] = {}
            skipped.append(f"{name} is still computing")
        except Exception as exc:  # keep the fused view alive on one bad section
            payloads[name] = {}
            skipped.append(f"{name} failed ({exc})")
    return payloads, skipped
