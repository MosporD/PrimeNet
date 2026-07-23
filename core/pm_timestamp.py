"""
Canonical PM timestamp parsing for Nokia and Huawei exports.

One wall-clock standard everywhere: ``YYYY-MM-DD HH:MM:SS`` (naive OSS time).

Vendor raw forms:
- Huawei: slash ``DD/MM/YYYY[ HH:MM[:SS]]`` (day-first)
- Nokia: dotted ``M.D.YYYY[ HH:MM[:SS]]`` (month-first preferred)
- Sync/pipeline may already store ISO ``YYYY-MM-DD HH:MM:SS``
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None  # type: ignore

_PSEUDO_TZ_RE = re.compile(r'\s+[A-Za-z]{2,5}$')


def strip_pm_tz_suffix(value: str) -> str:
    """Drop trailing tokens like DST from Huawei exports."""
    return _PSEUDO_TZ_RE.sub('', (value or '').strip()).strip()


def format_pm_timestamp(dt: datetime) -> str:
    """Canonical PrimeNet PM timestamp string."""
    return dt.replace(microsecond=0).strftime('%Y-%m-%d %H:%M:%S')


def parse_pm_datetime(
    value,
    *,
    prefer_dayfirst: bool | None = None,
) -> datetime | None:
    """
    Parse a PM time cell into a naive datetime.

    ``prefer_dayfirst``:
      - True  → try day/month before month/day (Huawei Date / slash times)
      - False → try month/day before day/month (Nokia PERIOD_START_TIME / dotted)
      - None  → infer from separators: ``/`` → day-first, ``.`` → month-first,
                ISO ``YYYY-MM-DD`` unambiguous
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None, microsecond=0)

    if pd is not None and isinstance(value, pd.Timestamp):
        if pd.isna(value) or value.year < 2000:
            return None
        return value.to_pydatetime().replace(tzinfo=None, microsecond=0)

    if isinstance(value, (int, float)):
        try:
            x = float(value)
        except (TypeError, ValueError):
            return None
        # Excel serial day (Huawei / NetAct)
        if 20000 < x < 80000:
            t = datetime(1899, 12, 30) + timedelta(days=x)
            if t.year >= 1990:
                return t.replace(microsecond=0)
        try:
            if x.is_integer() and x > 10_000_000_000:
                return datetime.utcfromtimestamp(x / 1000.0).replace(microsecond=0)
            if x > 10_000_000:
                return datetime.utcfromtimestamp(x).replace(microsecond=0)
        except (TypeError, ValueError, OSError, OverflowError):
            return None
        return None

    s = strip_pm_tz_suffix(str(value))
    if not s or s.lower() in ('nan', 'nat', 'none'):
        return None

    # ISO / sync-normalized first (never treat as DD/MM).
    if len(s) >= 10 and s[4] == '-' and s[7] == '-' and s[:4].isdigit():
        try:
            s_iso = s
            if s_iso.endswith('Z'):
                s_iso = s_iso[:-1] + '+00:00'
            if 'T' not in s_iso and ' ' in s_iso:
                s_iso = s_iso.replace(' ', 'T', 1)
            dt = datetime.fromisoformat(s_iso.split('.')[0])
            if dt.tzinfo:
                dt = dt.replace(tzinfo=None)
            if dt.year >= 2000:
                return dt.replace(microsecond=0)
        except ValueError:
            pass

    # Infer vendor-ish dayfirst when caller did not hint.
    if prefer_dayfirst is None:
        if '/' in s:
            prefer_dayfirst = True  # Huawei
        elif '.' in s and not s[:4].isdigit():
            prefer_dayfirst = False  # Nokia dotted M.D.YYYY
        else:
            prefer_dayfirst = None

    slash_dayfirst = (
        '%d/%m/%Y %H:%M:%S',
        '%d/%m/%Y %H:%M',
        '%d/%m/%Y',
        '%d/%m/%y %H:%M:%S',
        '%d/%m/%y %H:%M',
        '%d/%m/%y',
        '%d-%m-%Y %H:%M:%S',
        '%d-%m-%Y %H:%M',
        '%d-%m-%Y',
        '%d-%m-%y %H:%M:%S',
        '%d-%m-%y %H:%M',
        '%d-%m-%y',
    )
    slash_monthfirst = (
        '%m/%d/%Y %H:%M:%S',
        '%m/%d/%Y %H:%M',
        '%m/%d/%Y',
        '%m/%d/%y %H:%M:%S',
        '%m/%d/%y %H:%M',
        '%m/%d/%y',
    )
    ymd_slash = (
        '%Y/%m/%d %H:%M:%S',
        '%Y/%m/%d %H:%M',
        '%Y/%m/%d',
    )
    dotted_dayfirst = (
        '%d.%m.%Y %H:%M:%S',
        '%d.%m.%Y %H:%M',
        '%d.%m.%Y',
        '%d.%m.%y %H:%M:%S',
        '%d.%m.%y %H:%M',
        '%d.%m.%y',
    )
    dotted_monthfirst = (
        '%m.%d.%Y %H:%M:%S',
        '%m.%d.%Y %H:%M',
        '%m.%d.%Y',
        '%m.%d.%y %H:%M:%S',
        '%m.%d.%y %H:%M',
        '%m.%d.%y',
    )
    iso_fmts = (
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %H:%M',
        '%Y-%m-%d',
    )

    if prefer_dayfirst is True:
        ordered = iso_fmts + ymd_slash + slash_dayfirst + slash_monthfirst + dotted_dayfirst + dotted_monthfirst
    elif prefer_dayfirst is False:
        ordered = iso_fmts + ymd_slash + dotted_monthfirst + dotted_dayfirst + slash_monthfirst + slash_dayfirst
    else:
        ordered = iso_fmts + ymd_slash + slash_dayfirst + slash_monthfirst + dotted_monthfirst + dotted_dayfirst

    for fmt in ordered:
        try:
            dt = datetime.strptime(s, fmt)
            if dt.year >= 2000:
                return dt
        except ValueError:
            try:
                # Trailing junk: format width for a sample date (avoids blind [:19]).
                width = len(datetime(2000, 1, 2, 3, 4, 5).strftime(fmt))
                dt = datetime.strptime(s[:width], fmt)
                if dt.year >= 2000:
                    return dt
            except ValueError:
                continue

    if pd is None:
        return None

    # pandas last resort with the same dayfirst preference.
    if prefer_dayfirst is True:
        order = (True, False)
    elif prefer_dayfirst is False:
        order = (False, True)
    elif '/' in s:
        order = (True, False)
    else:
        order = (False, True)

    for dayfirst in order:
        t = pd.to_datetime(s, errors='coerce', dayfirst=dayfirst)
        if pd.notna(t) and t.year >= 2000:
            return t.to_pydatetime().replace(tzinfo=None, microsecond=0)
    return None


