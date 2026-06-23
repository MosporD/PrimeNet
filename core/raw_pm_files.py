"""
PM raw folder helpers: pick latest export per RAT and prune stale files.

Canonical layout: ``raw/{vendor}/cells/{2g|3g|4g|5g}/{hourly|daily}/`` (one file per folder after pull).
Legacy ``.../all/...`` may still exist; use :func:`relocate_legacy_all_folder` to move files out.
"""

from __future__ import annotations

import os
import re
import shutil
from typing import Iterable

from pipeline.paths import raw_path

_TABULAR_EXTS = (".csv", ".txt", ".tsv", ".xlsx", ".xls", ".xlsm")


def infer_technology_from_filename(file_name: str) -> str | None:
    """Map export filename to 2G/3G/4G/5G (same rules as the raw loader)."""
    stem = os.path.splitext(os.path.basename(file_name))[0].strip().lower()
    stem = re.sub(r"[^a-z0-9_]+", "_", stem)
    if re.search(r"(^|_)(5g|nr)($|_)", stem) or "5g" in stem:
        return "5G"
    if "4g_tdd" in stem or "4g_fdd" in stem or re.search(r"(^|_)(4g|lte)($|_)", stem):
        return "4G"
    if re.search(r"(^|_)(3g|wcdma|umts)($|_)", stem) or "(3g)" in stem:
        return "3G"
    if re.search(r"(^|_)(2g|gsm)($|_)", stem) or "(2g)" in stem:
        return "2G"
    return None


def _is_tabular(name: str) -> bool:
    low = name.lower()
    return low.endswith(_TABULAR_EXTS) and not name.startswith("~$")


def select_latest_files_per_technology(
    folder: str,
    filenames: Iterable[str] | None = None,
) -> list[str]:
    """
    Keep one newest file (by mtime) per inferred RAT.
    Files with unknown RAT are grouped under ``_unknown`` (newest only).
    """
    names = list(filenames) if filenames is not None else os.listdir(folder)
    names = [n for n in names if _is_tabular(n)]

    best: dict[str, tuple[float, str]] = {}
    for fn in names:
        full = os.path.join(folder, fn)
        if not os.path.isfile(full):
            continue
        tech = infer_technology_from_filename(fn) or "_unknown"
        try:
            mtime = os.path.getmtime(full)
        except OSError:
            continue
        prev = best.get(tech)
        if prev is None or mtime > prev[0]:
            best[tech] = (mtime, fn)

    chosen = sorted(fn for _, fn in best.values())
    return chosen


def relocate_legacy_all_folder(vendor: str, domain: str, scope: str) -> int:
    """Move tabular files from legacy ``.../all/...`` into per-RAT folders."""
    legacy = raw_path(vendor, domain, "all", scope)
    if not os.path.isdir(legacy):
        return 0
    moved = 0
    for name in list(os.listdir(legacy)):
        if not _is_tabular(name):
            continue
        tech = infer_technology_from_filename(name)
        if not tech:
            continue
        dest_dir = raw_path(vendor, domain, tech.lower(), scope)
        os.makedirs(dest_dir, exist_ok=True)
        src = os.path.join(legacy, name)
        dst = os.path.join(dest_dir, name)
        if os.path.isfile(dst):
            try:
                os.remove(dst)
            except OSError:
                pass
        try:
            shutil.move(src, dst)
            moved += 1
        except OSError:
            pass
    return moved


def clear_tabular_files(folder: str) -> int:
    """Remove all tabular exports in ``folder`` (used before a fresh SFTP pull)."""
    if not os.path.isdir(folder):
        return 0
    removed = 0
    for name in os.listdir(folder):
        if not _is_tabular(name):
            continue
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        try:
            os.remove(path)
            removed += 1
        except OSError:
            pass
    return removed


def prune_stale_pm_files(
    folder: str,
    *,
    keep_per_technology: int = 1,
    filenames: Iterable[str] | None = None,
) -> int:
    """
    Delete older tabular exports, keeping up to ``keep_per_technology`` newest per RAT.
    Returns number of files removed.
    """
    keep = max(1, int(keep_per_technology))
    names = list(filenames) if filenames is not None else os.listdir(folder)
    names = [n for n in names if _is_tabular(n)]

    buckets: dict[str, list[tuple[float, str]]] = {}
    for fn in names:
        full = os.path.join(folder, fn)
        if not os.path.isfile(full):
            continue
        tech = infer_technology_from_filename(fn) or "_unknown"
        try:
            mtime = os.path.getmtime(full)
        except OSError:
            continue
        buckets.setdefault(tech, []).append((mtime, fn))

    removed = 0
    for items in buckets.values():
        items.sort(key=lambda x: x[0], reverse=True)
        for _, fn in items[keep:]:
            path = os.path.join(folder, fn)
            try:
                os.remove(path)
                removed += 1
            except OSError:
                pass
    return removed
