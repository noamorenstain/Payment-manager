"""Exact money handling (integer minor units, never float)."""

import pytest

from app.domain import money as m
from app.domain.errors import ValidationError


@pytest.mark.parametrize("text, minor", [
    ("1200", 120000), ("1,200", 120000), ("1200.5", 120050), ("1,234.56", 123456),
    ("0.01", 1), ("400", 40000), ("1,000,000", 100000000), (" 250 ", 25000),
    ("€1,200.00", 120000), ("₪99.90", 9990),
])
def test_parse_valid(text, minor):
    result = m.parse_amount(text)
    assert result == minor and isinstance(result, int)


@pytest.mark.parametrize("text, message", [
    ("", m.he.AMOUNT_REQUIRED),
    ("-5", m.he.AMOUNT_NEGATIVE),
    ("0", m.he.AMOUNT_ZERO),
    ("0.00", m.he.AMOUNT_ZERO),
    ("1.234", m.he.AMOUNT_TOO_MANY_DECIMALS),
    ("1,200.005", m.he.AMOUNT_TOO_MANY_DECIMALS),
    ("abc", m.he.AMOUNT_BAD_FORMAT),
    ("1,23", m.he.AMOUNT_BAD_FORMAT),
    ("1.2.3", m.he.AMOUNT_BAD_FORMAT),
    ("12,34,567", m.he.AMOUNT_BAD_FORMAT),
    ("1e5", m.he.AMOUNT_BAD_FORMAT),
    ("NaN", m.he.AMOUNT_BAD_FORMAT),
    ("1000000000", m.he.AMOUNT_TOO_LARGE),
    ("١٢٠٠", m.he.AMOUNT_BAD_FORMAT),       # non-ASCII digits
])
def test_parse_invalid(text, message):
    with pytest.raises(ValidationError) as exc:
        m.parse_amount(text, field="amount")
    assert exc.value.message == message
    assert exc.value.field == "amount"


def test_optional_and_zero_allowed():
    assert m.parse_amount("", required=False) is None
    assert m.parse_amount("0", allow_zero=True) == 0


def test_float_classic_trap_is_exact():
    # 0.1 + 0.2 != 0.3 in binary floating point; with minor units it is exact.
    assert m.parse_amount("0.10") + m.parse_amount("0.20") == m.parse_amount("0.30")


def test_format():
    assert m.format_amount(123456) == "1,234.56"
    assert m.format_amount(5) == "0.05"
    assert m.format_amount(0) == "0.00"
    assert m.format_money(120000, "EUR") == "€1,200.00"
    assert m.format_money(9990, "ILS") == "₪99.90"
    assert m.format_money(100, "USD") == "$1.00"
    assert m.format_money(None, "EUR") == ""
    assert m.to_input(120050) == "1200.50"
    with pytest.raises(TypeError):
        m.format_amount(1.5)


@pytest.mark.parametrize("total, parts, expected", [
    (120000, 3, [40000, 40000, 40000]),
    (100000, 3, [33333, 33333, 33334]),
    (100, 7, [14, 14, 14, 14, 14, 14, 16]),
    (1, 1, [1]),
])
def test_split_evenly_exact(total, parts, expected):
    result = m.split_evenly(total, parts)
    assert result == expected
    assert sum(result) == total


def _assert_valid_split(total, parts, result):
    assert len(result) == parts
    assert sum(result) == total, (total, parts, result)       # never a cent more or less
    assert all(isinstance(x, int) and x > 0 for x in result)  # integers, no zero installments
    base = total // parts
    assert result[:-1] == [base] * (parts - 1)                # all but the last are equal
    assert 0 <= result[-1] - base < parts                     # remainder < one cent per part, on the last


def test_split_sums_exactly_for_every_small_total_and_count():
    # Exhaustive: every total from €0.01 to €30.00 split into 1..36 installments.
    checked = 0
    for total in range(1, 3001):
        for parts in range(1, min(36, total) + 1):
            _assert_valid_split(total, parts, m.split_evenly(total, parts))
            checked += 1
    assert checked > 100_000


@pytest.mark.parametrize("total", [100000, 120000, 99999, 100001, 1, 7, 333, 1000000, 123456789, m.MAX_MINOR])
@pytest.mark.parametrize("parts", [1, 2, 3, 6, 7, 9, 11, 12, 24, 36, 60])
def test_split_sums_exactly_for_typical_and_extreme_totals(total, parts):
    if parts > total:
        # e.g. €0.07 into 9 installments would need zero-amount installments → rejected
        with pytest.raises(ValidationError):
            m.split_evenly(total, parts)
        return
    _assert_valid_split(total, parts, m.split_evenly(total, parts))


def test_split_random_large_totals():
    import random
    rng = random.Random(20261112)
    for _ in range(20000):
        total = rng.randint(1, m.MAX_MINOR)
        parts = rng.randint(1, min(120, total))
        _assert_valid_split(total, parts, m.split_evenly(total, parts))


def test_split_spec_examples_in_euros():
    assert [m.format_money(x, "EUR") for x in m.split_evenly(100000, 3)] == ["€333.33", "€333.33", "€333.34"]
    assert [m.format_money(x, "EUR") for x in m.split_evenly(120000, 3)] == ["€400.00", "€400.00", "€400.00"]
    assert m.format_money(sum(m.split_evenly(100000, 3)), "EUR") == "€1,000.00"


def test_split_rejects_bad_input():
    with pytest.raises(ValueError):
        m.split_evenly(True, 1)   # bool is not money
    with pytest.raises(ValueError):
        m.split_evenly(1000, 2.0)
    with pytest.raises(ValidationError):
        m.split_evenly(2, 3)
    with pytest.raises(ValueError):
        m.split_evenly(0, 2)
    with pytest.raises(ValueError):
        m.split_evenly(100, 0)


def test_sum_by_currency_never_mixes_and_never_counts_missing_as_zero():
    totals = m.sum_by_currency([("EUR", 120000), ("ILS", 5000), ("EUR", 100), ("USD", None), ("ILS", None)])
    assert totals.totals == {"EUR": 120100, "ILS": 5000}
    assert "USD" not in totals.totals
    assert totals.missing_count == 2
