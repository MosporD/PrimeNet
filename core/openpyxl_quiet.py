"""Suppress known-noisy openpyxl UserWarnings during Excel PM/metadata reads.

Huawei/Nokia workbooks often lack a default stylesheet. openpyxl emits::

    UserWarning: Workbook contains no default style, apply openpyxl's default

That warning is harmless but used to become the *only* line shown in ETL
failure summaries (``code=1: warn("Workbook…")``), hiding the real error.
"""

from __future__ import annotations

import warnings
from functools import wraps
from typing import Any, Callable

_INSTALLED = False

# Match the openpyxl message (and the ``warn("…")`` form some log formatters use).
_STYLE_WARN_RE = r"Workbook contains no default style"


def silence_openpyxl_style_warning() -> None:
    """Install a process-wide filter (idempotent, safe across loader threads)."""
    global _INSTALLED
    if _INSTALLED:
        return
    warnings.filterwarnings(
        "ignore",
        message=_STYLE_WARN_RE,
        category=UserWarning,
        module=r"openpyxl(\.|$)",
    )
    # Also catch when the warning is attributed to pandas/openpyxl internals.
    warnings.filterwarnings(
        "ignore",
        message=_STYLE_WARN_RE,
        category=UserWarning,
    )
    _INSTALLED = True


def is_openpyxl_style_noise(line: str | None) -> bool:
    """True when a log/stderr line is only the stylesheet warning (or warn("…") wrap)."""
    if not line:
        return False
    low = str(line).lower()
    return "workbook contains no default style" in low or (
        "apply openpyxl" in low and "default" in low
    )


def quiet_read_excel(*args: Any, **kwargs: Any):
    """``pandas.read_excel`` with the stylesheet warning suppressed."""
    import pandas as pd

    silence_openpyxl_style_warning()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        if "engine" not in kwargs:
            kwargs["engine"] = "openpyxl"
        return pd.read_excel(*args, **kwargs)


def with_openpyxl_quiet(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator: ensure the stylesheet warning filter is installed before ``fn``."""

    @wraps(fn)
    def _wrapped(*args: Any, **kwargs: Any):
        silence_openpyxl_style_warning()
        return fn(*args, **kwargs)

    return _wrapped
