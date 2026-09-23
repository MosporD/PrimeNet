"""Daily / manual network-wide RMOD_R ingest (delegates to Configuration Dashboard shared job)."""

from __future__ import annotations

from typing import Any


def last_ingest_result() -> dict[str, Any] | None:
    from modules.configuration_dashboard.ingest_job import last_ingest_result as _last

    return _last()


def run_rmod_inventory_ingest(*, trigger_source: str = 'scheduled') -> dict[str, Any]:
    """
    Full-network Nokia pull using the shared service account.

    Delegates to Configuration Dashboard ingest (RMOD_R + WNCELG) so both
    snapshots stay in sync from one Admin / scheduler trigger.
    """
    from modules.configuration_dashboard.ingest_job import run_config_dashboard_ingest

    return run_config_dashboard_ingest(trigger_source=trigger_source)
