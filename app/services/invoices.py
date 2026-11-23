"""Invoices (manual entry). Phase B: one-time payment = one invoice + one obligation.

Every change runs in one transaction, writes an audit event and re-checks the accounting
invariant ``total = paid + canceled + outstanding`` before committing.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass

from app.clock import Clock
from app.domain import accounting as acc
from app.domain import dates as d
from app.domain.errors import ValidationError
from app.i18n import he
from app.paths import DataPaths
from app.services import attachments, audit, lookups, obligations, payments
from app.services.attachments import StagedFile
from app.services.common import NeedsConfirmation, NotFound, clean_text, require, same_name, ts


@dataclass
class InvoiceInput:
    supplier_name: str | None
    property_id: int | None
    category_id: int | None
    currency: str | None
    amount_minor: int | None
    due_date: dt.date | None
    invoice_number: str | None = None
    issue_date: dt.date | None = None
    received_date: dt.date | None = None
    notes: str | None = None
    reminder_lead_days: int | None = None


# ------------------------------------------------------------------ validation

def _validate_refs(conn: sqlite3.Connection, data: InvoiceInput, *, keep_property: int | None = None,
                   keep_category: int | None = None) -> None:
    """Property required; property/category must be active (an existing archived choice may be kept)."""
    require(data.property_id is not None, he.PROPERTY_REQUIRED, "property_id")
    prop = conn.execute("SELECT * FROM properties WHERE id = ?", (data.property_id,)).fetchone()
    require(prop is not None, he.PROPERTY_REQUIRED, "property_id")
    require(prop["archived_at"] is None or prop["id"] == keep_property, he.LOOKUP_ARCHIVED_CHOICE, "property_id")
    if data.category_id is not None:
        cat = conn.execute("SELECT * FROM categories WHERE id = ?", (data.category_id,)).fetchone()
        require(cat is not None, he.CATEGORY_INVALID, "category_id")
        require(cat["archived_at"] is None or cat["id"] == keep_category, he.LOOKUP_ARCHIVED_CHOICE, "category_id")


def _validate_dates(clock: Clock, data: InvoiceInput, confirmed: bool) -> None:
    today = clock.today()
    if data.issue_date:
        d.require_not_future(data.issue_date, today, "issue_date")
    if data.received_date:
        d.require_not_future(data.received_date, today, "received_date")
    if data.issue_date and data.received_date and data.received_date < data.issue_date and not confirmed:
        raise NeedsConfirmation([he.WARN_RECEIVED_BEFORE_ISSUE])


def _validate_lead_days(value: int | None) -> None:
    if value is not None:
        require(0 <= value <= 365, he.LEAD_DAYS_RANGE, "reminder_lead_days")


def _check_invariant(conn: sqlite3.Connection, invoice_id: int) -> None:
    inv = get_row(conn, invoice_id)
    balances = _balances(conn, invoice_id)
    if not acc.invoice_invariant_holds(inv["total_minor"], balances):
        raise RuntimeError(f"accounting invariant violated for invoice {invoice_id}")  # rolls back


def _balances(conn: sqlite3.Connection, invoice_id: int) -> list[acc.ObligationBalance]:
    rows = conn.execute("SELECT amount_minor, paid_minor, lifecycle, parent_obligation_id "
                        "FROM v_obligation_balance WHERE invoice_id = ?", (invoice_id,)).fetchall()
    return [acc.ObligationBalance(r["amount_minor"], r["paid_minor"], r["lifecycle"],
                                  r["parent_obligation_id"] is not None) for r in rows]


# ------------------------------------------------------------------ create

def find_by_token(conn: sqlite3.Connection, request_token: str | None) -> sqlite3.Row | None:
    if not request_token:
        return None
    return conn.execute("SELECT * FROM invoices WHERE request_token = ?", (request_token,)).fetchone()


def create(conn: sqlite3.Connection, clock: Clock, paths: DataPaths, data: InvoiceInput, *,
           staged_file: StagedFile | None = None, request_token: str | None = None,
           confirmed: bool = False) -> int:
    """Create an invoice with a single obligation (one-time payment). Inside a transaction."""
    existing = find_by_token(conn, request_token)
    if existing is not None:
        return existing["id"]

    _validate_refs(conn, data)
    require(data.currency is not None and conn.execute(
        "SELECT 1 FROM currencies WHERE code = ? AND active = 1", (data.currency,)).fetchone() is not None,
        he.CURRENCY_REQUIRED, "currency")
    require(data.amount_minor is not None and data.amount_minor > 0, he.AMOUNT_REQUIRED, "amount")
    require(data.due_date is not None, he.DATE_REQUIRED, "due_date")
    _validate_lead_days(data.reminder_lead_days)
    _validate_dates(clock, data, confirmed)

    supplier_id = lookups.resolve_or_create_supplier(conn, clock, data.supplier_name)
    now = ts(clock)
    number = clean_text(data.invoice_number, 80)
    notes = clean_text(data.notes, 2000)
    invoice_id = conn.execute(
        "INSERT INTO invoices (supplier_id, property_id, category_id, invoice_number, issue_date, received_date, "
        "currency, total_minor, notes, request_token, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (supplier_id, data.property_id, data.category_id, number, d.to_iso(data.issue_date),
         d.to_iso(data.received_date), data.currency, data.amount_minor, notes, request_token, now, now)).lastrowid
    due = data.due_date.isoformat()
    obligation_id = conn.execute(
        "INSERT INTO obligations (invoice_id, supplier_id, property_id, category_id, currency, amount_minor, "
        "original_due_date, current_due_date, reminder_lead_days, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (invoice_id, supplier_id, data.property_id, data.category_id, data.currency, data.amount_minor, due, due,
         data.reminder_lead_days, now, now)).lastrowid
    audit.record(conn, clock, "invoice", invoice_id, "create",
                 new={"supplier_id": supplier_id, "property_id": data.property_id, "category_id": data.category_id,
                      "invoice_number": number, "currency": data.currency, "total_minor": data.amount_minor,
                      "due_date": due, "issue_date": d.to_iso(data.issue_date),
                      "received_date": d.to_iso(data.received_date), "obligation_id": obligation_id})
    _check_invariant(conn, invoice_id)
    if staged_file is not None:  # last step: moves the file into permanent storage
        attachments.commit_staged(conn, paths, clock, staged_file, invoice_id=invoice_id, kind="invoice")
    return invoice_id


# ------------------------------------------------------------------ read

def get_row(conn: sqlite3.Connection, invoice_id: int) -> sqlite3.Row:
    row = conn.execute("""
        SELECT i.*, s.name AS supplier_name, s.archived_at AS supplier_archived,
               p.name AS property_name, p.is_general AS property_is_general, p.country AS property_country,
               c.name AS category_name
        FROM invoices i
        JOIN suppliers s ON s.id = i.supplier_id
        JOIN properties p ON p.id = i.property_id
        LEFT JOIN categories c ON c.id = i.category_id
        WHERE i.id = ?""", (invoice_id,)).fetchone()
    if row is None:
        raise NotFound(f"invoice {invoice_id}")
    return row


def obligations_of(conn: sqlite3.Connection, invoice_id: int) -> list[sqlite3.Row]:
    return conn.execute("""
        SELECT o.*, b.paid_minor, b.remaining_minor, b.outstanding_minor, b.canceled_minor,
               b.transferred_minor, b.primary_state
        FROM obligations o JOIN v_obligation_balance b ON b.obligation_id = o.id
        WHERE o.invoice_id = ? ORDER BY o.installment_no, o.original_due_date, o.id""", (invoice_id,)).fetchall()


def view(conn: sqlite3.Connection, invoice_id: int) -> dict:
    """Everything the details page shows. Paid and canceled records are fully viewable."""
    inv = get_row(conn, invoice_id)
    obs = obligations_of(conn, invoice_id)
    ob_ids = [o["id"] for o in obs]
    entries = payments.for_obligations(conn, ob_ids)
    entry_ids = [e["id"] for e in entries]
    marks_o = ",".join("?" * len(ob_ids)) or "NULL"
    marks_e = ",".join("?" * len(entry_ids)) or "NULL"
    docs = conn.execute(
        f"SELECT * FROM attachments WHERE invoice_id = ? OR obligation_id IN ({marks_o}) "
        f"OR payment_entry_id IN ({marks_e}) ORDER BY id", (invoice_id, *ob_ids, *entry_ids)).fetchall()
    postponements = conn.execute(
        f"SELECT * FROM postponements WHERE obligation_id IN ({marks_o}) ORDER BY created_at, id", ob_ids).fetchall()
    reminders = conn.execute(
        f"SELECT * FROM reminders WHERE obligation_id IN ({marks_o}) ORDER BY remind_on, id", ob_ids).fetchall()
    summary = acc.invoice_summary(inv["total_minor"], _balances(conn, invoice_id))
    return {
        "invoice": inv,
        "obligations": obs,
        "payments": entries,
        "invoice_documents": [a for a in docs if a["invoice_id"] is not None or a["obligation_id"] is not None],
        "receipts_by_entry": _group(docs, "payment_entry_id"),
        "postponements": postponements,
        "reminders": reminders,
        "summary": summary,
        "audit": audit.for_invoice(conn, invoice_id),
    }


def _group(rows, key) -> dict:
    out: dict = {}
    for r in rows:
        if r[key] is not None:
            out.setdefault(r[key], []).append(r)
    return out


# ------------------------------------------------------------------ update / cancel

def update(conn: sqlite3.Connection, clock: Clock, invoice_id: int, data: InvoiceInput, *,
           confirmed: bool = False, due_change_reason: str | None = None) -> None:
    """Edit invoice details. Amount and due date can be edited only on a single, still-open
    obligation; currency is fixed once created. Inside a transaction."""
    inv = get_row(conn, invoice_id)
    obs = obligations_of(conn, invoice_id)
    _validate_refs(conn, data, keep_property=inv["property_id"], keep_category=inv["category_id"])
    _validate_lead_days(data.reminder_lead_days)
    _validate_dates(clock, data, confirmed)
    if data.supplier_name and same_name(data.supplier_name, inv["supplier_name"]):
        supplier_id = inv["supplier_id"]  # unchanged (even if that supplier was archived since)
    else:
        supplier_id = lookups.resolve_or_create_supplier(conn, clock, data.supplier_name)

    old = {k: inv[k] for k in ("supplier_id", "property_id", "category_id", "invoice_number", "issue_date",
                               "received_date", "notes", "total_minor")}
    new = {
        "supplier_id": supplier_id,
        "property_id": data.property_id,
        "category_id": data.category_id,
        "invoice_number": clean_text(data.invoice_number, 80),
        "issue_date": d.to_iso(data.issue_date),
        "received_date": d.to_iso(data.received_date),
        "notes": clean_text(data.notes, 2000),
        "total_minor": inv["total_minor"],
    }
    single = obs[0] if len(obs) == 1 else None
    if data.amount_minor is not None and data.amount_minor != inv["total_minor"]:
        require(single is not None and single["lifecycle"] == "active", he.AMOUNT_EDIT_NOT_ALLOWED, "amount")
        require(data.amount_minor >= single["paid_minor"], he.DB_ERRORS["amount_below_paid"], "amount")
        new["total_minor"] = data.amount_minor

    now = ts(clock)
    if old != new:
        conn.execute("UPDATE invoices SET supplier_id=?, property_id=?, category_id=?, invoice_number=?, issue_date=?, "
                     "received_date=?, notes=?, total_minor=?, updated_at=? WHERE id=?",
                     (*new.values(), now, invoice_id))
        old_c, new_c = audit.changed_fields(old, new)
        audit.record(conn, clock, "invoice", invoice_id, "update", old=old_c, new=new_c)

    for ob in obs:
        sets, params = [], []
        for col in ("supplier_id", "property_id", "category_id"):
            if ob[col] != new[col]:
                sets.append(f"{col} = ?")
                params.append(new[col])
        if single is not None and ob["reminder_lead_days"] != data.reminder_lead_days and ob["lifecycle"] == "active":
            sets.append("reminder_lead_days = ?")
            params.append(data.reminder_lead_days)
        if single is not None and new["total_minor"] != ob["amount_minor"]:
            sets.append("amount_minor = ?")
            params.append(new["total_minor"])
        if sets:
            conn.execute(f"UPDATE obligations SET {', '.join(sets)}, updated_at = ? WHERE id = ?",
                         (*params, now, ob["id"]))

    if single is not None and data.due_date is not None and data.due_date.isoformat() != single["current_due_date"]:
        obligations.change_due_date(conn, clock, single["id"], data.due_date,
                                    due_change_reason or he.DUE_DATE_EDIT_REASON, postpone=False)
    _check_invariant(conn, invoice_id)


def cancel(conn: sqlite3.Connection, clock: Clock, invoice_id: int, reason: str | None) -> int:
    """Cancel every still-open obligation of the invoice. Paid parts stay paid. Inside a transaction."""
    reason = clean_text(reason, 300)
    if not reason:
        raise ValidationError(he.CANCEL_REASON_REQUIRED, "reason")
    inv = get_row(conn, invoice_id)
    open_obs = [o for o in obligations_of(conn, invoice_id) if obligations.is_open(o)]
    if not open_obs:
        raise ValidationError(he.CANCEL_NOTHING_OPEN)
    for ob in open_obs:
        obligations.cancel(conn, clock, ob["id"], reason)
    if inv["canceled_at"] is None:
        conn.execute("UPDATE invoices SET canceled_at = ?, cancel_reason = ?, updated_at = ? WHERE id = ?",
                     (ts(clock), reason, ts(clock), invoice_id))
    audit.record(conn, clock, "invoice", invoice_id, "cancel", new={"canceled_obligations": [o["id"] for o in open_obs]},
                 details=reason)
    _check_invariant(conn, invoice_id)
    return len(open_obs)


def add_document(conn: sqlite3.Connection, clock: Clock, paths: DataPaths, invoice_id: int, staged: StagedFile,
                 replaces_id: int | None = None) -> int:
    """Attach a (new or replacement) invoice document. Inside a transaction."""
    get_row(conn, invoice_id)
    if replaces_id is not None:  # validate fully BEFORE the file is moved into storage
        old = attachments.get(conn, replaces_id)
        require(old["invoice_id"] == invoice_id, he.FILE_REPLACE_MISMATCH)
        require(old["superseded_by"] is None, he.DB_ERRORS["attachment_already_superseded"])
    new_id = attachments.commit_staged(conn, paths, clock, staged, invoice_id=invoice_id, kind="invoice")
    if replaces_id is not None:
        attachments.supersede(conn, clock, replaces_id, new_id)
    return new_id


def add_receipt(conn: sqlite3.Connection, clock: Clock, paths: DataPaths, entry_id: int, staged: StagedFile,
                replaces_id: int | None = None) -> int:
    payments.get(conn, entry_id)
    if replaces_id is not None:
        old = attachments.get(conn, replaces_id)
        require(old["payment_entry_id"] == entry_id, he.FILE_REPLACE_MISMATCH)
        require(old["superseded_by"] is None, he.DB_ERRORS["attachment_already_superseded"])
    new_id = attachments.commit_staged(conn, paths, clock, staged, payment_entry_id=entry_id, kind="receipt")
    if replaces_id is not None:
        attachments.supersede(conn, clock, replaces_id, new_id)
    return new_id


def invoice_id_for_obligation(conn: sqlite3.Connection, obligation_id: int) -> int | None:
    row = conn.execute("SELECT invoice_id FROM obligations WHERE id = ?", (obligation_id,)).fetchone()
    if row is None:
        raise NotFound(f"obligation {obligation_id}")
    return row["invoice_id"]
