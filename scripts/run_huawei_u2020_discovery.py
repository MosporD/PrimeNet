"""Backward-compatible entry point — prefer ``python -m modules.cm_extractor.scripts.run_huawei_u2020_discovery``."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.cm_extractor.scripts.run_huawei_u2020_discovery import main

if __name__ == '__main__':
    raise SystemExit(main())
