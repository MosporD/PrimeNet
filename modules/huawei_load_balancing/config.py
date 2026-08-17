"""Huawei load-balancing rules — CellMLB knobs on Network Balance layers."""

from __future__ import annotations

import os

from modules.nokia_load_balancing.smb_config import resolve_balance_path

CELLMLB_MO = "CellMLB"
CELLMLB_PARAMS = ["IdleMlbUeNumThd", "HoMlbUeNumThd"]
CM_EXTRA_PARAMS = ["MlbTriggerMode", "LoadOffset"]

NETWORK_BALANCE_PATH = resolve_balance_path()
NETWORK_BALANCE_VENDOR = "Huawei"
NOK_STATUS_VALUE = "NOK"
TREND_MAX_DAYS = int(os.environ.get("NETWORK_BALANCE_TREND_MAX_DAYS", "90"))

PARAM_MIN = 1
PARAM_MAX = 100
DEFAULTS: dict[str, int] = {
    "IdleMlbUeNumThd": 10,
    "HoMlbUeNumThd": 20,
}

# Highest-throughput layer is congested → more aggressive MLB (lower UE thresholds).
HIGHEST_LAYER_DELTAS: dict[str, int] = {
    "IdleMlbUeNumThd": -2,
    "HoMlbUeNumThd": -5,
}

# Lowest-throughput layer should keep users → less aggressive MLB.
LOWEST_LAYER_DELTAS: dict[str, int] = {
    "IdleMlbUeNumThd": 2,
    "HoMlbUeNumThd": 5,
}

THROUGHPUT_LAYERS = ("L18", "L21", "L9", "L18+")
