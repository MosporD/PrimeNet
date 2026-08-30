"""Run insight section builders with a time budget and a shared TTL cache.

The fused views (RF Optimization Workbench, Radio Morning Report) call many
detectors whose first build can scan large PM/CM/neighbor stores. Building them
serially inside one request can take minutes, which the UI sees as an endless
"Loading" state. Sections therefore build on a shared worker pool: finished
payloads are cached for a short TTL, a request waits only up to its budget, and
slow sections keep building in the background so the next refresh finds them
in the cache.

``cached_build`` is the same store, for standalone modules (Sector Health,
Sleeping Cells, Mobility, etc.) that hit the same expensive scans. It is
single-flight and in-thread so a pool worker can nest cache lookups without
deadlocking the executor.
"""

from __future__ import annotations

import inspect
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from functools import wraps
from typing import Any, Callable

_TTL_SECONDS = float(os.getenv("NCM_RADIO_SECTION_TTL", "900"))
_DEFAULT_BUDGET_SECONDS = float(os.getenv("NCM_RADIO_SECTION_BUDGET", "45"))

_lock = threading.Lock()
_cache: dict[str, tuple[float, Any]] = {}
_pending: dict[str, Future] = {}
_executor = ThreadPoolExecutor(
    max_workers=int(os.getenv("NCM_RADIO_SECTION_WORKERS", "6")),
    thread_name_prefix="radio-section",
)
_tls = threading.local()


def _refresh_active() -> bool:
    if getattr(_tls, "force", False):
        return True
    try:
        from flask import has_request_context, request

        if not has_request_context():
            return False
        value = str(request.args.get("refresh") or "").strip().lower()
        return value in ("1", "true", "yes")
    except Exception:
        return False


def copy_insight(payload: Any) -> Any:
    """Shallow-copy an issues payload so callers cannot poison the cache."""
    if not isinstance(payload, dict):
        return payload
    out = dict(payload)
    issues = out.get("issues")
    if isinstance(issues, list):
        out["issues"] = [dict(row) if isinstance(row, dict) else row for row in issues]
    return out


def _build_and_store(key: str, builder: Callable[[], Any], ttl: float, force_nested: bool = False) -> Any:
    _tls.force = bool(force_nested)
    try:
        payload = builder()
        with _lock:
            _cache[key] = (time.time() + ttl, payload)
        return payload
    finally:
        _tls.force = False
        with _lock:
            if _pending.get(key) is not None:
                # Executor Future is the pending entry; pop only that key's slot.
                _pending.pop(key, None)


def cached_build(
    key: str,
    builder: Callable[[], Any],
    *,
    ttl: float | None = None,
    force: bool = False,
    copy: Callable[[Any], Any] | None = None,
) -> Any:
    """Return a TTL-cached payload and coalesce concurrent builds for ``key``.

    Builds run on the caller's thread (single-flight). Pass ``copy`` when the
    payload is mutable and callers may annotate it in place.
    """
    ttl_sec = _TTL_SECONDS if ttl is None else float(ttl)
    force = bool(force) or _refresh_active()
    now = time.time()

    building = getattr(_tls, "building", None)
    if building is None:
        _tls.building = building = set()

    with _lock:
        if not force:
            hit = _cache.get(key)
            if hit and hit[0] > now:
                return copy(hit[1]) if copy else hit[1]
        pending = _pending.get(key)
        owner = False
        if pending is None:
            pending = Future()
            _pending[key] = pending
            owner = True

    if not owner:
        if key in building:
            payload = builder()
            return copy(payload) if copy else payload
        payload = pending.result()
        return copy(payload) if copy else payload

    building.add(key)
    try:
        payload = builder()
        with _lock:
            _cache[key] = (time.time() + ttl_sec, payload)
        pending.set_result(payload)
        return copy(payload) if copy else payload
    except Exception as exc:
        pending.set_exception(exc)
        raise
    finally:
        building.discard(key)
        with _lock:
            if _pending.get(key) is pending:
                _pending.pop(key, None)


def cached_insight(name: str):
    """Decorator: TTL-cache a keyword-only insight builder. Honors ``?refresh=1``."""

    def deco(fn: Callable[..., dict]):
        sig = inspect.signature(fn)

        @wraps(fn)
        def wrapper(*args, **kwargs):
            force = bool(kwargs.pop("force_refresh", False))
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            params = dict(bound.arguments)
            key = "|".join(
                [f"insight.{name}"]
                + [f"{k}={params[k]}" for k in sorted(params)]
            )
            return cached_build(
                key,
                lambda: fn(**params),
                force=force,
                copy=copy_insight,
            )

        return wrapper

    return deco


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
    force = _refresh_active()

    now = time.time()
    with _lock:
        for name, (key, builder) in builders.items():
            if not force:
                hit = _cache.get(key)
                if hit and hit[0] > now:
                    payloads[name] = copy_insight(hit[1]) if isinstance(hit[1], dict) else hit[1]
                    continue
            fut = _pending.get(key)
            if fut is None:
                fut = _executor.submit(_build_and_store, key, builder, _TTL_SECONDS, force)
                _pending[key] = fut
            waiting[name] = fut

    for name, fut in waiting.items():
        remaining = deadline - time.monotonic()
        try:
            payload = fut.result(timeout=max(0.1, remaining))
            payloads[name] = copy_insight(payload) if isinstance(payload, dict) else payload
        except FutureTimeoutError:
            payloads[name] = {}
            skipped.append(f"{name} is still computing")
        except Exception as exc:  # keep the fused view alive on one bad section
            payloads[name] = {}
            skipped.append(f"{name} failed ({exc})")
    return payloads, skipped
