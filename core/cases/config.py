"""Optimization Cases store configuration."""

from __future__ import annotations

import os
from pathlib import Path

from sync_config import DATABASES_ROOT

CASES_DIR = Path(os.path.join(DATABASES_ROOT, "cases"))
SQLITE_PATH = CASES_DIR / "optimization_cases.db"

# Scorecard defaults (days)
BASELINE_DAYS = 7
POST_DAYS = 7
CONTROL_NEIGHBOR_LIMIT = 5

# Valid case states (ordered lifecycle)
STATES = (
    "open",
    "assigned",
    "proposed",
    "approved",
    "executed",
    "verifying",
    "closed",
    "rejected",
)

TRANSITIONS: dict[str, frozenset[str]] = {
    "open": frozenset({"assigned", "proposed", "rejected", "closed"}),
    "assigned": frozenset({"proposed", "rejected", "closed", "open"}),
    "proposed": frozenset({"approved", "rejected", "assigned"}),
    "approved": frozenset({"executed", "rejected", "proposed"}),
    "executed": frozenset({"verifying", "closed"}),
    "verifying": frozenset({"closed", "executed"}),
    "closed": frozenset(),
    "rejected": frozenset({"open"}),
}
