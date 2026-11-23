"""Actual payments: record, void (with reason) and correct (void + linked new entry).

Payment entries are never edited or deleted. The database independently rejects
overpayment and payments on closed / missing-amount obligations; the checks here exist to
give precise Hebrew messages before reaching those guards.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass

from app.clock import Clock
from app.domain import dates as d
from app.domain import money as m
from app.domain.errors import ValidationError
from app.i18n import he
from app.paths import DataPaths
from app.services import attachments, audit, obligations
from app.services.attachments import StagedFile
from app.services.common import NotFound, clean_text, ts

METHODS = ("bank_transfer", "card", "cash", "check", "other")


@dataclass
class PaymentInput:
    amount_minor: int
    paid_on: dt.date
    method: str
    reference: str | None = None
    notes: str | None = None


@dataclass
class PaymentResult:
    entry_id: int
    already_recorded: bool = False   # same request_token submitted again
    now_paid_in_full: bool = False


def get(conn: sqlite3.Connection, entry_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM payment_entries WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        raise NotFound(f"payment {entry_id}")
    return row


def _validate(conn: sqlite3.Connection, clock: Clock, ob: sqlite3.Row, data: PaymentInput) -> None:
    if ob["lifecycle"] != "active":
        raise ValidationError(he.DB_ERRORS["payment_on_inactive_obligation"])
    if ob["amount_minor"] is None:
        raise ValidationError(he.DB_ERRORS["payment_on_missing_amount"])
    if type(data.amount_minor) is not int or data.amount_minor <= 0:
        raise ValidationError(he.AMOUNT_ZERO, "amount")
    if data.amount_minor > ob["outstanding_minor"]:
        raise ValidationError(he.PAYMENT_EXCEEDS_OUTSTANDING.format(
            outstanding=m.format_money(ob["outstanding_minor"], ob["currency"])), "amount")
    d.require_not_future(data.paid_on, clock.today(), "paid_on", he.DATE_PAYMENT_IN_FUTURE)
    if data.method not in METHODS:
        raise ValidationError(he.PAYMENT_METHOD_REQUIRED, "method")


def _insert(conn: sqlite3.Connection, clock: Clock, obligation_id: int, data: PaymentInput,
            request_token: str | None, corrects_entry_id: int | None = None) -> int:
    now = ts(clock)
    entry_id = conn.execute(
        "INSERT INTO payment_entries (obligation_id, amount_minor, paid_on, method, reference, notes, "
        "corrects_entry_id, request_token, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (obligation_id, data.amount_minor, data.paid_on.isoformat(), data.method,
         clean_text(data.reference, 120), clean_text(data.notes, 1000), corrects_entry_id, request_token,
         now, now)).lastrowid
    audit.record(conn, clock, "payment", entry_id, "payment_correction" if corrects_entry_id else "payment_recorded",
                 new={"obligation_id": obligation_id, "amount_minor": data.amount_minor,
                      "paid_on": data.paid_on.isoformat(), "method": data.method,
                      "reference": clean_text(data.reference, 120), "corrects_entry_id": corrects_entry_id})
    return entry_id


def _after_payment(conn: sqlite3.Connection, clock: Clock, obligation_id: int) -> bool:
    ob = obligations.get(conn, obligation_id)
    if ob["primary_state"] == "paid":
        obligations.resolve_pending_reminders(conn, clock, obligation_id, "handled", he.REMINDER_RESOLVED_PAID)
        return True
    return False


def find_by_token(conn: sqlite3.Connection, request_token: str | None) -> sqlite3.Row | None:
    if not request_token:
        return None
    return conn.execute("SELECT * FROM payment_entries WHERE request_token = ?", (request_token,)).fetchone()


def record(conn: sqlite3.Connection, clock: Clock, paths: DataPaths, obligation_id: int, data: PaymentInput, *,
           request_token: str | None = None, receipt: StagedFile | None = None) -> PaymentResult:
    """Record an actual payment. Call inside a transaction."""
    existing = find_by_token(conn, request_token)
    if existing is not None:
        return PaymentResult(existing["id"], already_recorded=True)
    ob = obligations.get(conn, obligation_id)
    _validate(conn, clock, ob, data)
    entry_id = _insert(conn, clock, obligation_id, data, request_token)
    paid_in_full = _after_payment(conn, clock, obligation_id)
    if receipt is not None:  # last step: moves the file into permanent storage
        attachments.commit_staged(conn, paths, clock, receipt, payment_entry_id=entry_id, kind="receipt")
    return PaymentResult(entry_id, now_paid_in_full=paid_in_full)


def void(conn: sqlite3.Connection, clock: Clock, entry_id: int, reason: str | None, *,
         correction: PaymentInput | None = None, request_token: str | None = None) -> int | None:
    """Void a payment (kept, struck through) and optionally record its corrected version.

    Returns the id of the corrected entry, if any. Call inside a transaction.
    """
    reason = clean_text(reason, 300)
    if not reason:
        raise ValidationError(he.VOID_REASON_REQUIRED, "void_reason")
    entry = get(conn, entry_id)
    if entry["voided_at"] is not None:
        raise ValidationError(he.DB_ERRORS["payment_already_voided"])
    ob = obligations.get(conn, entry["obligation_id"])
    if ob["lifecycle"] == "restructured":
        raise ValidationError(he.DB_ERRORS["void_on_restructured"])
    if correction is not None and find_by_token(conn, request_token) is not None:
        return find_by_token(conn, request_token)["id"]

    now = ts(clock)
    conn.execute("UPDATE payment_entries SET voided_at = ?, void_reason = ?, updated_at = ? WHERE id = ?",
                 (now, reason, now, entry_id))
    audit.record(conn, clock, "payment", entry_id, "payment_voided",
                 old={"amount_minor": entry["amount_minor"], "paid_on": entry["paid_on"]}, details=reason)

    if correction is None:
        return None
    ob = obligations.get(conn, entry["obligation_id"])
    _validate(conn, clock, ob, correction)
    new_id = _insert(conn, clock, entry["obligation_id"], correction, request_token, corrects_entry_id=entry_id)
    _after_payment(conn, clock, entry["obligation_id"])
    return new_id


def for_obligations(conn: sqlite3.Connection, obligation_ids: list[int]) -> list[sqlite3.Row]:
    if not obligation_ids:
        return []
    marks = ",".join("?" * len(obligation_ids))
    return conn.execute(f"SELECT * FROM payment_entries WHERE obligation_id IN ({marks}) "
                        f"ORDER BY paid_on DESC, id DESC", obligation_ids).fetchall()
