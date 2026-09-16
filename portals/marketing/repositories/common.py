"""Shared repository helpers."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone


class ValidationError(Exception):
    """Field-level validation failure, surfaced back to the form or API."""

    def __init__(self, errors: dict[str, str] | str):
        if isinstance(errors, str):
            errors = {"_": errors}
        self.errors = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean(value, limit: int = 500) -> str:
    text = ("" if value is None else str(value)).strip()
    return text[:limit]


def clean_or_none(value, limit: int = 500) -> str | None:
    text = clean(value, limit)
    return text or None


_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_\-]{1,31}$")


def normalise_code(value, field: str = "code") -> str:
    code = clean(value, 32).upper().replace(" ", "-")
    if not _CODE_RE.match(code):
        raise ValidationError(
            {field: "Use 2–32 characters: letters, digits, hyphen or underscore."}
        )
    return code


def parse_date(value, field: str, *, required: bool = False) -> str | None:
    text = clean(value, 10)
    if not text:
        if required:
            raise ValidationError({field: "This date is required."})
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise ValidationError({field: "Use the format YYYY-MM-DD."}) from None


def parse_number(value, field: str, *, minimum=None, maximum=None, required=False):
    text = clean(value, 24)
    if not text:
        if required:
            raise ValidationError({field: "This value is required."})
        return None
    try:
        number = float(text)
    except ValueError:
        raise ValidationError({field: "Enter a number."}) from None
    if minimum is not None and number < minimum:
        raise ValidationError({field: f"Must be at least {minimum}."})
    if maximum is not None and number > maximum:
        raise ValidationError({field: f"Must be at most {maximum}."})
    return number


def parse_int(value, field: str, *, minimum=None, maximum=None, required=False):
    number = parse_number(value, field, minimum=minimum, maximum=maximum, required=required)
    return None if number is None else int(number)


def require_choice(value, choices, field: str) -> str:
    key = clean(value, 64).lower()
    if key not in choices:
        raise ValidationError({field: "Choose one of the listed options."})
    return key


def check_date_order(start: str | None, end: str | None, field: str, message: str) -> None:
    if start and end and end < start:
        raise ValidationError({field: message})
