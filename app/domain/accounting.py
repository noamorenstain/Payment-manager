"""Accounting model (plan §3.3) as pure functions.

The SQL view ``v_obligation_balance`` computes the same values for queries; tests assert
that both agree. Original amounts are never modified — cancel and restructure only change
the lifecycle, and the split of the remaining balance is derived:

    paid         = sum of non-voided payment entries
    remaining    = amount - paid                       (None if amount missing)
    outstanding  = remaining if active        else 0
    canceled     = remaining if canceled      else 0
    transferred  = remaining if restructured  else 0   (moved to child obligations)

"Paid in full" requires an ACTIVE obligation with a known amount and paid == amount, so a
canceled balance can never be classified as paid.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

ACTIVE, CANCELED, RESTRUCTURED = "active", "canceled", "restructured"
LIFECYCLES = (ACTIVE, CANCELED, RESTRUCTURED)

# primary states (match v_obligation_balance.primary_state)
STATE_OPEN = "open"
STATE_PARTIAL = "partial"
STATE_PAID = "paid"
STATE_MISSING = "missing_amount"
STATE_CANCELED = "canceled"
STATE_RESTRUCTURED = "restructured"

# invoice-level states
INV_OPEN = "open"
INV_PARTIAL = "partial"
INV_PAID = "paid"
INV_MISSING = "missing_amount"
INV_CANCELED = "canceled"
INV_CLOSED_PARTLY_CANCELED = "closed_partly_canceled"


@dataclass(frozen=True)
class ObligationBalance:
    amount_minor: int | None
    paid_minor: int
    lifecycle: str
    is_child: bool = False  # created by a restructure (has a parent obligation)

    @property
    def remaining_minor(self) -> int | None:
        return None if self.amount_minor is None else self.amount_minor - self.paid_minor

    @property
    def outstanding_minor(self) -> int | None:
        return self.remaining_minor if self.lifecycle == ACTIVE else 0

    @property
    def canceled_minor(self) -> int | None:
        return self.remaining_minor if self.lifecycle == CANCELED else 0

    @property
    def transferred_minor(self) -> int | None:
        return self.remaining_minor if self.lifecycle == RESTRUCTURED else 0

    @property
    def primary_state(self) -> str:
        if self.lifecycle == CANCELED:
            return STATE_CANCELED
        if self.lifecycle == RESTRUCTURED:
            return STATE_RESTRUCTURED
        if self.amount_minor is None:
            return STATE_MISSING
        if self.paid_minor == self.amount_minor:
            return STATE_PAID
        if self.paid_minor > 0:
            return STATE_PARTIAL
        return STATE_OPEN

    @property
    def is_paid_in_full(self) -> bool:
        return (self.lifecycle == ACTIVE and self.amount_minor is not None
                and self.amount_minor > 0 and self.paid_minor == self.amount_minor)

    @property
    def is_partially_paid(self) -> bool:
        """Independent flag: some but not all paid (may also be overdue, canceled, …)."""
        return self.amount_minor is not None and 0 < self.paid_minor < self.amount_minor


def obligation_balance(amount_minor: int | None, valid_payments: Iterable[int], lifecycle: str,
                       is_child: bool = False) -> ObligationBalance:
    if lifecycle not in LIFECYCLES:
        raise ValueError(f"unknown lifecycle: {lifecycle}")
    paid = 0
    for p in valid_payments:
        if not isinstance(p, int) or p <= 0:
            raise ValueError("payments must be positive integers")
        paid += p
    if amount_minor is not None and paid > amount_minor:
        raise ValueError("paid exceeds amount")
    if amount_minor is None and paid:
        raise ValueError("payments on an obligation with a missing amount")
    return ObligationBalance(amount_minor, paid, lifecycle, is_child)


@dataclass(frozen=True)
class InvoiceSummary:
    total_minor: int | None
    paid_minor: int
    canceled_minor: int | None
    outstanding_minor: int | None
    state: str

    @property
    def is_paid_in_full(self) -> bool:
        return self.state == INV_PAID


def invoice_summary(total_minor: int | None, balances: Sequence[ObligationBalance]) -> InvoiceSummary:
    """Totals over ALL obligations of an invoice (restructured parents AND their children).

    A restructured parent contributes only its ``paid``; its transferred amount is counted
    through the child obligations, so nothing is double-counted.
    """
    paid = sum(b.paid_minor for b in balances)
    missing = any(b.amount_minor is None for b in balances)
    canceled = None if any(b.lifecycle == CANCELED and b.amount_minor is None for b in balances) \
        else sum(b.canceled_minor for b in balances if b.amount_minor is not None)
    outstanding = None if any(b.lifecycle == ACTIVE and b.amount_minor is None for b in balances) \
        else sum(b.outstanding_minor for b in balances if b.amount_minor is not None)

    active_or_child = [b for b in balances if b.lifecycle != RESTRUCTURED]
    if balances and all(b.lifecycle == CANCELED for b in active_or_child) and paid == 0:
        state = INV_CANCELED
    elif missing and any(b.lifecycle == ACTIVE and b.amount_minor is None for b in balances):
        state = INV_MISSING
    elif outstanding == 0 and (canceled or 0) == 0 and not missing and balances:
        state = INV_PAID
    elif outstanding == 0 and (canceled is None or canceled > 0):
        state = INV_CLOSED_PARTLY_CANCELED
    elif paid > 0:
        state = INV_PARTIAL
    else:
        state = INV_OPEN
    return InvoiceSummary(total_minor, paid, canceled, outstanding, state)


def invoice_invariant_holds(total_minor: int | None, balances: Sequence[ObligationBalance]) -> bool:
    """total = Σ paid + Σ canceled + Σ outstanding (undefined while any amount is missing)."""
    if total_minor is None or any(b.amount_minor is None for b in balances):
        return True
    s = invoice_summary(total_minor, balances)
    return total_minor == s.paid_minor + s.canceled_minor + s.outstanding_minor
