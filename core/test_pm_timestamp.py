"""Tests for canonical PM timestamp parsing (Huawei DD/MM + Nokia dotted)."""

from datetime import datetime

from core.pm_timestamp import canonicalize_pm_timestamp, derive_pm_report_columns, parse_pm_datetime


def test_huawei_slash_is_day_first_not_us_month_first():
    # Was wrongly becoming 2026-01-07 under US / month-first parsers.
    dt = parse_pm_datetime('01/07/2026 00:00:00', prefer_dayfirst=True)
    assert dt == datetime(2026, 7, 1, 0, 0, 0)
    assert canonicalize_pm_timestamp('14/07/2026 00:00') == '2026-07-14 00:00:00'


def test_huawei_time_slash_inferred_dayfirst():
    dt = parse_pm_datetime('07/07/2026 12:00:00')
    assert dt == datetime(2026, 7, 7, 12, 0, 0)


def test_nokia_dotted_month_first():
    dt = parse_pm_datetime('7.14.2026 00:00:00', prefer_dayfirst=False)
    assert dt == datetime(2026, 7, 14, 0, 0, 0)
    assert canonicalize_pm_timestamp('07.01.2026 08:00:00', prefer_dayfirst=False) == '2026-07-01 08:00:00'


def test_iso_passthrough():
    assert canonicalize_pm_timestamp('2026-07-14 00:00:00') == '2026-07-14 00:00:00'
    assert canonicalize_pm_timestamp('2026-07-01T04:00:00') == '2026-07-01 04:00:00'
    cols = derive_pm_report_columns('14/07/2026 13:45:00', hourly=True, prefer_dayfirst=True)
    assert cols == {
        'timestamp': '2026-07-14 13:45:00',
        'report_date': '2026-07-14',
        'report_time': '13:45:00',
    }


def test_derive_pm_report_columns_daily():
    cols = derive_pm_report_columns('7.14.2026', hourly=False, prefer_dayfirst=False)
    assert cols == {
        'timestamp': '2026-07-14 00:00:00',
        'report_date': '2026-07-14',
    }
    assert 'report_time' not in cols
