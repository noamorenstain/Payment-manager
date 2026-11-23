"""Strict date validation (plan §3.4)."""

import datetime as dt

import pytest

from app.domain import dates as d
from app.domain.errors import ValidationError


@pytest.mark.parametrize("text, expected", [
    ("12/11/2026", dt.date(2026, 11, 12)),
    ("1/2/2026", dt.date(2026, 2, 1)),
    ("29/02/2028", dt.date(2028, 2, 29)),        # leap year
    ("  15/03/2026  ", dt.date(2026, 3, 15)),    # spaces trimmed
    ("31/12/2100", dt.date(2100, 12, 31)),
    ("01/01/2000", dt.date(2000, 1, 1)),
])
def test_valid_dates(text, expected):
    assert d.parse_he_date(text) == expected


@pytest.mark.parametrize("text", [
    "31/02/2026", "30/02/2028", "29/02/2027", "29/02/2100",   # Feb (2100 is not a leap year)
    "31/04/2026", "31/06/2026", "31/09/2026", "31/11/2026",   # 30-day months
    "00/05/2026", "32/01/2026",                               # day out of range
    "15/00/2026", "15/13/2026",                               # month out of range
    "12/11/26", "2026-11-12", "12-11-2026", "12.11.2026",     # wrong formats
    "abc", "12/11/2026x", "1/1/1/2026", "١٢/١١/٢٠٢٦",          # garbage, non-ASCII digits
    "31/12/1999", "01/01/2101",                               # year range
])
def test_invalid_dates_rejected(text):
    with pytest.raises(ValidationError) as exc:
        d.parse_he_date(text, field="due_date")
    assert exc.value.field == "due_date"
    assert exc.value.message  # Hebrew message present


def test_impossible_date_message_names_the_date():
    with pytest.raises(ValidationError) as exc:
        d.parse_he_date("31/02/2026")
    assert exc.value.message == "תאריך לא קיים: 31/02/2026"


def test_required_and_optional_empty():
    with pytest.raises(ValidationError):
        d.parse_he_date("")
    with pytest.raises(ValidationError):
        d.parse_he_date(None)
    assert d.parse_he_date("   ", required=False) is None


@pytest.mark.parametrize("text, ok", [
    ("2026-11-12", True), ("2028-02-29", True),
    ("2026-02-30", False), ("2027-02-29", False), ("2026-13-01", False), ("2026-1-5", False),
    ("12/11/2026", False), ("1999-12-31", False),
])
def test_iso_parsing_is_strict(text, ok):
    if ok:
        assert d.parse_iso_date(text).isoformat() == text
    else:
        with pytest.raises(ValidationError):
            d.parse_iso_date(text)


def test_format_round_trip():
    value = dt.date(2026, 3, 5)
    assert d.format_he(value) == "05/03/2026"
    assert d.parse_he_date(d.format_he(value)) == value
    assert d.to_iso(value) == "2026-03-05"
    assert d.from_iso("2026-03-05") == value
    assert d.format_he(None) == "" and d.to_iso(None) is None


def test_not_future_rule():
    today = dt.date(2026, 11, 12)
    assert d.require_not_future(today, today) == today
    with pytest.raises(ValidationError):
        d.require_not_future(dt.date(2026, 11, 13), today, message="תאריך התשלום אינו יכול להיות עתידי.")


def test_require_after_and_range():
    base = dt.date(2026, 11, 12)
    assert d.require_after(dt.date(2026, 11, 13), base)
    with pytest.raises(ValidationError):
        d.require_after(base, base)
    with pytest.raises(ValidationError):
        d.require_range(dt.date(2026, 2, 1), dt.date(2026, 1, 1))
    d.require_range(dt.date(2026, 1, 1), dt.date(2026, 1, 1))
    d.require_range(None, dt.date(2026, 1, 1))


@pytest.mark.parametrize("start, months, day, expected", [
    (dt.date(2026, 1, 31), 1, None, dt.date(2026, 2, 28)),
    (dt.date(2028, 1, 31), 1, None, dt.date(2028, 2, 29)),
    (dt.date(2026, 1, 15), 1, 31, dt.date(2026, 2, 28)),
    (dt.date(2026, 3, 1), 1, 31, dt.date(2026, 4, 30)),
    (dt.date(2026, 5, 1), 1, 31, dt.date(2026, 6, 30)),
    (dt.date(2026, 11, 30), 2, None, dt.date(2027, 1, 30)),
    (dt.date(2026, 12, 15), 12, None, dt.date(2027, 12, 15)),
    (dt.date(2026, 3, 31), -1, None, dt.date(2026, 2, 28)),
])
def test_add_months_clamps_to_month_end(start, months, day, expected):
    assert d.add_months(start, months, day) == expected
