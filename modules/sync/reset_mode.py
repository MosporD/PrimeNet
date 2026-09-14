"""Runtime switch for the parked sync pull/ingest paths.

Nokia/Huawei PM pull + ingest, metadata pull and group ingest were stubbed out
in July 2026 (``2bb28bc7``) while the PM databases were rebuilt. The original
implementations are intact behind :func:`sync_reset_mode` rather than stranded
after an early ``return``, so the parked state is a deliberate, reversible
switch instead of unreachable code.

Default is parked (matching the behaviour since July). Set
``NCM_SYNC_RESET_MODE=0`` in ``.env`` to run the real pull/ingest again.
"""

from __future__ import annotations

import os

_FALSEY = frozenset({'0', 'false', 'no', 'off'})


def sync_reset_mode() -> bool:
    """True while PM/metadata/group pull and ingest are parked (the default)."""
    return (os.getenv('NCM_SYNC_RESET_MODE') or '').strip().lower() not in _FALSEY
