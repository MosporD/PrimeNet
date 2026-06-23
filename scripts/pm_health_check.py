#!/usr/bin/env python3
"""CLI: performance PM database health check."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pm_health import run_pm_health_check  # noqa: E402


def main() -> int:
    payload = run_pm_health_check()
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