def canonicalize_pm_timestamp(
    value,
    *,
    prefer_dayfirst: bool | None = None,
) -> str | None:
    """Parse then emit canonical ``YYYY-MM-DD HH:MM:SS``."""
    dt = parse_pm_datetime(value, prefer_dayfirst=prefer_dayfirst)
    if dt is None:
        return None
    return format_pm_timestamp(dt)


PM_REPORT_DATE_COL = 'report_date'
PM_REPORT_TIME_COL = 'report_time'


def format_pm_report_date(dt: datetime) -> str:
    """PrimeNet PM date column (``YYYY-MM-DD``)."""
    return dt.replace(microsecond=0).strftime('%Y-%m-%d')


def format_pm_report_time(dt: datetime) -> str:
    """PrimeNet PM time column for hourly scope (``HH:MM:SS``)."""
    return dt.replace(microsecond=0).strftime('%H:%M:%S')


def derive_pm_report_columns(
    value,
    *,
    hourly: bool = True,
    prefer_dayfirst: bool | None = None,
) -> dict[str, str] | None:
    """
    Parse a vendor time cell into PrimeNet report columns.

    Hourly: ``timestamp``, ``report_date``, ``report_time``.
    Daily: ``timestamp`` (midnight), ``report_date``.
    """
    dt = parse_pm_datetime(value, prefer_dayfirst=prefer_dayfirst)
    if dt is None:
        return None
    out = {
        'timestamp': format_pm_timestamp(dt),
        PM_REPORT_DATE_COL: format_pm_report_date(dt),
    }
    if hourly:
        out[PM_REPORT_TIME_COL] = format_pm_report_time(dt)
    return out
