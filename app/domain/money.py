"""Exact money handling. Amounts are integers in minor units (agorot / cents).

Binary floating point is never used: user input is parsed with :class:`decimal.Decimal`
and converted to an ``int``; all arithmetic is integer arithmetic.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.domain.errors import ValidationError
from app.i18n import he

MINOR_DIGITS = 2
MINOR_FACTOR = 10 ** MINOR_DIGITS
MAX_MINOR = 99_999_999_999  # 999,999,999.99 — a sanity ceiling for manual entry

CURRENCY_SYMBOLS = {"ILS": "₪", "EUR": "€", "USD": "$"}

# 1234 | 1,234 | 1,234,567 | optional .d or .dd   ([0-9], not \d: \d matches non-ASCII digits)
_AMOUNT_RE = re.compile(r"^(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]{1,2})?$")
_TOO_MANY_DECIMALS_RE = re.compile(r"^[0-9][0-9,]*\.[0-9]{3,}$")


def parse_amount(text: str | None, field: str | None = None, *, required: bool = True,
                 allow_zero: bool = False) -> int | None:
    """Parse user input such as ``1,200`` / ``1200.5`` / ``1,234.56`` into minor units."""
    raw = (text or "").strip().replace(" ", "").replace(" ", "")
    for symbol in CURRENCY_SYMBOLS.values():
        raw = raw.replace(symbol, "")
    if not raw:
        if required:
            raise ValidationError(he.AMOUNT_REQUIRED, field)
        return None
    if raw.startswith("-"):
        raise ValidationError(he.AMOUNT_NEGATIVE, field)
    if _TOO_MANY_DECIMALS_RE.match(raw):
        raise ValidationError(he.AMOUNT_TOO_MANY_DECIMALS, field)
    if not _AMOUNT_RE.match(raw):
        raise ValidationError(he.AMOUNT_BAD_FORMAT, field)
    try:
        value = Decimal(raw.replace(",", ""))
    except InvalidOperation:  # pragma: no cover - regex already guarantees validity
        raise ValidationError(he.AMOUNT_BAD_FORMAT, field) from None
    minor = int(value * MINOR_FACTOR)
    if Decimal(minor) != value * MINOR_FACTOR:  # pragma: no cover - guarded by regex
        raise ValidationError(he.AMOUNT_TOO_MANY_DECIMALS, field)
    if minor == 0 and not allow_zero:
        raise ValidationError(he.AMOUNT_ZERO, field)
    if minor > MAX_MINOR:
        raise ValidationError(he.AMOUNT_TOO_LARGE, field)
    return minor


def format_amount(minor: int) -> str:
    """``123456`` → ``1,234.56``."""
    if not isinstance(minor, int):
        raise TypeError("money must be an integer number of minor units")
    sign = "-" if minor < 0 else ""
    whole, frac = divmod(abs(minor), MINOR_FACTOR)
    return f"{sign}{whole:,}.{frac:0{MINOR_DIGITS}d}"


def format_money(minor: int | None, currency: str) -> str:
    """``123456, 'EUR'`` → ``€1,234.56``. Missing amounts render as an empty string."""
    if minor is None:
        return ""
    symbol = CURRENCY_SYMBOLS.get(currency, currency + " ")
    return f"{symbol}{format_amount(minor)}"


def to_input(minor: int | None) -> str:
    """Value for an editable amount field: ``123456`` → ``1234.56``."""
    if minor is None:
        return ""
    whole, frac = divmod(minor, MINOR_FACTOR)
    return f"{whole}.{frac:0{MINOR_DIGITS}d}"


def split_evenly(total_minor: int, parts: int) -> list[int]:
    """Split exactly; the rounding remainder goes to the LAST part (1000.00/3 → 333.33, 333.33, 333.34)."""
    if type(total_minor) is not int or total_minor <= 0:  # type() excludes bool
        raise ValueError("total must be a positive integer")
    if type(parts) is not int or parts < 1:
        raise ValueError("parts must be a positive integer")
    if parts > total_minor:
        raise ValidationError(he.INSTALLMENTS_TOO_MANY)
    base = total_minor // parts
    result = [base] * parts
    result[-1] = total_minor - base * (parts - 1)
    return result


@dataclass
class CurrencyTotals:
    """Per-currency totals; unknown (missing) amounts are counted, never treated as zero."""

    totals: dict[str, int]
    missing_count: int


def sum_by_currency(items: Iterable[tuple[str, int | None]]) -> CurrencyTotals:
    totals: dict[str, int] = {}
    missing = 0
    for currency, minor in items:
        if minor is None:
            missing += 1
            continue
        totals[currency] = totals.get(currency, 0) + minor
    return CurrencyTotals(totals=totals, missing_count=missing)
