"""AMLE optimizer rules and constants — edit adjustment logic here."""

from __future__ import annotations

import os

# Managed object and parameters pulled from NetAct CM.
AMLE_MO_CLASS = "NOKLTE:AMLEPR"
AMLE_PARAMS = ["cacHeadroom", "deltaCac", "maxCacThreshold"]
CM_EXTRA_PARAMS = ["targetCarrierFreq"]

# Network Balance share (daily Nokia/Huawei balancing CSV exports).
NETWORK_BALANCE_PATH = os.environ.get("NETWORK_BALANCE_PATH", r"\\RNO-WAN\Network Balance")
NETWORK_BALANCE_VENDOR = os.environ.get("NETWORK_BALANCE_VENDOR", "Nokia")
SECTOR_COLUMN = "Sector"
STATUS_COLUMN = "New Balancing Status"
NOK_STATUS_VALUE = "NOK"
BALANCE_VENDORS = ("nokia", "huawei")
BALANCE_INGEST_LOOKBACK_DAYS = int(os.environ.get("NETWORK_BALANCE_INGEST_LOOKBACK_DAYS", "14"))
BALANCE_PREFER_SQLITE = os.environ.get("NETWORK_BALANCE_PREFER_SQLITE", "1").strip().lower() not in ("0", "false", "no")
# Maximum date span for trend queries in the UI.
TREND_MAX_DAYS = int(os.environ.get("NETWORK_BALANCE_TREND_MAX_DAYS", "90"))

# Adjustment step applied per parameter (see HIGHEST/LOWEST_LAYER_DELTAS for direction).
ADJUSTMENT_DELTA = 10
PARAM_MIN = 0
PARAM_MAX = 100

# Require at least this many layers with throughput > 0 before proposing changes.
MIN_ACTIVE_LAYERS = 2

# Skip sectors where highest and lowest layer are the same.
SKIP_TIED_LAYERS = True

# Highest-throughput source → less aggressive offloading.
HIGHEST_LAYER_DELTAS: dict[str, int] = {
    "maxCacThreshold": -ADJUSTMENT_DELTA,
    "cacHeadroom": ADJUSTMENT_DELTA,
    "deltaCac": ADJUSTMENT_DELTA,
}

# Lowest-throughput source → more aggressive offloading.
LOWEST_LAYER_DELTAS: dict[str, int] = {
    "maxCacThreshold": ADJUSTMENT_DELTA,
    "cacHeadroom": -ADJUSTMENT_DELTA,
    "deltaCac": -ADJUSTMENT_DELTA,
}

# Layer labels in Network Balance throughput columns.
THROUGHPUT_LAYERS = ("L18", "L21", "L9", "L18+")
THROUGHPUT_COLUMNS: dict[str, str] = {
    "L18": "L18 User DL PDCP Average Throughput",
    "L21": "L21 User DL PDCP Average Throughput",
    "L9": "L9 User DL PDCP Average Throughput",
    "L18+": "L18new User DL PDCP Average Throughput",
}

# Minimum Nokia CM client timeout (seconds) for multi-site AMLE pulls.
BULK_CM_TIMEOUT_SEC = int(os.environ.get("AMLE_BULK_CM_TIMEOUT_SEC", "300"))
# Parallel Open API workers when CM Operations bulk export is unavailable.
OPEN_API_PARALLEL_WORKERS = int(os.environ.get("AMLE_OPEN_API_PARALLEL_WORKERS", "6"))
# AMLEPR is a small MO class — Open API per-site queries are faster than CM Operations bulk.
AMLE_USE_CM_OPERATIONS_BULK = os.environ.get("AMLE_USE_CM_OPERATIONS_BULK", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)
# Scoped AMLE CM queries — fail faster than generic CM extract (default 180s × retries).
AMLE_CM_TIMEOUT_SEC = int(os.environ.get("AMLE_CM_TIMEOUT_SEC", "45"))
AMLE_CM_MAX_RETRIES = int(os.environ.get("AMLE_CM_MAX_RETRIES", "1"))
