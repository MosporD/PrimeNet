"""Persistent CM discovery catalog paths (shared across Docker web + scheduler).

Catalogs must live under ``NCM_DATA_ROOT`` (compose volume ``/data``), not under
``/app/data`` in the image tree — otherwise the scheduler refreshes a private
copy that PrimeNet web never sees.
"""

from __future__ import annotations

from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _data_root() -> Path:
    try:
        from sync_config import DATA_ROOT

        return Path(DATA_ROOT)
    except Exception:
        return _project_root()


def cm_catalog_path(filename: str) -> Path:
    """Writable catalog path on the shared data volume (or local project root)."""
    return _data_root() / 'var' / 'cm_catalogs' / filename


def cm_catalog_read_candidates(filename: str) -> list[Path]:
    """Primary path first, then legacy ``<repo>/data/<filename>`` if different."""
    primary = cm_catalog_path(filename)
    legacy = _project_root() / 'data' / filename
    out = [primary]
    if legacy.resolve() != primary.resolve():
        out.append(legacy)
    return out
