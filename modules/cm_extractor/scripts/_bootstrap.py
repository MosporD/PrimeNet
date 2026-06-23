"""Shared repo-root bootstrap for CM Extractor CLI scripts."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def bootstrap() -> Path:
    root = str(REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / '.env', override=True)
    except ImportError:
        pass
    return REPO_ROOT
