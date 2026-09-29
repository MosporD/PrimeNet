"""Runtime switch for the parked sync pull/ingest paths.

Nokia/Huawei PM pull + ingest, metadata pull and group ingest were stubbed out
in July 2026 (``2bb28bc7``) while the PM databases were rebuilt. The original
implementations are intact behind :func:`sync_reset_mode` rather than stranded
after an early ``return``, so the parked state is a deliberate, reversible
switch instead of unreachable code.

**Default is OFF** (real pull/ingest runs). Set ``NCM_SYNC_RESET_MODE=1`` only
when you intentionally want those legacy scheduler pulls parked.
"""

from __future__ import annotations

import os

_TRUTHY = frozenset({'1', 'true', 'yes', 'on'})


def sync_reset_mode() -> bool:
    """True only when ``NCM_SYNC_RESET_MODE`` is explicitly enabled."""
    return (os.getenv('NCM_SYNC_RESET_MODE') or '').strip().lower() in _TRUTHY
