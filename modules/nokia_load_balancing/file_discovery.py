"""Detect vendor and date from Network Balance export filenames."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

VENDOR_ALIASES: dict[str, str] = {
    "nokia": "nokia",
    "huawei": "huawei",
    "hw": "huawei",
}

SEP = r"[-_./ ]"
_ISO_RE = re.compile(r"(?<!\d)(\d{4})" + SEP + r"(\d{1,2})" + SEP + r"(\d{1,2})(?!\d)")
_DMY_RE = re.compile(r"(?<!\d)(\d{1,2})" + SEP + r"(\d{1,2})" + SEP + r"(\d{4})(?!\d)")
_COMPACT_RE = re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)")


def _make_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def detect_date(stem: str, *, month_first: bool = False) -> date | None:
    match = _ISO_RE.search(stem)
    if match:
        year, month, day = (int(part) for part in match.groups())
        parsed = _make_date(year, month, day)
        if parsed:
            return parsed

    match = _DMY_RE.search(stem)
    if match:
        first, second, year = (int(part) for part in match.groups())
        order = [(second, first), (first, second)] if month_first else [(first, second), (second, first)]
        for day, month in order:
            parsed = _make_date(year, month, day)
            if parsed:
                return parsed

    match = _COMPACT_RE.search(stem)
    if match:
        year, month, day = (int(part) for part in match.groups())
        parsed = _make_date(year, month, day)
        if parsed:
            return parsed

    return None


def detect_vendor(stem: str, aliases: dict[str, str] | None = None) -> str | None:
    aliases = aliases or VENDOR_ALIASES
    lowered = stem.lower()
    for alias in sorted(aliases, key=len, reverse=True):
        if re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", lowered):
            return aliases[alias]
    return None


def parse_balance_filename(path: Path | str, *, month_first: bool = False) -> tuple[str | None, date | None]:
    """Return (vendor, file_date) parsed from a CSV filename stem."""
    stem = Path(path).stem
    return detect_vendor(stem), detect_date(stem, month_first=month_first)
