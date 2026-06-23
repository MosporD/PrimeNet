"""Tunable thresholds for SON Analytics (development stage)."""

from __future__ import annotations

from .pm_helpers import PM_DATA_SCOPE

# Geographic KPI degradation clusters (daily vs 7-day average)
SON_MIN_CLUSTER_CELLS = 3
SON_TOP_CLUSTERS = 50

CACHE_TTL_SECONDS = 3600
