"""Tunable constants for SON ML (offline job + inference)."""

from __future__ import annotations

import os

KPI_CATEGORIES: tuple[str, ...] = (
    "Retainability",
    "Accessibility",
    "Mobility",
    "Interference",
    "Utilization",
)

TECHNOLOGY = "4G"
VENDORS: tuple[str, ...] = ("nokia", "huawei")
LOOKBACK_DAYS = 28
MIN_HISTORY_DAYS = 7
SEQUENCE_DAYS = 14
EMBEDDING_DIM = 8
ANOMALY_PERCENTILE = 95.0
ANOMALY_MIN_SCORE = 70.0
TOPOLOGY_MIN_SCORE = 55.0
SPATIAL_EPS_DEG = 0.03
SPATIAL_MIN_SAMPLES = 3
CAUSE_LABELS: tuple[str, ...] = (
    "sleeping",
    "congestion",
    "interference",
    "mobility",
    "cm_change",
    "neighbor",
)
NEIGHBOR_MAX_LINES = 8000
NEIGHBOR_MIN_ATTEMPTS = 1.0
CACHE_TTL_SECONDS = 3600
AE_EPOCHS = 20
AE_HIDDEN = 32
AE_BOTTLENECK = 8
IF_ESTIMATORS = 100
IF_CONTAMINATION = 0.05


def env_disabled() -> bool:
    return os.environ.get("SON_DISABLE_ML", "").strip().lower() in ("1", "true", "yes")


def torch_enabled() -> bool:
    if os.environ.get("SON_DISABLE_TORCH", "").strip().lower() in ("1", "true", "yes"):
        return False
    try:
        import torch  # noqa: F401
    except ImportError:
        return False
    return True
