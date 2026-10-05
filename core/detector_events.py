"""Fingerprint new detector offenders and emit platform events."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Iterable

logger = logging.getLogger(__name__)


def _state_dir() -> str:
    try:
        from sync_config import DATA_ROOT

        root = DATA_ROOT
    except Exception:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "var", "detector_fingerprints")
    os.makedirs(path, exist_ok=True)
    return path


def _load_prev(name: str) -> set[str]:
    path = os.path.join(_state_dir(), f"{name}.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return set(str(x) for x in (data.get("ids") or []))
    except Exception:
        return set()


def _save(name: str, ids: set[str]) -> None:
    path = os.path.join(_state_dir(), f"{name}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"ids": sorted(ids)}, fh)


def _issue_id(issue: dict[str, Any]) -> str:
    if issue.get("id"):
        return str(issue["id"])
    cells = issue.get("cells") or []
    cell = cells[0] if cells else issue.get("title") or ""
    raw = f"{issue.get('module')}|{cell}|{issue.get('category')}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _severity(issue: dict[str, Any]) -> str:
    return str(issue.get("severity") or "").strip().lower()


def emit_new_offenders(
    detector: str,
    issues: Iterable[dict[str, Any]],
    *,
    event_kind: str,
    critical_only: bool = False,
) -> list[str]:
    """Compare issue ids to last run; emit event for newly seen offenders.

    Returns list of new ids (may be empty). Never raises.
    """
    try:
        current_rows = [i for i in issues if isinstance(i, dict)]
        if critical_only:
            current_rows = [
                i
                for i in current_rows
                if _severity(i) in ("critical", "high")
                or float(i.get("score") or 0) >= 70
            ]
        current_ids = {_issue_id(i) for i in current_rows}
        prev = _load_prev(detector)
        new_ids = sorted(current_ids - prev)
        _save(detector, current_ids)
        if not new_ids:
            return []
        new_issues = [i for i in current_rows if _issue_id(i) in set(new_ids)]
        from core.events import emit

        emit(
            event_kind,
            {
                "detector": detector,
                "new_count": len(new_ids),
                "new_ids": new_ids[:100],
                "samples": [
                    {
                        "id": _issue_id(i),
                        "title": i.get("title"),
                        "severity": i.get("severity"),
                        "score": i.get("score"),
                        "cells": (i.get("cells") or [])[:5],
                        "area": i.get("area"),
                    }
                    for i in new_issues[:20]
                ],
            },
        )
        return new_ids
    except Exception as exc:
        logger.warning("detector emit failed %s: %s", detector, exc)
        return []
