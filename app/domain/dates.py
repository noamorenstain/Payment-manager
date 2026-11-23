"""Strict date handling.

* User-facing format: ``DD/MM/YYYY`` (``D/M/YYYY`` also accepted). Display is always DD/MM/YYYY.
* Storage format: ISO ``YYYY-MM-DD``.
* Every parsed date is constructed with :class:`datetime.date`, so impossible calendar dates
  (31/02, 29/02 in non-leap years, 31/04, day 00, month 13, …) are rejected.
* Years are limited to 2000–2100.
* Nothing here reads the system clock; callers pass ``today`` from the injectable Clock.
"""

from __future__ import annotations

import calendar
import datetime as dt
import re

from app.domain.errors import ValidationError
from app.i18n import he

MIN_YEAR = 2000
MAX_YEAR = 2100

# [0-9] rather than \d: in Python \d also matches non-ASCII digits (e.g. Arabic-Indic).
_HE_RE = re.compile(r"^([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})$")
_ISO_RE = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})$")


def _build(year: int, month: int, day: int, shown: str, field: str | None) -> dt.date:
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise ValidationError(he.DATE_YEAR_RANGE.format(min=MIN_YEAR, max=MAX_YEAR), field)
    if not 1 <= month <= 12:
        raise ValidationError(he.DATE_INVALID_MONTH.format(value=shown), field)
    try:
        return dt.date(year, month, day)
    except ValueError:
        raise ValidationError(he.DATE_NOT_EXISTS.format(value=shown), field) from None


def parse_he_date(text: str | None, field: str | None = None, required: bool = True) -> dt.date | None:
    """Parse a user-entered ``DD/MM/YYYY`` date. Returns None for empty optional input."""
    value = (text or "").strip()
    if not value:
        if required:
            raise ValidationError(he.DATE_REQUIRED, field)
        return None
    match = _HE_RE.match(value)
    if not match:
        raise ValidationError(he.DATE_BAD_FORMAT, field)
    day, month, year = (int(g) for g in match.groups())
    return _build(year, month, day, value, field)


def parse_iso_date(text: str | None, field: str | None = None, required: bool = True) -> dt.date | None:
    """Parse a strict ISO ``YYYY-MM-DD`` date (hidden form fields, database values)."""
    value = (text or "").strip()
    if not value:
        if required:
            raise ValidationError(he.DATE_REQUIRED, field)
        return None
    match = _ISO_RE.match(value)
    if not match:
        raise ValidationError(he.DATE_BAD_FORMAT, field)
    year, month, day = (int(g) for g in match.groups())
    return _build(year, month, day, f"{day:02d}/{month:02d}/{year:04d}", field)


def format_he(value: dt.date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else ""


def to_iso(value: dt.date | None) -> str | None:
    return value.isoformat() if value else None


def from_iso(value: str | None) -> dt.date | None:
    """Read a date stored by the app (already validated by the DB CHECKs)."""
    return dt.date.fromisoformat(value) if value else None


# ---------------------------------------------------------------- business rules

def require_not_future(value: dt.date, today: dt.date, field: str | None = None, message: str | None = None) -> dt.date:
    if value > today:
        raise ValidationError(message or he.DATE_IN_FUTURE, field)
    return value


def require_after(value: dt.date, other: dt.date, field: str | None = None, message: str | None = None) -> dt.date:
    if value <= other:
        raise ValidationError(message or he.DATE_MUST_BE_AFTER.format(other=format_he(other)), field)
    return value


def require_range(start: dt.date | None, end: dt.date | None, field: str | None = None) -> None:
    if start and end and start > end:
        raise ValidationError(he.DATE_RANGE_INVERTED, field)


# ---------------------------------------------------------------- calendar arithmetic

def last_day_of_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def clamp_day(year: int, month: int, day: int) -> dt.date:
    """Day ``day`` of the month, or the month's last day if it has fewer days (31 → 28/29/30)."""
    return dt.date(year, month, min(day, last_day_of_month(year, month)))


def add_months(value: dt.date, months: int, day: int | None = None) -> dt.date:
    """Shift by whole months, clamping to month end. ``day`` overrides the target day."""
    index = value.year * 12 + (value.month - 1) + months
    year, month = divmod(index, 12)
    return clamp_day(year, month + 1, day if day is not None else value.day)
