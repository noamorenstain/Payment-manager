"""Obligation operations: due-date changes (postpone / edit) and cancellation.

Neither operation touches payment entries or other obligations. Original amounts and the
original due date are never changed; history is kept in ``postponements`` and the audit log.
"""

from __future__ import annotations

import datetime as dt
import sqlite3

from app.clock import Clock
from app.domain import dates as d
from app.domain.errors import ValidationError
from app.i18n import he
from app.services import audit
from app.services.common import NotFound, clean_text, ts


def get(conn: sqlite3.Connection, obligation_id: int) -> sqlite3.Row:
    row = conn.execute("""
        SELECT o.*, b.paid_minor, b.remaining_minor, b.outstanding_minor, b.canceled_minor,
               b.transferred_minor, b.primary_state
        FROM obligations o JOIN v_obligation_balance b ON b.obligation_id = o.id
        WHERE o.id = ?""", (obligation_id,)).fetchone()
    if row is None:
        raise NotFound(f"obligation {obligation_id}")
    return row


def is_open(row: sqlite3.Row) -> bool:
    """Active with something still to pay (or an amount still missing)."""
    return row["lifecycle"] == "active" and (row["amount_minor"] is None or row["outstanding_minor"] > 0)


def _require_open(row: sqlite3.Row, message: str) -> None:
    if row["lifecycle"] != "active":
        raise ValidationError(he.OBLIGATION_NOT_ACTIVE)
    if not is_open(row):
        raise ValidationError(message)


def change_due_date(conn: sqlite3.Connection, clock: Clock, obligation_id: int, new_date: dt.date,
                    reason: str | None = None, *, postpone: bool = True,
                    move_manual_reminders: bool = False) -> None:
    """Postpone (new date must be later) or edit (any different date). Call inside a transaction.

    Manual reminders keep their own dates unless ``move_manual_reminders`` is explicitly set
    (default False — plan D6); then only PENDING reminders shift by the same number of days.
    The automatic reminder is never stored, so it follows the new due date by itself.
    """
    row = get(conn, obligation_id)
    _require_open(row, he.POSTPONE_NOTHING_OPEN)
    old_date = d.from_iso(row["current_due_date"])
    if postpone:
        d.require_after(new_date, old_date, "new_due_date")
    elif new_date == old_date:
        raise ValidationError(he.DUE_DATE_UNCHANGED, "due_date")

    reason = clean_text(reason, 300)
    delta = (new_date - old_date).days
    moved = []
    if move_manual_reminders:
        for rem in conn.execute("SELECT id, remind_on FROM reminders WHERE obligation_id = ? AND status = 'pending'",
                                (obligation_id,)).fetchall():
            shifted = d.from_iso(rem["remind_on"]) + dt.timedelta(days=delta)
            if not d.MIN_YEAR <= shifted.year <= d.MAX_YEAR:
                raise ValidationError(he.DATE_YEAR_RANGE.format(min=d.MIN_YEAR, max=d.MAX_YEAR), "new_due_date")
            moved.append((rem["id"], rem["remind_on"], shifted.isoformat()))

    now = ts(clock)
    conn.execute("INSERT INTO postponements (obligation_id, old_due_date, new_due_date, reason, "
                 "moved_manual_reminders, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                 (obligation_id, old_date.isoformat(), new_date.isoformat(), reason, int(bool(moved)), now))
    conn.execute("UPDATE obligations SET current_due_date = ?, updated_at = ? WHERE id = ?",
                 (new_date.isoformat(), now, obligation_id))
    for rem_id, _old, new in moved:
        conn.execute("UPDATE reminders SET remind_on = ?, updated_at = ? WHERE id = ?", (new, now, rem_id))
    audit.record(conn, clock, "obligation", obligation_id, "postpone" if postpone else "due_date_change",
                 old={"current_due_date": old_date.isoformat()},
                 new={"current_due_date": new_date.isoformat(),
                      "moved_reminders": [{"id": r, "from": o, "to": n} for r, o, n in moved]},
                 details=reason)


def resolve_pending_reminders(conn: sqlite3.Connection, clock: Clock, obligation_id: int, status: str,
                              note: str) -> int:
    rows = conn.execute("SELECT id FROM reminders WHERE obligation_id = ? AND status = 'pending'",
                        (obligation_id,)).fetchall()
    now = ts(clock)
    for r in rows:
        conn.execute("UPDATE reminders SET status = ?, resolved_at = ?, resolution_note = ?, updated_at = ? "
                     "WHERE id = ?", (status, now, note, now, r["id"]))
    if rows:
        audit.record(conn, clock, "obligation", obligation_id, "reminders_resolved",
                     new={"reminder_ids": [r["id"] for r in rows], "status": status}, details=note)
    return len(rows)


def cancel(conn: sqlite3.Connection, clock: Clock, obligation_id: int, reason: str | None) -> None:
    """Cancel the unpaid remainder. Payments stay valid; nothing is deleted. Inside a transaction."""
    reason = clean_text(reason, 300)
    if not reason:
        raise ValidationError(he.CANCEL_REASON_REQUIRED, "reason")
    row = get(conn, obligation_id)
    _require_open(row, he.CANCEL_NOTHING_OPEN)
    now = ts(clock)
    conn.execute("UPDATE obligations SET lifecycle = 'canceled', closed_at = ?, close_reason = ?, "
                 "closed_paid_minor = ?, updated_at = ? WHERE id = ?",
                 (now, reason, row["paid_minor"], now, obligation_id))
    after = get(conn, obligation_id)
    audit.record(conn, clock, "obligation", obligation_id, "cancel",
                 old={"lifecycle": "active", "outstanding_minor": row["outstanding_minor"]},
                 new={"lifecycle": "canceled", "paid_minor": after["paid_minor"],
                      "canceled_minor": after["canceled_minor"]},
                 details=reason)
    resolve_pending_reminders(conn, clock, obligation_id, "cleared", he.REMINDER_RESOLVED_CANCELED)


def postponements(conn: sqlite3.Connection, obligation_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM postponements WHERE obligation_id = ? ORDER BY created_at, id",
                        (obligation_id,)).fetchall()
