"""
Concurrency gates to limit RAM pressure from pipeline ingest and heavy PM queries.

When ``RESOURCE_ADAPTIVE=1``, slot limits are recomputed from live free RAM on
each acquire attempt (env vars remain the ceiling).
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from functools import wraps
from typing import Callable, Iterator, TypeVar

from flask import jsonify

from core.load_monitor import effective_query_concurrency, resource_snapshot
from sync_config import HEAVY_QUERY_MAX_CONCURRENT, HEAVY_QUERY_SLOT_TIMEOUT_SEC

logger = logging.getLogger(__name__)

F = TypeVar('F', bound=Callable)


class ResourceBusyError(Exception):
    """Raised when a heavy query slot cannot be acquired within the timeout."""


class _AdaptiveConcurrencyGate:
    def __init__(self, configured_max: int) -> None:
        self._configured_max = max(1, int(configured_max))
        self._active = 0
        self._cond = threading.Condition()

    def current_limit(self) -> int:
        return effective_query_concurrency(self._configured_max)

    def active_count(self) -> int:
        with self._cond:
            return self._active

    def acquire(self, *, timeout: float | None) -> bool:
        deadline = (time.monotonic() + timeout) if timeout is not None else None
        with self._cond:
            while True:
                limit = self.current_limit()
                if self._active < limit:
                    self._active += 1
                    return True
                if timeout == 0 or (deadline is not None and time.monotonic() >= deadline):
                    return False
                wait_for = None
                if deadline is not None:
                    wait_for = max(0.0, deadline - time.monotonic())
                self._cond.wait(timeout=wait_for)

    def release(self) -> None:
        with self._cond:
            self._active = max(0, self._active - 1)
            self._cond.notify()


_heavy_query_gate = _AdaptiveConcurrencyGate(HEAVY_QUERY_MAX_CONCURRENT)


@contextmanager
def heavy_query_slot(*, label: str = 'query') -> Iterator[None]:
    """Limit concurrent heavy PM reads so the web UI stays responsive."""
    timeout = HEAVY_QUERY_SLOT_TIMEOUT_SEC
    wait = float(timeout) if timeout > 0 else None
    acquired = _heavy_query_gate.acquire(timeout=0 if wait is None else wait)
    if not acquired:
        snap = resource_snapshot()
        logger.warning(
            'Heavy query slot unavailable (label=%s, limit=%s, active=%s, snapshot=%s)',
            label,
            _heavy_query_gate.current_limit(),
            _heavy_query_gate.active_count(),
            snap,
        )
        raise ResourceBusyError(
            f'Server is busy with other PM queries '
            f'(limit {_heavy_query_gate.current_limit()} for current load). Retry shortly.'
        )
    try:
        yield
    finally:
        _heavy_query_gate.release()


def heavy_query_required(fn: F) -> F:
    """Flask route decorator: acquire a heavy-query slot or return HTTP 503."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            with heavy_query_slot(label=fn.__name__):
                return fn(*args, **kwargs)
        except ResourceBusyError as exc:
            return jsonify({'error': str(exc)}), 503

    return wrapper  # type: ignore[return-value]
