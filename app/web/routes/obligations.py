"""Obligation and payment actions (dialogs on the invoice details page)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from app.db.connection import transaction
from app.db.errors import hebrew_message
from app.domain.errors import ValidationError
from app.i18n import he
from app.services import attachments, invoices, obligations, payments
from app.services.common import NotFound
from app.web.deps import get_conn
from app.web.forms import FormReader, stage_file
from app.web.routes.common import redirect
from app.web.routes.invoices import render_invoice

router = APIRouter()


def _invoice_of(conn, obligation_id: int) -> int:
    invoice_id = invoices.invoice_id_for_obligation(conn, obligation_id)
    if invoice_id is None:  # recurring occurrences without an invoice arrive in Phase D
        raise NotFound(f"obligation {obligation_id} has no invoice")
    return invoice_id


def _dialog_error(request, conn, invoice_id, name, reader, **extra):
    return render_invoice(request, conn, invoice_id, status=422,
                          dialog={"name": name, "errors": reader.errors, "values": reader.values, **extra})


def _read_payment(reader: FormReader) -> payments.PaymentInput | None:
    amount = reader.amount("amount")
    paid_on = reader.date("paid_on")
    method = reader.choice("method", payments.METHODS, he.PAYMENT_METHOD_REQUIRED)
    if reader.errors:
        return None
    return payments.PaymentInput(amount, paid_on, method, reader.text("reference"), reader.text("notes"))


@router.get("/obligations/{obligation_id}")
def obligation_page(obligation_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    return RedirectResponse(f"/invoices/{_invoice_of(conn, obligation_id)}#ob-{obligation_id}", status_code=303)


@router.post("/obligations/{obligation_id}/payments")
async def record_payment(obligation_id: int, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    state = request.app.state
    invoice_id = _invoice_of(conn, obligation_id)
    reader = FormReader(await request.form())
    data = _read_payment(reader)
    staged = stage_file(reader, state.paths, attachments.max_upload_bytes(conn))
    if data is not None and not reader.errors:
        try:
            with transaction(conn):
                result = payments.record(conn, state.clock, state.paths, obligation_id, data,
                                         request_token=reader.text("request_token"), receipt=staged)
        except ValidationError as exc:
            reader.add(exc)
        except sqlite3.IntegrityError as exc:
            reader.errors["_form"] = hebrew_message(exc)
        else:
            msg = ("payment_already_recorded" if result.already_recorded
                   else "payment_recorded_full" if result.now_paid_in_full else "payment_recorded")
            return redirect(f"/invoices/{invoice_id}", msg, f"ob-{obligation_id}")
    return _dialog_error(request, conn, invoice_id, "pay", reader, obligation_id=obligation_id, staged=staged)


@router.post("/obligations/{obligation_id}/postpone")
async def postpone(obligation_id: int, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    invoice_id = _invoice_of(conn, obligation_id)
    reader = FormReader(await request.form())
    new_date = reader.date("new_due_date")
    if not reader.errors:
        try:
            with transaction(conn):
                obligations.change_due_date(conn, request.app.state.clock, obligation_id, new_date,
                                            reader.text("reason"),
                                            move_manual_reminders=reader.checkbox("move_reminders"))
        except ValidationError as exc:
            reader.add(exc, "new_due_date")
        else:
            return redirect(f"/invoices/{invoice_id}", "postponed", f"ob-{obligation_id}")
    return _dialog_error(request, conn, invoice_id, "postpone", reader, obligation_id=obligation_id)


@router.post("/obligations/{obligation_id}/cancel")
async def cancel_obligation(obligation_id: int, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    invoice_id = _invoice_of(conn, obligation_id)
    reader = FormReader(await request.form())
    try:
        with transaction(conn):
            obligations.cancel(conn, request.app.state.clock, obligation_id, reader.text("reason"))
    except ValidationError as exc:
        reader.add(exc, "reason")
        return _dialog_error(request, conn, invoice_id, "cancel-obligation", reader, obligation_id=obligation_id)
    return redirect(f"/invoices/{invoice_id}", "obligation_canceled", f"ob-{obligation_id}")


@router.post("/payment-entries/{entry_id}/void")
async def void_payment(entry_id: int, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    entry = payments.get(conn, entry_id)
    invoice_id = _invoice_of(conn, entry["obligation_id"])
    reader = FormReader(await request.form())
    correct = reader.checkbox("correct")
    correction = _read_payment(reader) if correct else None
    if not reader.text("void_reason"):
        reader.errors.setdefault("void_reason", he.VOID_REASON_REQUIRED)
    if not reader.errors:
        try:
            with transaction(conn):
                payments.void(conn, request.app.state.clock, entry_id, reader.text("void_reason"),
                              correction=correction, request_token=reader.text("request_token"))
        except ValidationError as exc:
            reader.add(exc)
        except sqlite3.IntegrityError as exc:
            reader.errors["_form"] = hebrew_message(exc)
        else:
            return redirect(f"/invoices/{invoice_id}", "payment_corrected" if correct else "payment_voided",
                            "payments")
    return _dialog_error(request, conn, invoice_id, "void", reader, entry_id=entry_id)


@router.post("/payment-entries/{entry_id}/receipts")
async def add_receipt(entry_id: int, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    state = request.app.state
    entry = payments.get(conn, entry_id)
    invoice_id = _invoice_of(conn, entry["obligation_id"])
    reader = FormReader(await request.form())
    replaces = reader.int_id("replaces_id")
    staged = stage_file(reader, state.paths, attachments.max_upload_bytes(conn))
    if staged is None and "file" not in reader.errors:
        reader.errors["file"] = he.FILE_REQUIRED
    if not reader.errors:
        try:
            with transaction(conn):
                invoices.add_receipt(conn, state.clock, state.paths, entry_id, staged, replaces)
        except ValidationError as exc:
            reader.add(exc, "file")
        else:
            return redirect(f"/invoices/{invoice_id}", "document_replaced" if replaces else "receipt_added",
                            "payments")
    return _dialog_error(request, conn, invoice_id, "receipt", reader, entry_id=entry_id)
